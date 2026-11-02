"""One paginated public history, joining saved facts before slicing the page."""

from datetime import datetime

from ..db import reading
from . import game_settlements, user_history
from .errors import ApiError
from .pagination import ListQuery, page_offset
from .score_timeline import moment


def project(records, perfs):
    by_game = {row['game_id']: row for row in perfs}
    if len(by_game) != len(perfs):
        raise game_settlements.invalid_settlement()
    rows, seen = [], set()
    for ordinal, rating in enumerate(records, 1):
        gid = rating['game_id']
        if gid is not None:
            if gid in seen:
                raise game_settlements.invalid_settlement()
            seen.add(gid)
        perf = by_game.pop(gid, None)
        if perf is not None and not perf['rated']:
            raise game_settlements.invalid_settlement()
        rows.append(
            {
                'key': f'rating:{ordinal}',
                # A missing Rating timestamp stays missing even if its paired Perf
                # has a date. The original Perf timestamp remains in the nested row.
                'recorded_at': rating['recorded_at'],
                'rating': rating,
                'perf': perf,
            }
        )
    rows.extend(
        {
            'key': f'game:{perf["game_id"]}',
            'recorded_at': perf['recorded_at'],
            'rating': None,
            'perf': perf,
        }
        for perf in by_game.values()
    )
    # Known dates newest first, unknown dates last. Ties use public ordinals /
    # game IDs for stable presentation, not a claim about transaction ordering.
    return sorted(
        rows,
        key=lambda row: (
            row['recorded_at'] is not None,
            moment(row['recorded_at']) or datetime.min,
            row['rating'] is not None,
            int(row['key'].split(':')[1]),
        ),
        reverse=True,
    )


def listing(uid, query=ListQuery()):
    if query.q:
        raise ApiError('Score history search is not supported')
    with reading() as cursor:
        cursor.execute(
            'SELECT id, rating, ratinghistory, rating_ledger_id, rating_event_id FROM user WHERE id=%s AND deleted=0',
            (uid,),
        )
        user = cursor.fetchone()
        if user is None:
            raise ApiError('User not found', 404, 'not_found')
        records, sources = user_history.rating_records(cursor, user)
        perfs = user_history.all_perfs(cursor, uid)
        rows = project(records, perfs)
        pagination = query.metadata(len(rows))
        offset = page_offset(pagination)
        selected = rows[offset : offset + query.per_page]
        user_history.decorate_ratings(
            cursor,
            uid,
            [row['rating'] for row in selected if row['rating'] is not None],
            sources,
        )
        return {'user_id': uid, 'history': selected, 'pagination': pagination}
