from decimal import Decimal

import pytest

from wm_app.services import dictionary_multipliers as policy
from wm_app.services.errors import ApiError, GameError
from wm_app.services.rating import score_answer


@pytest.mark.parametrize(
    'value',
    [None, True, 1, 1.25, '', 'NaN', 'Infinity', '1e0', '1.001', '0', '-1', '0.09', '5.01', '01.2'],
)
def test_invalid_configuration_is_rejected_without_coercion(value):
    with pytest.raises(ApiError):
        policy.parse(value)


@pytest.mark.parametrize(
    'value,expected', [('1', '1.00'), ('1.2', '1.20'), ('0.10', '0.10'), ('5.00', '5.00')]
)
def test_configuration_is_exact_decimal(value, expected):
    assert policy.parse(value) == Decimal(expected)
    assert format(policy.parse(value), '.2f') == expected


@pytest.mark.parametrize('correct', [False, True])
@pytest.mark.parametrize('played', [1, 6])
@pytest.mark.parametrize('previous', [None, {'perf': 1700.123456789, 'usercombo': 4}])
def test_multiplier_one_preserves_every_old_numeric_bit(correct, played, previous):
    options = dict(
        rating=1333,
        played_games=played,
        previous=previous,
        last_global_combo=5,
        correct=correct,
        randint=lambda low, high: high,
    )
    old = score_answer(**options)
    new = score_answer(**options, multiplier=Decimal('1.00'))
    assert new['rating_version'] == 'dict-perf-v1'
    assert new['raw_perf_delta'].hex() == old['perf_delta'].hex()
    for field in ('perf', 'perf_delta'):
        assert new[field].hex() == old[field].hex()
    assert new['usercombo'] == old['usercombo'] and new['globalcombo'] == old['globalcombo']


@pytest.mark.parametrize('correct', [False, True])
@pytest.mark.parametrize('factor', ['0.10', '1.25', '5.00'])
def test_only_delta_is_scaled_not_baseline_or_prior_perf(correct, factor):
    options = dict(
        rating=1200,
        played_games=1,
        previous={'perf': 1800.0, 'usercombo': 2},
        last_global_combo=3,
        correct=correct,
        randint=lambda low, high: low,
    )
    old = score_answer(**options)
    new = score_answer(**options, multiplier=Decimal(factor))
    expected_delta = old['perf_delta'] * float(factor)
    assert new['perf_delta'] == expected_delta
    assert new['raw_perf_delta'] == old['perf_delta']
    assert new['perf'] == (1800 if correct else 1500) + expected_delta


def test_legacy_has_no_fabricated_snapshot_and_new_missing_snapshot_fails_closed():
    assert policy.metadata({'perf_mode': 0, 'multiplier_snapshot': None}) == {
        'perf_rule_version': 'legacy-v1',
        'multiplier_snapshot': None,
    }
    for value in (None, 1.0, Decimal('NaN'), Decimal('5.01')):
        with pytest.raises(GameError):
            policy.game_multiplier(
                {'perf_mode': 1, 'question_mode': 1, 'answer_mode': 1, 'multiplier_snapshot': value}
            )
