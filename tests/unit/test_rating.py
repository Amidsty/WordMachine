import pytest

from wm_app.services.rating import RATING_VERSION, rating_delta, score_answer
from wm_app.utils import check_answer


@pytest.mark.parametrize(
    'answer,expected,correct',
    [
        (' APPLE ', 'apple', True),
        ('colour', 'color/colour', True),
        ('banana', 'apple', False),
        ('APPLE', 'apple', True),
    ],
)
def test_answer_matching(answer, expected, correct):
    assert check_answer(answer, expected) is correct


def test_first_correct_answer_legacy_baseline():
    result = score_answer(
        rating=0,
        played_games=1,
        previous=None,
        last_global_combo=0,
        correct=True,
        randint=lambda low, high: low,
    )
    assert result['perf_delta'] == pytest.approx(1500 / 1300 * 11)
    assert result['perf'] == pytest.approx(1500 + result['perf_delta'])
    assert result['usercombo'] == result['globalcombo'] == 1
    assert result['rating_version'] == RATING_VERSION


def test_correct_answer_accumulates_perf():
    previous = {'perf': 1530, 'usercombo': 2}
    result = score_answer(
        rating=1500,
        played_games=6,
        previous=previous,
        last_global_combo=4,
        correct=True,
        randint=lambda low, high: high,
    )
    assert result['usercombo'] == 3
    assert result['globalcombo'] == 5
    assert result['perf_delta'] == 30
    assert result['perf'] == 1560


def test_wrong_answer_characterizes_legacy_reset_not_a_new_rule():
    result = score_answer(
        rating=1400,
        played_games=6,
        previous={'perf': 1800, 'usercombo': 5},
        last_global_combo=20,
        correct=False,
        randint=lambda low, high: high,
    )
    assert result['usercombo'] == result['globalcombo'] == 0
    assert result['perf_delta'] == pytest.approx(-1400 / 1500 * 5)
    assert result['perf'] == pytest.approx(1400 + result['perf_delta'])


@pytest.mark.parametrize('rating,perf,expected', [(1500, 1510, 9), (1500, 1490, -9), (0, 0, 0)])
def test_rating_delta_golden_cases(rating, perf, expected):
    assert rating_delta(rating, perf) == expected
    assert type(rating_delta(rating, perf)) is int


@pytest.mark.parametrize('rating', [0, 999, 1300, 1500, 1700, 2500, 3000])
@pytest.mark.parametrize('difference', [-100, 0, 100])
def test_rating_formula_matches_legacy_math(rating, difference):
    perf = rating + difference
    factor = (
        1500 / min(max(rating, 1300), 1700)
        if difference > 0
        else 1 / (1500 / max(min(rating, 2500), 1000))
    )
    sign = (difference > 0) - (difference < 0)
    assert rating_delta(rating, perf) == round(factor * sign * abs(difference) ** 0.95)


@pytest.mark.parametrize('perf', [float('nan'), float('inf'), -float('inf')])
def test_invalid_perf_rejected(perf):
    with pytest.raises(ValueError):
        rating_delta(1500, perf)
