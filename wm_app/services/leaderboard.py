"""Public top-100 leaderboard with competition ranks and participation tie breaking."""

import json

from ..db import reading
from . import game_answers, game_participants
from .errors import ApiError
from .legacy_game import invalid_data, json_list
from .pagination import ListQuery, page_offset


def participation_counts(cursor, ids):
    """Finished games with membership and at least one saved answer, once per game.

    Both Rated and Unrated count. Storage modes, not archival JSON or rating
    events, select the authority. This is an attendance read, not a score audit.
    Batch ranking candidates (including cutoff ties), never one query per user.
    """
    counts = dict.fromkeys(ids, 0)
    if not ids:
        return counts
    placeholders = ','.join(['%s'] * len(ids))
    cursor.execute(
        'SELECT p.user_id, COUNT(*) AS total FROM game_participant p '
        'JOIN game g ON g.id=p.game_id '
        'WHERE p.user_id IN (' + placeholders + ') '
        'AND g.participant_mode=1 AND g.answer_mode=1 AND g.status=1 '
        'AND EXISTS (SELECT 1 FROM game_answer a '
        'WHERE a.game_id=g.id AND a.user_id=p.user_id) GROUP BY p.user_id',
        ids,
    )
    for row in cursor.fetchall():
        counts[row['user_id']] = row['total']

    # Legacy answers can coexist with either participant storage mode. Numeric
    # JSON membership is only a candidate filter; selected archives are decoded
    # strictly below. Corrupt matching records are not silently counted as zero.
    legacy_members = ' OR '.join(
        "JSON_CONTAINS(CASE WHEN JSON_VALID(g.users) THEN g.users ELSE '[]' END, %s)=1" for _ in ids
    )
    cursor.execute(
        'SELECT g.id, g.ownerid, g.participant_mode, g.participant_count, '
        'g.answer_mode, g.answer_count, g.users, g.result FROM game g '
        'WHERE g.status=1 AND g.answer_mode=0 AND ('
        '(g.participant_mode=1 AND EXISTS (SELECT 1 FROM game_participant p '
        'WHERE p.game_id=g.id AND p.user_id IN (' + placeholders + '))) '
        'OR (g.participant_mode=0 AND (' + legacy_members + ')))',
        [*ids, *(json.dumps(uid) for uid in ids)],
    )
    games = list(cursor.fetchall())
    game_participants.load_many(cursor, games)
    for current in games:
        game_answers.relational(current)  # Check legacy mode/count metadata.
        members = set(current['users'])
        entries = json_list(current['result'])
        if any(
            not isinstance(entry, dict)
            or type(entry.get('uid')) is not int
            or entry['uid'] not in members
            for entry in entries
        ):
            raise invalid_data()
        for uid in {entry['uid'] for entry in entries} & counts.keys():
            counts[uid] += 1
    return counts


def list_leaders(query=ListQuery()):
    if query.q:
        raise ApiError('Leaderboard search is not supported')
    with reading() as cursor:
        # Rating alone bounds the candidate universe, but cannot choose which
        # users survive a tie at the 100th row. Include ALL cutoff ties before
        # truncating by participation count. Keyset batches bound memory and SQL
        # parameter counts, not total work when a large group shares a Rating.
        cursor.execute(
            'SELECT id, username, introduction, rating FROM user WHERE deleted = 0 '
            'ORDER BY rating DESC, id ASC LIMIT 100'
        )
        batch = cursor.fetchall()
        cutoff = batch[-1]['rating'] if batch else None
        leaders = []
        while batch:
            counts = participation_counts(cursor, [user['id'] for user in batch])
            leaders.extend({**user, 'participation_count': counts[user['id']]} for user in batch)
            leaders.sort(
                key=lambda user: (
                    user['rating'] is None,
                    -(user['rating'] or 0),
                    -user['participation_count'],
                    user['id'],
                )
            )
            del leaders[100:]
            if len(batch) < 100:
                break
            # NULL remains after every recorded Rating, distinct from zero.
            # NULL-safe equality also includes the full missing-Rating group.
            cursor.execute(
                'SELECT id, username, introduction, rating FROM user WHERE deleted = 0 '
                'AND rating <=> %s AND id > %s ORDER BY id ASC LIMIT 100',
                (cutoff, batch[-1]['id']),
            )
            batch = cursor.fetchall()

    rank = 0
    for index, user in enumerate(leaders):
        if index == 0 or user['rating'] != leaders[index - 1]['rating']:
            rank = index + 1
        user['rank'] = rank
    pagination = query.metadata(len(leaders))
    offset = page_offset(pagination)
    return {'users': leaders[offset : offset + query.per_page], 'pagination': pagination}
