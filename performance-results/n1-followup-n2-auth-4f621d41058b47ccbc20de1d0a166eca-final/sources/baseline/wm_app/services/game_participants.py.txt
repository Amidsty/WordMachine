"""Participation storage boundary; shared game rules live in game.py.

The relation is authoritative in mode 1. Old JSON is never used as a fallback,
including after an explicit conversion (when it remains an archival value).
"""

import json
from collections import defaultdict
from datetime import datetime

from .errors import GameError
from .legacy_game import unique_ids


def invalid_participants():
    return GameError(
        'Game participation requires review; run audit-legacy', 409, 'invalid_game_participants'
    )


def relational(game):
    # Missing metadata is only supported for pre-migration audit/unit-test input.
    mode, count = game.get('participant_mode', 0), game.get('participant_count')
    if (
        type(mode) is not int
        or mode not in (0, 1)
        or (mode == 0 and count is not None)
        or (mode == 1 and (type(count) is not int or count <= 0))
    ):
        raise invalid_participants()
    return mode == 1


def validate_ids(ids, owner_id):
    if (
        not ids
        or any(type(uid) is not int or uid <= 0 for uid in ids)
        or len(set(ids)) != len(ids)
        or type(owner_id) is not int
        or owner_id not in ids
    ):
        raise invalid_participants()


def validate_rows(game, rows):
    ids = [row['user_id'] for row in rows]
    validate_ids(ids, game['ownerid'])
    if len(rows) != game['participant_count']:
        raise invalid_participants()
    for index, row in enumerate(rows):
        if (
            type(row.get('position')) is not int
            or row['position'] != index
            or not isinstance(row.get('recorded_at'), datetime)
            or (row.get('joined_at') is not None and not isinstance(row['joined_at'], datetime))
        ):
            raise invalid_participants()
    return ids


def load_many(cursor, games):
    """Batch the current lobby page, or a single locked/read game; never scan all memberships."""
    normalized = []
    for game in games:
        if relational(game):
            normalized.append(game)
        else:
            game['users'] = unique_ids(game['users'])
    if not normalized:
        return
    ids = [game['id'] for game in normalized]
    placeholders = ', '.join(['%s'] * len(ids))
    cursor.execute(
        """SELECT game_id, user_id, position, joined_at, recorded_at FROM game_participant
                      WHERE game_id IN ("""
        + placeholders
        + ') ORDER BY game_id, position',
        ids,
    )
    rows = defaultdict(list)
    for row in cursor.fetchall():
        rows[row['game_id']].append(row)
    for game in normalized:
        game['_participants'] = rows[game['id']]
        game['users'] = validate_rows(game, game['_participants'])


def lock_references(cursor, ids):
    # FK inserts otherwise take shared user locks in shuffled turn order, which
    # can deadlock with another game's ascending exclusive rating locks.
    # Acquire every user reference in the same ID order BEFORE touching children.
    for uid in sorted(set(ids)):
        cursor.execute('SELECT id FROM user WHERE id = %s FOR SHARE', (uid,))
        if cursor.fetchone() is None:
            raise invalid_participants()


def save(cursor, game, *, historical=False):
    """Persist the already-authorized member order inside the caller's game transaction.

    historical is only for explicit conversion: unknown join timestamps stay NULL.
    Routine calls only reorder waiting games; started games never rewrite rows.
    """
    ids = game['users']
    if not relational(game):
        cursor.execute('UPDATE game SET users = %s WHERE id = %s', (json.dumps(ids), game['id']))
        return
    validate_ids(ids, game['ownerid'])
    previous = {row['user_id']: row for row in game.get('_participants', [])}
    lock_references(cursor, [*previous, *ids])
    # MySQL unique constraints are immediate, not deferrable. Move existing slots
    # to a disjoint positive range, then assign the final order. Keep row identity
    # and timestamps; do not delete/reinsert every member just to reshuffle.
    offset = len(previous) + len(ids)
    if offset + len(previous) > 2147483647:
        raise invalid_participants()
    if previous:
        cursor.execute(
            'UPDATE game_participant SET position = position + %s WHERE game_id = %s',
            (offset, game['id']),
        )
        for uid in sorted(previous.keys() - set(ids)):
            cursor.execute(
                'DELETE FROM game_participant WHERE game_id = %s AND user_id = %s',
                (game['id'], uid),
            )
    now = datetime.utcnow()
    rows = []
    for position, uid in enumerate(ids):
        if uid in previous:
            cursor.execute(
                'UPDATE game_participant SET position = %s WHERE game_id = %s AND user_id = %s',
                (position, game['id'], uid),
            )
            row = {**previous[uid], 'position': position}
        else:
            joined_at = None if historical else now
            cursor.execute(
                """INSERT INTO game_participant (game_id, user_id, position, joined_at, recorded_at)
                              VALUES (%s, %s, %s, %s, %s)""",
                (game['id'], uid, position, joined_at, now),
            )
            row = {
                'game_id': game['id'],
                'user_id': uid,
                'position': position,
                'joined_at': joined_at,
                'recorded_at': now,
            }
        rows.append(row)
    cursor.execute('UPDATE game SET participant_count = %s WHERE id = %s', (len(ids), game['id']))
    game['participant_count'], game['_participants'] = len(ids), rows
