"""Public score projections; only explicitly opted-in manual metadata is public.

Hidden reasons/actors are omitted from the response, not merely hidden by the UI.
Raw archives, request UUIDs, event heads and private audits are never projected.

All reads share one MVCC snapshot. Rating validates the complete existing ledger;
Perf batches and validates the selected finished-game page, without English lookup.
"""

import json
import math
from collections import defaultdict

from ..db import reading
from . import (
    game_answers,
    game_names,
    game_participants,
    game_rating_policy,
    game_settlements,
    rating_events,
    weighted_games,
)
from .errors import ApiError
from .legacy_game import invalid_data, json_list, unique_ids
from .pagination import ListQuery, page_offset
from .rating import MAX_RATING, MIN_RATING


def timestamp(value):
    return value.isoformat() + 'Z' if value is not None else None


def finite_perf(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def legacy_amount(entry, key):
    value = entry.get(key)
    if value is not None and (
        type(value) is not int or (key == 'new_rating' and not MIN_RATING <= value <= MAX_RATING)
    ):
        raise invalid_data()
    if key == 'delta' and value is not None and not -(2**32 - 1) <= value <= 2**32 - 1:
        raise invalid_data()
    return value


def rating_rows(cursor, user, query):
    cursor.execute(
        'SELECT r.*, s.rated_count, s.rating_version, s.settled_at, s.recorded_at, '
        'g.settlement_mode, g.status, g.rated FROM game_rating r '
        'JOIN game_settlement s ON s.game_id=r.game_id JOIN game g ON g.id=r.game_id '
        'WHERE r.user_id=%s ORDER BY r.id',
        (user['id'],),
    )
    sources = list(cursor.fetchall())
    weighted_games.check_sources(cursor, sources)
    events = rating_events.load_many(cursor, [user])[user['id']]
    # Also validates the legacy prefix, ledger pointer, event sources and final balance.
    game_settlements.merge_history(user, sources, events)
    rows = [
        {
            'source': 'legacy',
            'game_id': entry['game_id'],
            'recorded_at': None,
            'before': None,
            'delta': legacy_amount(entry, 'delta'),
            'after': legacy_amount(entry, 'new_rating'),
        }
        for entry in game_settlements.legacy_history(user['ratinghistory'])
    ]
    event_sources = {event['game_rating_id'] for event in events if event['kind'] == 'game'}
    by_id = {source['id']: source for source in sources}
    for source in sources:
        if source['id'] not in event_sources:
            rows.append(
                {
                    'source': 'game',
                    'game_id': source['game_id'],
                    'recorded_at': timestamp(source['settled_at']),
                    'before': source['rating_before'],
                    'delta': source['delta'],
                    'after': source['rating_after'],
                }
            )
    for event in events:
        rows.append(
            {
                'source': event['kind'],
                'game_id': by_id[event['game_rating_id']]['game_id']
                if event['kind'] == 'game'
                else None,
                'recorded_at': timestamp(event['recorded_at']),
                'before': event['rating_before'],
                'delta': event['delta'],
                'after': event['rating_after'],
            }
        )
        if event['kind'] == 'manual':
            manual = event['_manual_source']  # Validated by load_many/merge_history.
            if manual.get('publish_reason', 0) == 1:
                rows[-1]['reason'] = manual['reason']
            if manual.get('publish_actor', 0) == 1:
                rows[-1]['actor_id'] = manual['actor_id']
    pagination = query.metadata(len(rows))
    offset = page_offset(pagination)
    selected = list(reversed(rows))[offset : offset + query.per_page]
    ids = [row['game_id'] for row in selected if row['game_id'] is not None]
    games = {}
    if ids:
        cursor.execute(
            'SELECT id, name FROM game WHERE id IN (' + ','.join(['%s'] * len(ids)) + ')', ids
        )
        games = {row['id']: row for row in cursor.fetchall()}
    versions = {s['game_id']: s.get('rule_version') for s in sources}
    weighted = [
        row['game_id']
        for row in selected
        if row['source'] == 'game'
        and versions.get(row['game_id']) in weighted_games.RATING_VERSIONS
    ]
    parts = grouped(cursor, 'weighted_result', weighted, 'game_id, user_id') if weighted else {}
    for row in selected:
        row['rule_version'] = (
            versions.get(row['game_id'])
            if row['source'] == 'game'
            else ('manual-v1' if row['source'] == 'manual' else None)
        )
        part = next((p for p in parts.get(row['game_id'], []) if p['user_id'] == user['id']), None)
        if row['rule_version'] in weighted_games.RATING_VERSIONS and part is None:
            raise weighted_games.invalid()
        row['competitive_delta'] = part['competitive_delta'] if part else None
        row['newcomer_bonus'] = part['newcomer_bonus'] if part else None
        current = games.get(row['game_id'])
        row['game_available'] = current is not None
        row['game_name'] = game_names.stored(current) if current else None
    return {'history': selected, 'pagination': pagination}


def grouped(cursor, table, ids, order):
    cursor.execute(
        'SELECT * FROM '
        + table
        + ' WHERE game_id IN ('
        + ','.join(['%s'] * len(ids))
        + ') ORDER BY '
        + order,
        ids,
    )
    result = defaultdict(list)
    for row in cursor.fetchall():
        result[row['game_id']].append(row)
    return result


def perf_rows(cursor, uid, query):
    # Archived JSON must never establish membership of a normalized game.
    # Separate the indexed user-membership branch from legacy JSON scans. The
    # disjoint storage modes make UNION ALL safe, without duplicate game IDs.
    candidates = """(SELECT g.id FROM game_participant p JOIN game g ON g.id=p.game_id
        WHERE p.user_id=%s AND g.participant_mode=1 AND g.status=1
        UNION ALL SELECT g.id FROM game g WHERE g.participant_mode=0 AND g.status=1
        AND JSON_CONTAINS(CASE WHEN JSON_VALID(g.users) THEN g.users ELSE '[]' END, %s)=1) matched"""
    source = ' FROM ' + candidates + ' JOIN game g ON g.id=matched.id'
    params = (uid, json.dumps(uid))
    cursor.execute('SELECT COUNT(*) AS total' + source, params)
    pagination = query.metadata(cursor.fetchone()['total'])
    cursor.execute(
        'SELECT g.*' + source + ' ORDER BY g.id DESC LIMIT %s OFFSET %s',
        (*params, query.per_page, page_offset(pagination)),
    )
    games = list(cursor.fetchall())
    if not games:
        return {'history': [], 'pagination': pagination}
    game_participants.load_many(cursor, games)
    ids = [row['id'] for row in games]
    answers = grouped(cursor, 'game_answer', ids, 'game_id, position')
    headers = grouped(cursor, 'game_settlement', ids, 'game_id')
    ratings = grouped(cursor, 'game_rating', ids, 'game_id, user_id')
    weighted_ids = [g['id'] for g in games if weighted_games.enabled(g)]
    weighted_data = (
        {
            table: grouped(
                cursor,
                table,
                weighted_ids,
                'game_id, user_id' if table != 'weighted_answer' else 'game_id, position',
            )
            for table in (
                'game_rating_snapshot',
                'weighted_answer',
                'weighted_result',
                'newcomer_award',
            )
        }
        if weighted_ids
        else {}
    )
    rows = []
    for current in games:
        if uid not in current['users']:
            raise invalid_data()
        current['wordlist'] = unique_ids(current['wordlist'])
        normalized = game_answers.relational(current)
        if normalized:
            entries = game_answers.validate_rows(current, answers[current['id']])
        else:
            if answers[current['id']]:
                raise game_answers.invalid_answers()
            entries = json_list(current['result'])
            if len(entries) > len(current['wordlist']) or any(
                not isinstance(entry, dict)
                or type(entry.get('uid')) is not int
                or entry['uid'] not in current['users']
                or (entry.get('perf') is not None and not finite_perf(entry['perf']))
                for entry in entries
            ):
                raise invalid_data()
            game_answers.validate_rule_order(entries)
        current['result'] = entries
        if weighted_games.enabled(current):
            gid = current['id']
            weighted_games.validate_answers(
                current,
                weighted_data['game_rating_snapshot'][gid],
                weighted_data['weighted_answer'][gid],
            )
            weighted_games.validate_results(
                current,
                ratings[gid],
                weighted_data['weighted_result'][gid],
                weighted_data['newcomer_award'][gid],
            )
        header = headers[current['id']][0] if headers[current['id']] else None
        game_settlements.validate_rows(current, header, ratings[current['id']])
        own = [entry for entry in entries if entry['uid'] == uid]
        perf = own[-1].get('perf') if own else None
        if perf is not None and not finite_perf(perf):
            raise game_answers.invalid_answers()
        rows.append(
            {
                'game_id': current['id'],
                'game_name': game_names.stored(current),
                'rated': game_rating_policy.rated(current),
                'perf': perf,
                'answered_count': len(own),
                'rule_version': own[-1].get('rating_version') if own else None,
                'recorded_at': timestamp(header['settled_at']) if header else None,
                'source': 'answers' if normalized else 'legacy',
                'missing_reason': ('no_answers' if not own else 'missing_perf')
                if perf is None
                else None,
            }
        )
    return {'history': rows, 'pagination': pagination}


def account(uid):
    with reading() as cursor:
        cursor.execute('SELECT id, rating FROM user WHERE id=%s AND deleted=0', (uid,))
        user = cursor.fetchone()
        if user is None:
            raise ApiError('User not found', 404, 'not_found')
        return {'user_id': uid, 'rating_state': weighted_games.public_account(cursor, user)}


def listing(uid, kind='rating', query=ListQuery()):
    if kind not in ('rating', 'perf') or query.q:
        raise ApiError('History kind must be rating or perf; search is not supported')
    with reading() as cursor:
        cursor.execute(
            'SELECT id, rating, ratinghistory, rating_ledger_id, rating_event_id FROM user WHERE id=%s AND deleted=0',
            (uid,),
        )
        user = cursor.fetchone()
        if user is None:
            raise ApiError('User not found', 404, 'not_found')
        result = (
            rating_rows(cursor, user, query) if kind == 'rating' else perf_rows(cursor, uid, query)
        )
        return {'user_id': uid, 'kind': kind, 'current_rating': user['rating'], **result}
