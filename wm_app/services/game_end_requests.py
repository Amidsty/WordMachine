"""Private, durable requests to end a running game; never end or score it.

Reuse game_request's durable receipt rather than duplicating a message in memory.
No game.version change or public Socket broadcast. One message per actor/game,
serialized by the game lock; original UUID retries retain the historical receipt.
"""

import json
import unicodedata
from datetime import datetime

from ..db import reading, transaction
from ..security.permissions import GAME_END_MIN_LEVEL, admin_level, can_end_game
from . import game_requests
from .auth import public_person
from .errors import GameError
from .pagination import ListQuery, page_offset

ACTION = 'end_request'


def message(value):
    if not isinstance(value, str):
        raise GameError('End request message must be 1–500 characters', 400, 'invalid_end_request')
    value = value.strip()
    if not 1 <= len(value) <= 500 or any(
        unicodedata.category(char) in ('Cc', 'Cs') and char != '\n' for char in value
    ):
        raise GameError('End request message must be 1–500 characters', 400, 'invalid_end_request')
    return value


def _actor(cursor, uid, *, lock=False):
    cursor.execute(
        'SELECT id, deleted, admin_level FROM user WHERE id=%s' + (' FOR UPDATE' if lock else ''),
        (uid,),
    )
    actor = cursor.fetchone()
    if actor is None or actor['deleted'] != 0:
        raise GameError('Account is no longer active', 403, 'forbidden')
    return actor


def send(game_id, uid, data):
    if set(data) != {'request_id', 'message'} or data.get('request_id') is None:
        raise GameError('request_id and message are required', 400, 'invalid_parameters')
    request_id = game_requests.validate_options(data['request_id'])[0]
    content = message(data['message'])
    with transaction() as cursor:
        replay = game_requests.reserve(
            cursor, uid, request_id, ACTION, game_id, {'message': content}, None
        )
        cursor.execute(
            'SELECT id, ownerid, status, version FROM game WHERE id=%s FOR UPDATE', (game_id,)
        )
        current = cursor.fetchone()
        if current is None:
            raise GameError('Game not found', 404, 'not_found')
        actor = _actor(cursor, uid, lock=True)
        if replay is not None:
            return replay  # Acknowledges the original message, not a new send/end command.
        if current['status'] != 0:
            raise GameError('Only running games accept end requests', 409, 'game_not_running')
        if can_end_game(actor, current['ownerid']):
            raise GameError('Use the reviewed manual end action', 403, 'forbidden')
        cursor.execute(
            'SELECT request_id FROM game_request WHERE game_id=%s AND actor_id=%s AND action=%s LIMIT 1',
            (game_id, uid, ACTION),
        )
        if cursor.fetchone() is not None:
            raise GameError(
                'You already sent an end request for this game', 409, 'end_request_exists'
            )
        return game_requests.complete(
            cursor,
            uid,
            request_id,
            game_id,
            current['version'],
            {
                'game_id': game_id,
                'sender_id': uid,
                'message': content,
                'sent_at': datetime.utcnow().isoformat() + 'Z',
            },
        )


def _public(row):
    try:
        receipt = json.loads(row['response'])
        if (
            receipt['game_id'] != row['game_id']
            or receipt['sender_id'] != row['actor_id']
            or receipt['request_id'] != row['request_id']
            or message(receipt['message']) != receipt['message']
            or not isinstance(receipt['sent_at'], str)
        ):
            raise ValueError('Invalid message receipt')
        datetime.fromisoformat(receipt['sent_at'].removesuffix('Z'))
    except (KeyError, TypeError, ValueError, GameError):
        raise GameError(
            'Stored end request requires review', 503, 'invalid_request_record'
        ) from None
    return {
        'game_id': row['game_id'],
        'request_id': row['request_id'],
        'message': receipt['message'],
        'sent_at': receipt['sent_at'],
        'game_name': row['name'],
        'status': row['status'],
        'owner_id': row['ownerid'],
        'sender': public_person(
            {
                'id': row['actor_id'],
                'username': row['username'],
                'rating': row['rating'],
                'deleted': row['deleted'],
            }
        ),
    }


def listing(uid, query=ListQuery(), *, game_id=None, include_finished=False):
    with reading() as cursor:
        actor = _actor(cursor, uid)
        where, params = 'r.action=%s', [ACTION]
        # Private messages: current owner/admins can read; everyone else ONLY their own.
        if admin_level(actor) < GAME_END_MIN_LEVEL:
            where += ' AND (g.ownerid=%s OR r.actor_id=%s)'
            params.extend([uid, uid])
        if game_id is not None:
            where += ' AND r.game_id=%s'
            params.append(game_id)
        if not include_finished:
            where += ' AND g.status=0'
        if query.q:
            where += " AND g.name LIKE %s ESCAPE '!'"
            params.append(query.like)
        source = 'game_request r JOIN game g ON g.id=r.game_id LEFT JOIN user u ON u.id=r.actor_id'
        cursor.execute('SELECT COUNT(*) AS total FROM ' + source + ' WHERE ' + where, params)
        pagination = query.metadata(cursor.fetchone()['total'])
        cursor.execute(
            'SELECT r.actor_id, r.request_id, r.game_id, r.response, g.name, g.status, g.ownerid, '
            'u.username, u.rating, u.deleted FROM '
            + source
            + ' WHERE '
            + where
            + ' ORDER BY r.created_at DESC, r.actor_id, r.request_id LIMIT %s OFFSET %s',
            [*params, query.per_page, page_offset(pagination)],
        )
        return {'requests': [_public(row) for row in cursor.fetchall()], 'pagination': pagination}
