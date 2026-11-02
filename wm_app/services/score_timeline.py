"""Read-only full public timeline, joined in one RR snapshot, without re-scoring.

Rating ledger order is authoritative. Unchanged balances are projected only when
saved times establish an unambiguous interval; unknown dates/balances stay null.
Public point keys are game IDs or ledger ordinals, never internal event heads.
"""

from bisect import bisect_left, bisect_right
from datetime import datetime

from ..db import reading
from . import game_names, game_settlements, user_history
from .errors import ApiError


def moment(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


def unchanged_rating(records, current):
    """Build an interval lookup; never reorder a ledger to invent past balances."""
    dated = [row for row in records if row['recorded_at'] is not None]
    times = [moment(row['recorded_at']) for row in dated]
    undated_prefix = len(records) - len(dated)
    ordered = records[undated_prefix:] == dated and times == sorted(times)

    def at(value):
        time = moment(value)
        if time is None:
            return None
        if not records:
            # A completely empty validated ledger has no saved balance changes.
            return current
        if not ordered or not times:
            return None
        left, right = bisect_left(times, time), bisect_right(times, time)
        if left != right:
            # Equal timestamps do not establish which transaction came first.
            values = [dated[left]['before'], *(row['after'] for row in dated[left:right])]
            return values[0] if all(v == values[0] for v in values) else None
        if left == 0:
            return dated[0]['before'] if undated_prefix == 0 else None
        return dated[left - 1]['after']

    return at


def project(records, perfs, games, current):
    """Pure allowlisted projection. Missing Perf is not replaced by an older one."""
    by_game = {row['game_id']: row for row in perfs}
    carry = unchanged_rating(records, current)
    points = []
    for ordinal, row in enumerate(records, 1):
        gid = row['game_id']
        perf = by_game.pop(gid, None)
        if perf is not None and not perf['rated']:
            raise game_settlements.invalid_settlement()
        game = games.get(gid)
        points.append(
            {
                'key': f'manual:{ordinal}' if gid is None else f'game:{gid}',
                'kind': 'manual' if gid is None else 'rated',
                'game_id': gid,
                'game_available': game is not None,
                'game_name': game_names.stored(game) if game else None,
                'recorded_at': row['recorded_at'],
                'rating': row['after'],
                'rating_origin': 'recorded' if row['after'] is not None else 'unknown',
                'perf': perf['perf'] if perf else None,
                'perf_missing': perf['missing_reason']
                if perf
                else ('not_applicable' if gid is None else 'missing_perf'),
            }
        )
    for perf in by_game.values():
        rating = carry(perf['recorded_at'])
        points.append(
            {
                'key': f'game:{perf["game_id"]}',
                'kind': 'rated' if perf['rated'] else 'unrated',
                'game_id': perf['game_id'],
                'game_available': True,
                'game_name': perf['game_name'],
                'recorded_at': perf['recorded_at'],
                'rating': rating,
                'rating_origin': 'carried' if rating is not None else 'unknown',
                'perf': perf['perf'],
                'perf_missing': perf['missing_reason'],
            }
        )
    # Stable sort preserves ledger order for equal times. Unknown dates are not
    # disguised as room IDs, conversion timestamps, or the current date.
    return sorted(
        points,
        key=lambda row: (
            row['recorded_at'] is not None,
            moment(row['recorded_at']) or datetime.min,
        ),
    )


def listing(uid):
    with reading() as cursor:
        cursor.execute(
            'SELECT id, rating, ratinghistory, rating_ledger_id, rating_event_id FROM user WHERE id=%s AND deleted=0',
            (uid,),
        )
        user = cursor.fetchone()
        if user is None:
            raise ApiError('User not found', 404, 'not_found')
        records, _ = user_history.rating_records(cursor, user)
        # Bounded source batches, not a first-page-only chart. All batches and
        # the ledger remain in this same snapshot; output grows with history.
        perfs = user_history.all_perfs(cursor, uid)
        games = {row['game_id']: {'name': row['game_name']} for row in perfs}
        missing = list(
            {row['game_id'] for row in records if row['game_id'] is not None} - games.keys()
        )
        for start in range(0, len(missing), 100):
            ids = missing[start : start + 100]
            cursor.execute(
                'SELECT id, name FROM game WHERE id IN (' + ','.join(['%s'] * len(ids)) + ')', ids
            )
            games.update({row['id']: row for row in cursor.fetchall()})
        return {'user_id': uid, 'points': project(records, perfs, games, user['rating'])}
