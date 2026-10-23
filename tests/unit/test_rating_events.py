from datetime import datetime

import pytest

from wm_app.services import rating_events
from wm_app.services.errors import GameError


def event(**changes):
    return {
        'id': 21,
        'user_id': 1,
        'sequence': 1,
        'previous_id': None,
        'legacy_rating_id': None,
        'game_rating_id': 11,
        'kind': 'game',
        'rule_version': 'legacy-v1',
        'rating_before': 100,
        'delta': 3,
        'rating_after': 103,
        'recorded_at': datetime(2026, 1, 1),
        **changes,
    }


def source(**changes):
    return {
        'id': 11,
        'user_id': 1,
        'rating_before': 100,
        'delta': 3,
        'rating_after': 103,
        **changes,
    }


@pytest.mark.parametrize(
    'changes',
    [
        {'id': True},
        {'sequence': 0},
        {'sequence': 2147483648},
        {'kind': 'adjustment'},
        {'rule_version': 'guess'},
        {'previous_id': 1},
        {'legacy_rating_id': -1},
        {'rating_before': True},
        {'rating_after': 2147483648},
        {'delta': 2},
        {'recorded_at': None},
        {'sequence': 2, 'previous_id': 21},
        {'sequence': 2, 'previous_id': 20, 'legacy_rating_id': 10},
    ],
)
def test_invalid_events_are_not_coerced_or_repaired(changes):
    with pytest.raises(GameError):
        rating_events.validate(event(**changes))


def test_history_links_untouched_prefix_and_checks_full_coverage():
    old = source(id=10, rating_before=99, delta=1, rating_after=100)
    row = event(legacy_rating_id=10)
    user = {'id': 1, 'rating': 103, 'rating_ledger_id': 11, 'rating_event_id': 21}
    rating_events.validate_history(user, [old, source()], [row])
    for bad_user, sources, events in [
        ({**user, 'rating_event_id': None}, [old, source()], [row]),
        (user, [old, source()], []),
        (user, [source()], [row]),
        (user, [old, source(), source(id=12)], [row]),
        (user, [old, source(user_id=2)], [row]),
        ({**user, 'rating': 104}, [old, source()], [row]),
    ]:
        with pytest.raises(GameError):
            rating_events.validate_history(bad_user, sources, events)


@pytest.mark.parametrize(
    'changes',
    [
        {},
        {'id': 8},
        {'user_id': 2},
        {'actor_id': True},
        {'actor_level': 3},
        {'request_id': 'invalid'},
        {'reason': ''},
        {'delta': -11},
        {'recorded_at': datetime(2025, 1, 1)},
        {'last_game_rating_id': None},
    ],
)
def test_manual_sources_bridge_game_balances_and_fail_closed(changes):
    manual = event(
        id=22,
        sequence=2,
        previous_id=21,
        game_rating_id=None,
        manual_rating_id=7,
        kind='manual',
        rule_version='manual-v1',
        rating_before=103,
        delta=-10,
        rating_after=93,
    )
    manual['_manual_source'] = {
        'id': 7,
        'user_id': 1,
        'actor_id': 3,
        'actor_level': 4,
        'request_id': '12345678-1234-4234-8234-123456789abc',
        'reason': 'reviewed',
        'last_game_rating_id': 11,
        'rating_before': 103,
        'delta': -10,
        'rating_after': 93,
        'recorded_at': datetime(2026, 1, 1),
        **changes,
    }
    user = {'id': 1, 'rating': 93, 'rating_ledger_id': 11, 'rating_event_id': 22}
    if changes:
        with pytest.raises(GameError):
            rating_events.validate_history(user, [source()], [event(), manual])
    else:
        rating_events.validate_history(user, [source()], [event(), manual])


def test_event_chain_order_is_per_account_sequence_not_wall_clock():
    one = event()
    two = event(
        id=25,
        sequence=2,
        previous_id=21,
        game_rating_id=14,
        rating_before=103,
        delta=-5,
        rating_after=98,
        recorded_at=datetime(2025, 1, 1),
    )
    user = {'id': 1, 'rating': 98, 'rating_ledger_id': 14, 'rating_event_id': 25}
    rows = [source(), source(id=14, rating_before=103, delta=-5, rating_after=98)]
    rating_events.validate_history(user, rows, [one, two])
    for events in ([two, one], [one, {**two, 'sequence': 3}], [one, {**two, 'previous_id': 20}]):
        with pytest.raises(GameError):
            rating_events.validate_history(user, rows, events)
