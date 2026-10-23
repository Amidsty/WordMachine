"""One write path for future settlements, including still-running legacy games.

Historical JSON is an untouched prefix, never a second writable rating ledger.
The caller owns the game lock and ascending user locks; no commit/DDL here.
"""

import math
from datetime import datetime

from . import game_rating_policy, rating_events, weighted_games
from .errors import GameError
from .legacy_game import invalid_data, json_list
from .rating import MAX_RATING, MIN_RATING, RATING_VERSION, rating_delta


def invalid_settlement():
    return GameError(
        'Game settlement requires review; run audit-legacy', 409, 'invalid_game_settlement'
    )


def relational(game):
    mode = game.get('settlement_mode', 0)
    if type(mode) is not int or mode not in (0, 1):
        raise invalid_settlement()
    return mode == 1


def final_perfs(game):
    perfs = {}
    for answer in game['result']:
        if not isinstance(answer, dict):
            raise invalid_data()
        uid, perf = answer.get('uid'), answer.get('perf')
        if (
            type(uid) is not int
            or uid not in game['users']
            or type(perf) not in (int, float)
            or not math.isfinite(perf)
        ):
            raise invalid_data()  # Missing legacy Perf must never be guessed.
        perfs[uid] = perf
    return perfs


def validate_header(header):
    if (
        header.get('rating_version')
        not in ('legacy-v1', *weighted_games.RATING_VERSIONS, game_rating_policy.UNRATED_VERSION)
        or (
            header.get('rating_version') == game_rating_policy.UNRATED_VERSION
            and header.get('rated_count') != 0
        )
        or type(header.get('rated_count')) is not int
        or header['rated_count'] < 0
        or not isinstance(header.get('recorded_at'), datetime)
        or (header.get('settled_at') is not None and not isinstance(header['settled_at'], datetime))
    ):
        raise invalid_settlement()


def validate_entry(row):
    if row.get('rule_version', RATING_VERSION) not in (
        RATING_VERSION,
        *weighted_games.RATING_VERSIONS,
    ):
        raise invalid_settlement()
    for field in ('id', 'game_id', 'user_id'):
        if type(row.get(field)) is not int or row[field] <= 0:
            raise invalid_settlement()
    for field in ('rating_before', 'rating_after'):
        if type(row.get(field)) is not int or not MIN_RATING <= row[field] <= MAX_RATING:
            raise invalid_settlement()
    if (
        type(row.get('delta')) is not int
        or row['rating_before'] + row['delta'] != row['rating_after']
        or type(row.get('perf')) not in (int, float)
        or not math.isfinite(row['perf'])
    ):
        raise invalid_settlement()


def validate_rows(game, header, rows):
    rated = game_rating_policy.rated(game)
    if not rated and not relational(game):
        raise invalid_settlement()
    if not relational(game):
        if header is not None or rows:
            raise invalid_settlement()
        return
    if game['status'] != 1:
        if game['status'] not in (-1, 0, 2) or header is not None or rows:
            raise invalid_settlement()
        return
    if header is None or header.get('game_id') != game['id']:
        raise invalid_settlement()
    validate_header(header)
    try:
        perfs = final_perfs(game)
    except GameError:
        raise invalid_settlement() from None
    expected_rule = (
        (
            weighted_games.rules(game).RATING_VERSION
            if weighted_games.enabled(game)
            else RATING_VERSION
        )
        if rated
        else game_rating_policy.UNRATED_VERSION
    )
    if (
        header['rating_version'] != expected_rule
        or len(rows) != header['rated_count']
        or len(rows) != (len(perfs) if rated else 0)
    ):
        raise invalid_settlement()
    seen = set()
    for row in rows:
        validate_entry(row)
        uid = row['user_id']
        if (
            row['game_id'] != game['id']
            or uid in seen
            or uid not in perfs
            or row['perf'] != perfs[uid]
            or row.get('rule_version', RATING_VERSION) != expected_rule
        ):
            raise invalid_settlement()
        seen.add(uid)


def load(cursor, game):
    if not relational(game):
        if not game_rating_policy.rated(game):
            raise invalid_settlement()
        return  # Already-finished legacy games stay legacy; audits also check stray rows.
    cursor.execute('SELECT * FROM game_settlement WHERE game_id = %s', (game['id'],))
    header = cursor.fetchone()
    cursor.execute('SELECT * FROM game_rating WHERE game_id = %s ORDER BY user_id', (game['id'],))
    sources = list(cursor.fetchall())
    validate_rows(game, header, sources)
    weighted_games.load_results(cursor, game, sources)


def legacy_history(value):
    history = json_list(value)
    seen = set()
    for entry in history:
        if (
            not isinstance(entry, dict)
            or type(entry.get('game_id')) is not int
            or entry['game_id'] <= 0
            or entry['game_id'] in seen
        ):
            raise invalid_data()
        seen.add(entry['game_id'])
    return history


def settle(cursor, game, users):
    """Record a new outcome, not a conversion/recalculation of a past settlement."""
    perfs = final_perfs(game)
    cursor.execute('SELECT game_id FROM game_settlement WHERE game_id = %s', (game['id'],))
    if cursor.fetchone() is not None:
        raise invalid_settlement()
    entries, heads = [], {}
    rated = game_rating_policy.rated(game)
    weighted = weighted_games.enabled(game)
    proposals = weighted_games.proposals(cursor, game, users) if weighted else {}
    rule = weighted_games.rules(game).RATING_VERSION if weighted else RATING_VERSION
    for uid in sorted(perfs) if rated else ():
        user = users[uid]
        history = legacy_history(user['ratinghistory'])
        if any(item['game_id'] == game['id'] for item in history):
            raise invalid_data()
        heads[uid] = rating_events.current(cursor, user)
        delta = (
            proposals[uid].competitive.delta + proposals[uid].bonus
            if weighted
            else rating_delta(user['rating'], perfs[uid])
        )
        after = user['rating'] + delta
        if not MIN_RATING <= after <= MAX_RATING:
            raise GameError('Rating exceeds supported INT range', 409, 'rating_out_of_range')
        entries.append((game['id'], uid, perfs[uid], user['rating'], delta, after))
    now = datetime.utcnow()
    # A header also records an empty settlement; zero answers is not un-settled.
    cursor.execute(
        """INSERT INTO game_settlement (game_id, rated_count, rating_version, settled_at, recorded_at)
                      VALUES (%s, %s, %s, %s, %s)""",
        (
            game['id'],
            len(entries),
            rule if rated else game_rating_policy.UNRATED_VERSION,
            now,
            now,
        ),
    )
    for entry in entries:
        cursor.execute(
            """INSERT INTO game_rating (game_id, user_id, perf, rating_before, delta, rating_after, rule_version)
                          VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (*entry, rule),
        )
        source_id = cursor.lastrowid
        if weighted:
            weighted_games.record(cursor, game, entry[1], source_id, proposals[entry[1]], now)
        rating_events.append_game(
            cursor,
            users[entry[1]],
            source_id,
            entry[3],
            entry[4],
            entry[5],
            heads[entry[1]],
            now,
            rule_version=rule,
        )
    cursor.execute('UPDATE game SET status = 1, settlement_mode = 1 WHERE id = %s', (game['id'],))
    game['status'], game['settlement_mode'] = 1, 1
    weighted_games.release(cursor, game)
    return perfs


def merge_history(user, rows, events=()):
    """Preserve legacy entries/order; validate both source facts and event authority."""
    rating_events.validate_history(user, rows, events)
    history = legacy_history(user['ratinghistory'])
    seen = {entry['game_id'] for entry in history}
    previous = None
    for row in rows:
        validate_entry(row)
        validate_header(row)
        if (
            not game_rating_policy.rated(row)
            or row['rating_version'] not in (RATING_VERSION, *weighted_games.RATING_VERSIONS)
            or row.get('rule_version', RATING_VERSION) != row['rating_version']
            or row['user_id'] != user['id']
            or row['game_id'] in seen
            or row['settlement_mode'] != 1
            or row['status'] != 1
            or row['rated_count'] == 0
            or (
                previous is not None
                and (
                    row['id'] <= previous['id']
                    or (not events and row['rating_before'] != previous['rating_after'])
                )
            )
        ):
            raise invalid_settlement()
        history.append(
            {'game_id': row['game_id'], 'delta': row['delta'], 'new_rating': row['rating_after']}
        )
        seen.add(row['game_id'])
        previous = row
    if (previous is None and user.get('rating_ledger_id') is not None) or (
        previous is not None
        and (
            (not events and previous['rating_after'] != user['rating'])
            or previous['id'] != user.get('rating_ledger_id')
        )
    ):
        raise invalid_settlement()
    return history


def histories(cursor, users):
    if not users:
        return []
    ids = [user['id'] for user in users]
    placeholders = ', '.join(['%s'] * len(ids))
    cursor.execute(
        """SELECT r.*, s.rated_count, s.rating_version, s.settled_at, s.recorded_at,
                             g.settlement_mode, g.status, g.rated FROM game_rating r
                      JOIN game_settlement s ON s.game_id = r.game_id JOIN game g ON g.id = r.game_id
                      WHERE r.user_id IN ("""
        + placeholders
        + ') ORDER BY r.user_id, r.id',
        ids,
    )
    source_rows = list(cursor.fetchall())
    weighted_games.check_sources(cursor, source_rows)
    grouped = {uid: [] for uid in ids}
    for row in source_rows:
        grouped[row['user_id']].append(row)
    events = rating_events.load_many(cursor, users)
    return [
        {
            'user_id': user['id'],
            'ratinghistory': merge_history(user, grouped[user['id']], events[user['id']]),
        }
        for user in users
    ]
