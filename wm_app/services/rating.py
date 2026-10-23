"""Cumulative Perf for new answers; legacy-v1 Rating settlement stays unchanged.

Historical answers retain their recorded versions and values. The v2 Perf rule
uses the previous personal Perf on both correct and wrong answers, including
when an in-progress legacy game receives its first answer after deployment.
"""

import math
import random

RATING_VERSION = 'legacy-v1'
CUMULATIVE_PERF_VERSION = 'perf-v2'
MULTIPLIED_PERF_VERSION = 'dict-perf-v2'
MIN_RATING, MAX_RATING = -2147483648, 2147483647


def score_answer(
    *, rating, played_games, previous, last_global_combo, correct, randint=None, multiplier=None
):
    randint = randint or random.randint
    global_combo = last_global_combo + 1 if correct else 0
    user_combo = (previous.get('usercombo', 0) if previous else 0) + 1 if correct else 0
    factor = 1500 / min(max(1300, rating), 1700)
    if correct:
        combo_factor = math.ceil(user_combo**0.7)
        delta = factor * randint(10 + combo_factor, 15 + 5 * combo_factor)
    else:
        combo_factor = math.ceil((global_combo + 1) ** 0.7)
        delta = -(1 / factor) * randint(combo_factor, 5 * combo_factor)
    raw_delta = delta
    if multiplier is not None:
        from .dictionary_multipliers import stored

        stored(multiplier)
        # Multiplication by 1.00 must not introduce a different floating-point path.
        if multiplier != 1:
            delta *= float(multiplier)
    if previous is not None:
        base = previous['perf']
        if type(base) not in (int, float) or not math.isfinite(base):
            raise ValueError('Previous Perf must be finite')
    else:
        base = max(rating, 1500) if played_games <= 5 else rating
    result = {
        'usercombo': user_combo,
        'globalcombo': global_combo,
        'perf_delta': delta,
        'perf': base + delta,
        'rating_version': CUMULATIVE_PERF_VERSION,
    }
    if multiplier is not None:
        result.update(raw_perf_delta=raw_delta, rating_version=MULTIPLIED_PERF_VERSION)
    return result


def rating_delta(rating, perf):
    if not math.isfinite(perf):
        raise ValueError('Perf must be finite')
    difference = perf - rating
    if difference == 0:
        return 0
    factor = (
        1500.0 / min(max(rating, 1300), 1700)
        if difference > 0
        else 1.0 / (1500.0 / max(min(rating, 2500), 1000))
    )
    sign = 1 if difference > 0 else -1
    return round(factor * sign * abs(difference) ** 0.95)
