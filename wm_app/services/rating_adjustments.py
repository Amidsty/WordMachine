"""Manual adjustments: reservation -> ordered users -> checks -> source/event/audit.

No game locks: the first MVCC read occurs AFTER user locks. Every start/end/answer
also owns these user locks. Never establish an earlier read snapshot in this path.
Passwords are rechecked under lock, never stored in fingerprints/receipts/audits.
"""

import hashlib
import json
from datetime import datetime

from pymysql import IntegrityError

from ..db import reading, transaction
from ..security.passwords import verify_password
from ..security.permissions import (
    RATING_EDIT_MIN_LEVEL,
    admin_level,
    lock_users,
    require_manage_user,
)
from . import game_participants, game_settlements, rating_events, weighted_games
from .admin_policy import audit
from .errors import ApiError
from .game_requests import validate_options
from .rating import MAX_RATING, MIN_RATING
from .validation import password, string


def _permit(actor, target):
    require_manage_user(actor, target, allow_self=True)
    if admin_level(actor) < RATING_EDIT_MIN_LEVEL:
        raise ApiError('Rating adjustments require level 4 or higher', 403, 'forbidden')
    if target['deleted'] != 0:
        raise ApiError(
            'Restore and review this account before adjusting Rating', 409, 'invalid_account_state'
        )


def _integer(value, name):
    if type(value) is not int or not MIN_RATING <= value <= MAX_RATING:
        raise ApiError(f'{name} must be a signed INT')
    return value


def parameters(data):
    fields = {
        'request_id',
        'expected_rating',
        'expected_event_id',
        'new_rating',
        'reason',
        'current_password',
    }
    if set(data) != fields:
        raise ApiError(
            'Rating adjustment requires request_id, expected_rating, expected_event_id, new_rating, reason and current_password'
        )
    request_id = validate_options(data['request_id'])[0]
    if request_id is None:
        raise ApiError('request_id is required')
    event_id = data['expected_event_id']
    if event_id is not None and (
        not isinstance(event_id, str)
        or not event_id.isascii()
        or not event_id.isdecimal()
        or len(event_id) > 19
        or event_id.startswith('0')
        or not 0 < int(event_id) <= 9223372036854775807
    ):
        raise ApiError('expected_event_id must be a canonical positive BIGINT string or null')
    return {
        'request_id': request_id,
        'expected_rating': _integer(data['expected_rating'], 'expected_rating'),
        'expected_event_id': event_id,
        'new_rating': _integer(data['new_rating'], 'new_rating'),
        'reason': string(data['reason'], 'Reason', minimum=1, maximum=500),
    }, password(data['current_password'], new=False)


def _reserve(cursor, actor_id, target_id, intent):
    encoded = json.dumps(
        [target_id, intent], sort_keys=True, separators=(',', ':'), ensure_ascii=True
    )
    digest = hashlib.sha256(encoded.encode('ascii')).hexdigest()
    try:
        cursor.execute(
            'INSERT INTO rating_adjustment_request (actor_id, request_id, payload_hash, created_at) VALUES (%s, %s, %s, UTC_TIMESTAMP(6))',
            (actor_id, intent['request_id'], digest),
        )
    except IntegrityError as error:
        if error.args[0] != 1062:
            raise
        cursor.execute(
            'SELECT payload_hash, response FROM rating_adjustment_request WHERE actor_id = %s AND request_id = %s FOR SHARE',
            (actor_id, intent['request_id']),
        )
        row = cursor.fetchone()
        if row is None or row['response'] is None:
            raise ApiError(
                'Stored request requires review', 503, 'invalid_request_record'
            ) from None
        if row['payload_hash'] != digest:
            raise ApiError(
                'request_id was already used for a different command', 409, 'request_id_conflict'
            ) from None
        try:
            result = json.loads(row['response'])
            if (
                not isinstance(result, dict)
                or result.get('request_id') != intent['request_id']
                or result.get('user_id') != target_id
                or result.get('rating_after') != intent['new_rating']
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise ApiError(
                'Stored request requires review', 503, 'invalid_request_record'
            ) from None
        return result
    return None


def running(cursor, uid):
    # Nonlocking reads only: user -> game FOR UPDATE would invert game write locks.
    # Legacy JSON memberships remain authoritative until explicitly converted.
    cursor.execute(
        'SELECT id, ownerid, users, participant_mode, participant_count FROM game WHERE status = 0'
    )
    games = cursor.fetchall()
    game_participants.load_many(cursor, games)
    for game in games:
        game_participants.validate_ids(game['users'], game['ownerid'])
    return any(uid in game['users'] for game in games)


def review(actor_id, target_id):
    with reading() as cursor:
        cursor.execute('SELECT * FROM user WHERE id IN (%s, %s)', (actor_id, target_id))
        users = {row['id']: row for row in cursor.fetchall()}
        if actor_id not in users or target_id not in users:
            raise ApiError('User not found', 404, 'not_found')
        actor, target = users[actor_id], users[target_id]
        _permit(actor, target)
        game_settlements.histories(cursor, [target])  # Full validation, not just the rendered tail.
        events = rating_events.load_many(cursor, [target])[target_id]
        cursor.execute('SELECT id, game_id FROM game_rating WHERE user_id = %s', (target_id,))
        games = {row['id']: row['game_id'] for row in cursor.fetchall()}
        entries = []
        for event in reversed(events[-50:]):
            manual = event.get('_manual_source', {})
            entries.append(
                {
                    'id': str(event['id']),
                    'kind': event['kind'],
                    'sequence': event['sequence'],
                    'rating_before': event['rating_before'],
                    'delta': event['delta'],
                    'rating_after': event['rating_after'],
                    'game_id': games.get(event['game_rating_id']),
                    'actor_id': manual.get('actor_id'),
                    'reason': manual.get('reason'),
                    'recorded_at': event['recorded_at'].isoformat() + 'Z',
                }
            )
        return {
            'user_id': target_id,
            'rating': target['rating'],
            'rating_state': weighted_games.public_account(cursor, target),
            'rating_event_id': str(target['rating_event_id'])
            if target['rating_event_id'] is not None
            else None,
            'running_game': running(cursor, target_id),
            'events': entries,
        }


def adjust(actor_id, target_id, data):
    intent, supplied_password = parameters(data)
    with transaction() as cursor:
        replay = _reserve(cursor, actor_id, target_id, intent)
        users = lock_users(cursor, [actor_id, target_id])
        actor, target = users[actor_id], users[target_id]
        _permit(actor, target)
        if not verify_password(actor['pwhash'], supplied_password):
            raise ApiError('Current password incorrect', 401, 'invalid_credentials')
        if replay is not None:
            return replay  # Re-authorized receipt, not a new write or a new balance assertion.
        head = str(target['rating_event_id']) if target['rating_event_id'] is not None else None
        if target['rating'] != intent['expected_rating'] or head != intent['expected_event_id']:
            raise ApiError(
                'Rating changed; review the current balance before creating a new request',
                409,
                'stale_rating',
            )
        if target['rating'] == intent['new_rating']:
            raise ApiError('Rating is unchanged')
        # First consistent read is here, AFTER ordered user locks, including any
        # wait for an in-flight start/settlement. Do not move this above lock_users.
        if running(cursor, target_id):
            raise ApiError('Cannot adjust Rating during a running game', 409, 'rating_game_running')
        game_settlements.histories(cursor, [target])
        previous = rating_events.current(cursor, target)
        now = datetime.utcnow()
        delta = intent['new_rating'] - target['rating']
        cursor.execute(
            'INSERT INTO manual_rating (user_id, actor_id, actor_level, request_id, last_game_rating_id, rating_before, delta, rating_after, reason, recorded_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (
                target_id,
                actor_id,
                admin_level(actor),
                intent['request_id'],
                target['rating_ledger_id'],
                target['rating'],
                delta,
                intent['new_rating'],
                intent['reason'],
                now,
            ),
        )
        source_id = cursor.lastrowid
        event_id = rating_events.append_manual(
            cursor, target, source_id, intent['new_rating'], previous, now
        )
        result = {
            'request_id': intent['request_id'],
            'user_id': target_id,
            'rating_before': target['rating'],
            'delta': delta,
            'rating_after': intent['new_rating'],
            'rating_event_id': str(event_id),
            'message': 'Rating adjusted',
        }
        audit(
            cursor,
            actor,
            target_id,
            'adjust-rating',
            {'rating': target['rating'], 'rating_event_id': head},
            {
                'rating': intent['new_rating'],
                'rating_event_id': str(event_id),
                'request_id': intent['request_id'],
            },
            reason=intent['reason'],
        )
        cursor.execute(
            'UPDATE rating_adjustment_request SET response = %s WHERE actor_id = %s AND request_id = %s',
            (json.dumps(result, ensure_ascii=True), actor_id, intent['request_id']),
        )
        return result
