import json
from copy import deepcopy
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from wm_app.audit import inspect_legacy
from wm_app.services import game_settlements as settlements
from wm_app.services.errors import GameError


def header(**changes):
    return {
        'game_id': 7,
        'rated_count': 1,
        'rating_version': 'legacy-v1',
        'settled_at': datetime(2026, 1, 1),
        'recorded_at': datetime(2026, 1, 1),
        **changes,
    }


def entry(**changes):
    return {
        'id': 11,
        'game_id': 7,
        'user_id': 1,
        'perf': 1600.25,
        'rating_before': 1500,
        'delta': 80,
        'rating_after': 1580,
        **changes,
    }


def game(**changes):
    return {
        'id': 7,
        'status': 1,
        'settlement_mode': 1,
        'users': [1, 2],
        'result': [{'uid': 1, 'perf': 1600.25}],
        **changes,
    }


def test_valid_rows_and_empty_settlement_without_recalculating_historical_scores():
    # Validation is not a recomputation of recorded delta (80 is intentionally arbitrary).
    settlements.validate_rows(game(), header(), [entry()])
    settlements.validate_rows(game(result=[]), header(rated_count=0), [])
    settlements.validate_rows(game(status=0), None, [])
    settlements.validate_rows(game(settlement_mode=0), None, [])


@pytest.mark.parametrize('mode', [None, True, -1, 2, '1'])
def test_invalid_modes(mode):
    with pytest.raises(GameError, match='settlement requires review'):
        settlements.relational(game(settlement_mode=mode))


@pytest.mark.parametrize(
    'changes',
    [
        {'game_id': 8},
        {'rated_count': 0},
        {'rated_count': True},
        {'rating_version': 'unknown'},
        {'settled_at': '2026'},
        {'recorded_at': None},
    ],
)
def test_invalid_header(changes):
    with pytest.raises(GameError):
        settlements.validate_rows(game(), header(**changes), [entry()])


@pytest.mark.parametrize(
    'changes',
    [
        {'id': -1},
        {'id': True},
        {'game_id': 8},
        {'user_id': 2},
        {'user_id': True},
        {'perf': float('nan')},
        {'perf': float('inf')},
        {'perf': 1600.26},
        {'perf': None},
        {'rating_before': True},
        {'rating_after': 2147483648},
        {'rating_before': -2147483649},
        {'delta': 80.0},
        {'delta': -1},
    ],
)
def test_invalid_ledger_entry(changes):
    with pytest.raises(GameError):
        settlements.validate_rows(game(), header(), [entry(**changes)])


@pytest.mark.parametrize(
    'current,metadata,rows',
    [
        (game(), None, []),
        (game(), header(), []),
        (game(), header(rated_count=2), [entry(), entry(id=12)]),
        (game(status=0), header(), [entry()]),
        (game(status=2), header(rated_count=0), []),
        (game(settlement_mode=0), header(), [entry()]),
        (game(result=[None]), header(), [entry()]),
    ],
)
def test_incomplete_and_unexpected_settlements(current, metadata, rows):
    with pytest.raises(GameError):
        settlements.validate_rows(current, metadata, rows)


@pytest.mark.parametrize(
    'raw',
    ['[null]', '[{"game_id":"7"}]', '[{"game_id":true}]', '[{"game_id":7},{"game_id":7}]', '[{}]'],
)
def test_invalid_legacy_history_is_not_silently_merged_or_repaired(raw):
    with pytest.raises(GameError) as error:
        settlements.legacy_history(raw)
    assert error.value.code == 'legacy_data_error'


def test_history_keeps_legacy_prefix_and_uses_ledger_order_not_game_id_or_time():
    old = [{'game_id': 90, 'delta': -3, 'new_rating': 1500, 'legacy_extra': 'preserved'}]
    user = {'id': 1, 'rating': 1584, 'ratinghistory': json.dumps(old), 'rating_ledger_id': 15}
    first = {**header(), **entry(), 'settlement_mode': 1, 'status': 1}
    second = {
        **first,
        'id': 15,
        'game_id': 2,
        'rating_before': 1580,
        'delta': 4,
        'rating_after': 1584,
        'settled_at': datetime(2025, 1, 1),
    }
    before = deepcopy([user, first, second])
    result = settlements.merge_history(user, [first, second])
    assert result == [
        *old,
        {'game_id': 7, 'delta': 80, 'new_rating': 1580},
        {'game_id': 2, 'delta': 4, 'new_rating': 1584},
    ]
    assert [user, first, second] == before


@pytest.mark.parametrize('change', ['balance', 'chain', 'duplicate', 'order', 'legacy_duplicate'])
def test_history_refuses_inconsistent_balances_or_duplicate_sources(change):
    user = {'id': 1, 'rating': 1584, 'ratinghistory': None, 'rating_ledger_id': 12}
    first = {**header(), **entry(), 'settlement_mode': 1, 'status': 1}
    second = {
        **first,
        'id': 12,
        'game_id': 8,
        'rating_before': 1580,
        'delta': 4,
        'rating_after': 1584,
    }
    if change == 'balance':
        user['rating'] = 1500
    elif change == 'chain':
        second.update(rating_before=1579, delta=5)
    elif change == 'duplicate':
        second['game_id'] = 7
    elif change == 'order':
        second['id'] = 9
    else:
        user['ratinghistory'] = '[{"game_id":7}]'
    with pytest.raises(GameError):
        settlements.merge_history(user, [first, second])


def test_audit_reports_orphans_duplicate_sources_and_balance_mismatch_without_private_data():
    users = [
        {
            'id': 1,
            'username': 'private name',
            'rating': 1590,
            'gamehistory': '[7]',
            'ratinghistory': '[{"game_id":7}]',
        },
        {'id': 2, 'username': 'other', 'rating': 1500, 'gamehistory': None, 'ratinghistory': None},
    ]
    games = [
        {
            **game(),
            'ownerid': 1,
            'dictid': 1,
            'users': '[1,2]',
            'wordlist': '[11]',
            'result': '[{"uid":1,"word_id":11,"perf":1600.25,"answer":"private submission"}]',
        }
    ]
    words = [{'id': 11, 'dictid': 1, 'english': 'private answer', 'chinese': '私有题面'}]
    headers = [header(), header(game_id=777, rated_count=0)]
    rows = [entry(), entry(id=12, game_id=999, user_id=999)]
    before = deepcopy([users, games, words, headers, rows])
    report = inspect_legacy(users, [{'id': 1}], words, games, settlement_rows=headers, ratings=rows)
    assert {
        'duplicate_settlement',
        'invalid_rating_history',
        'missing_game_reference',
        'missing_user_reference',
        'invalid_settlement_reference',
    } <= {item['kind'] for item in report['issues']}
    assert [users, games, words, headers, rows] == before
    assert 'private' not in json.dumps(report) and '私有' not in json.dumps(
        report, ensure_ascii=False
    )


def test_latest_balance_check_is_current_read_without_locking_another_game():
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, entry(game_id=6)]
    users = {1: {'id': 1, 'rating': 1580, 'ratinghistory': None, 'rating_ledger_id': 11}}
    settlements.settle(cursor, game(status=0), users)
    sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert 'FOR SHARE' in sql[1] and 'JOIN' not in sql[1] and 'WHERE id = %s' in sql[1]
    assert all(
        'ratinghistory =' not in statement and 'perf =' not in statement for statement in sql
    )
    assert (
        sql.index(
            next(statement for statement in sql if statement.startswith('INSERT INTO game_rating'))
        )
        > 1
    )
