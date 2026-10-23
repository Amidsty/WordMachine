"""Append-only balance authority, with game and explicit manual source facts.

The first event anchors the untouched legacy game-rating prefix. Callers own
ascending exclusive user locks for current()/append_*(); history reads are MVCC.
"""

from datetime import datetime

from .errors import GameError
from .rating import MAX_RATING, MIN_RATING

MAX_SEQUENCE = 2147483647


def invalid_event():
    return GameError(
        'Rating event chain requires review; run audit-legacy', 409, 'invalid_rating_event'
    )


def _positive(value):
    return type(value) is int and value > 0


def _amounts(row):
    if any(
        type(row.get(key)) is not int or not MIN_RATING <= row[key] <= MAX_RATING
        for key in ('rating_before', 'rating_after')
    ):
        raise invalid_event()
    if (
        type(row.get('delta')) is not int
        or row['rating_before'] + row['delta'] != row['rating_after']
        or not isinstance(row.get('recorded_at'), datetime)
    ):
        raise invalid_event()


def validate(row):
    if not isinstance(row, dict) or not {'previous_id', 'legacy_rating_id'} <= row.keys():
        raise invalid_event()
    if any(not _positive(row.get(key)) for key in ('id', 'user_id', 'sequence')):
        raise invalid_event()
    if row['sequence'] > MAX_SEQUENCE:
        raise invalid_event()
    if row.get('kind') == 'game':
        if (
            row.get('rule_version') not in ('legacy-v1', 'weighted-rating-v1')
            or not _positive(row.get('game_rating_id'))
            or row.get('manual_rating_id') is not None
        ):
            raise invalid_event()
    elif row.get('kind') == 'manual':
        if (
            row.get('rule_version') != 'manual-v1'
            or row.get('game_rating_id') is not None
            or not _positive(row.get('manual_rating_id'))
        ):
            raise invalid_event()
    else:
        raise invalid_event()
    previous, anchor = row['previous_id'], row['legacy_rating_id']
    if row['sequence'] == 1:
        if previous is not None or (anchor is not None and not _positive(anchor)):
            raise invalid_event()
    elif not _positive(previous) or previous >= row['id'] or anchor is not None:
        raise invalid_event()
    _amounts(row)


def _match_source(event, source):
    key = 'game_rating_id' if event['kind'] == 'game' else 'manual_rating_id'
    if not isinstance(source, dict) or source.get('id') != event[key]:
        raise invalid_event()
    if any(
        event[key] != source.get(key)
        for key in ('user_id', 'rating_before', 'delta', 'rating_after')
    ):
        raise invalid_event()
    if event['kind'] == 'game' and event['rule_version'] != source.get('rule_version', 'legacy-v1'):
        raise invalid_event()
    if event['kind'] == 'manual':
        from .game_requests import validate_options

        _amounts(source)
        if 'last_game_rating_id' not in source:
            raise invalid_event()
        if (
            any(not _positive(source.get(key)) for key in ('actor_id', 'user_id', 'id'))
            or type(source.get('actor_level')) is not int
            or source['actor_level'] not in (4, 5)
            or not isinstance(source.get('reason'), str)
            or not 1 <= len(source['reason'].strip()) <= 500
            or len(source['reason']) > 500
            or source['delta'] == 0
            or source['recorded_at'] != event['recorded_at']
            or (
                source.get('last_game_rating_id') is not None
                and not _positive(source['last_game_rating_id'])
            )
        ):
            raise invalid_event()
        try:
            if (
                validate_options(source.get('request_id'))[0] != source.get('request_id')
                or source.get('request_id') is None
            ):
                raise invalid_event()
        except GameError:
            raise invalid_event() from None


def last_game(event):
    if event['kind'] == 'game':
        return event['game_rating_id']
    source = event.get('_manual_source')
    _match_source(event, source)
    return source['last_game_rating_id']


def _read_event(cursor, event_id):
    cursor.execute('SELECT * FROM rating_event WHERE id = %s FOR SHARE', (event_id,))
    event = cursor.fetchone()
    validate(event)
    if event['kind'] == 'manual':
        cursor.execute(
            'SELECT * FROM manual_rating WHERE id = %s FOR SHARE', (event['manual_rating_id'],)
        )
        event['_manual_source'] = cursor.fetchone()
        _match_source(event, event['_manual_source'])
    return event


def current(cursor, user):
    """PK current reads after user locks; never acquire game locks or gap locks."""
    from .game_settlements import invalid_settlement, validate_entry
    from .weighted_games import check_sources

    event_id = user.get('rating_event_id')
    if event_id is None:
        latest_id = user.get('rating_ledger_id')
        if latest_id is not None:
            cursor.execute('SELECT * FROM game_rating WHERE id = %s FOR SHARE', (latest_id,))
            latest = cursor.fetchone()
            if latest is None:
                raise invalid_settlement()
            check_sources(cursor, [latest], current=True)
            validate_entry(latest)
            if latest['user_id'] != user['id'] or latest['rating_after'] != user['rating']:
                raise invalid_settlement()
        return None
    if not _positive(event_id):
        raise invalid_event()
    event = _read_event(cursor, event_id)
    if event['id'] != event_id or event['user_id'] != user['id']:
        raise invalid_event()
    if event['rating_after'] != user['rating']:
        raise invalid_settlement()
    latest_id = last_game(event)
    if latest_id != user.get('rating_ledger_id'):
        raise invalid_event()
    if latest_id is not None:
        cursor.execute('SELECT * FROM game_rating WHERE id = %s FOR SHARE', (latest_id,))
        source = cursor.fetchone()
        if source is None:
            raise invalid_event()
        check_sources(cursor, [source], current=True)
        validate_entry(source)
        if source['user_id'] != user['id']:
            raise invalid_event()
        if event['kind'] == 'game':
            _match_source(event, source)
    if event['previous_id'] is not None:
        previous = _read_event(cursor, event['previous_id'])
        previous_game = last_game(previous)
        if (
            previous['user_id'] != user['id']
            or previous['sequence'] + 1 != event['sequence']
            or previous['rating_after'] != event['rating_before']
            or (event['kind'] == 'manual' and latest_id != previous_game)
            or (
                event['kind'] == 'game' and previous_game is not None and previous_game >= latest_id
            )
        ):
            raise invalid_event()
    else:
        anchor_id = event['legacy_rating_id']
        if event['kind'] == 'manual' and latest_id != anchor_id:
            raise invalid_event()
        if anchor_id is not None:
            cursor.execute('SELECT * FROM game_rating WHERE id = %s FOR SHARE', (anchor_id,))
            anchor = cursor.fetchone()
            if anchor is None:
                raise invalid_event()
            check_sources(cursor, [anchor], current=True)
            validate_entry(anchor)
            if (
                anchor['user_id'] != user['id']
                or anchor['rating_after'] != event['rating_before']
                or (event['kind'] == 'game' and anchor_id >= latest_id)
            ):
                raise invalid_event()
    return event


def _sequence(previous):
    sequence = previous['sequence'] + 1 if previous else 1
    if sequence > MAX_SEQUENCE:
        raise GameError('Rating event sequence exhausted', 409, 'rating_sequence_exhausted')
    return sequence


def append_game(
    cursor,
    user,
    source_id,
    before,
    delta,
    after,
    previous,
    recorded_at,
    *,
    rule_version='legacy-v1',
):
    if rule_version not in ('legacy-v1', 'weighted-rating-v1'):
        raise invalid_event()
    cursor.execute(
        'INSERT INTO rating_event (user_id, sequence, previous_id, legacy_rating_id, game_rating_id, kind, rule_version, rating_before, delta, rating_after, recorded_at) '
        "VALUES (%s, %s, %s, %s, %s, 'game', %s, %s, %s, %s, %s)",
        (
            user['id'],
            _sequence(previous),
            previous['id'] if previous else None,
            None if previous else user.get('rating_ledger_id'),
            source_id,
            rule_version,
            before,
            delta,
            after,
            recorded_at,
        ),
    )
    event_id = cursor.lastrowid
    cursor.execute(
        'UPDATE user SET rating = %s, rating_ledger_id = %s, rating_event_id = %s WHERE id = %s',
        (after, source_id, event_id, user['id']),
    )
    return event_id


def append_manual(cursor, user, source_id, after, previous, recorded_at):
    cursor.execute(
        'INSERT INTO rating_event (user_id, sequence, previous_id, legacy_rating_id, manual_rating_id, kind, rule_version, rating_before, delta, rating_after, recorded_at) '
        "VALUES (%s, %s, %s, %s, %s, 'manual', 'manual-v1', %s, %s, %s, %s)",
        (
            user['id'],
            _sequence(previous),
            previous['id'] if previous else None,
            None if previous else user.get('rating_ledger_id'),
            source_id,
            user['rating'],
            after - user['rating'],
            after,
            recorded_at,
        ),
    )
    event_id = cursor.lastrowid
    cursor.execute(
        'UPDATE user SET rating = %s, rating_event_id = %s WHERE id = %s',
        (after, event_id, user['id']),
    )
    return event_id


def validate_history(user, sources, events):
    """Every game suffix source occurs exactly once; manuals bridge balance gaps."""
    if not events:
        if user.get('rating_event_id') is not None:
            raise invalid_event()
        return
    for event in events:
        validate(event)
    anchor = events[0]['legacy_rating_id']
    start = 0
    if anchor is not None:
        indices = [index for index, row in enumerate(sources) if row['id'] == anchor]
        if len(indices) != 1:
            raise invalid_event()
        start = indices[0] + 1
    # The untouched legacy prefix still has its original contiguous source chain.
    for previous_source, source in zip(sources[:start], sources[1:start], strict=False):
        if source['rating_before'] != previous_source['rating_after']:
            raise invalid_event()
    index, previous, latest_game = start, None, anchor
    before = sources[start - 1]['rating_after'] if start else None
    for sequence, event in enumerate(events, 1):
        if (
            event['user_id'] != user['id']
            or event['sequence'] != sequence
            or event['previous_id'] != (previous['id'] if previous else None)
            or (before is not None and event['rating_before'] != before)
        ):
            raise invalid_event()
        if event['kind'] == 'game':
            if index >= len(sources):
                raise invalid_event()
            _match_source(event, sources[index])
            latest_game = sources[index]['id']
            index += 1
        elif last_game(event) != latest_game:
            raise invalid_event()
        previous, before = event, event['rating_after']
    if (
        index != len(sources)
        or previous['id'] != user.get('rating_event_id')
        or before != user['rating']
        or latest_game != user.get('rating_ledger_id')
    ):
        raise invalid_event()


def attach_manual(events, sources):
    by_id = {row['id']: row for row in sources}
    for event in events:
        if event.get('kind') == 'manual':
            event['_manual_source'] = by_id.get(event.get('manual_rating_id'))


def load_many(cursor, users):
    grouped = {user['id']: [] for user in users}
    if not grouped:
        return grouped
    cursor.execute(
        'SELECT * FROM rating_event WHERE user_id IN ('
        + ', '.join(['%s'] * len(grouped))
        + ') ORDER BY user_id, sequence',
        list(grouped),
    )
    events = cursor.fetchall()
    ids = [event['manual_rating_id'] for event in events if event['kind'] == 'manual']
    # Include sources even for NULL heads/no events: orphan manual facts must not
    # disappear from full-history validation (the hot settlement path stays O(1)).
    cursor.execute(
        'SELECT * FROM manual_rating WHERE user_id IN (' + ', '.join(['%s'] * len(grouped)) + ')',
        list(grouped),
    )
    sources = cursor.fetchall()
    if len(ids) != len(sources) or set(ids) != {source['id'] for source in sources}:
        raise invalid_event()
    attach_manual(events, sources)
    for event in events:
        grouped[event['user_id']].append(event)
    return grouped
