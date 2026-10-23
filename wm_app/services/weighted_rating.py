"""Pure, versioned RATING.md engine. NOT wired to game commands yet.

No DB writes, random draws, clock, authorization or implicit account adoption.
The future transactional adapter must supply locked snapshots and saved draws,
validate full room order/global streaks, and persist proposals exactly once.
Never use this engine to reinterpret legacy answers or successful receipts.
"""

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

PERF_VERSION = 'weighted-perf-v1'
RATING_VERSION = 'weighted-rating-v1'
BONUS_VERSION = 'newcomer-bonus-v1'
BONUSES = (600, 350, 250, 150, 100, 50)
MIN_RATING, MAX_RATING = -2147483648, 2147483647


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Invalid weighted-rating integer')
    return value


def finite(value):
    if type(value) not in (int, float):
        raise ValueError('Weighted-rating number must be finite')
    try:
        result = float(value)
    except OverflowError:
        raise ValueError('Weighted-rating number must be finite') from None
    if not math.isfinite(result):
        raise ValueError('Weighted-rating number must be finite')
    return result


def weight(value):
    result = finite(value)
    if result < 0:
        raise ValueError('Weighted-rating evidence must be nonnegative')
    return result


def boolean(value):
    if type(value) is not bool:
        raise ValueError('Weighted-rating flag must be boolean')
    return value


def clamp(value, low, high):
    return min(high, max(low, value))


def round_rating(value):
    return int(Decimal(str(finite(value))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Snapshot:
    public_rating: int
    remaining_bonus: int
    completed_games: int
    newcomer_enabled: bool
    difficulty: int = 1500
    multiplier: Decimal = Decimal('1.00')
    perf_version: str = PERF_VERSION
    rating_version: str = RATING_VERSION

    def __post_init__(self):
        integer(self.public_rating, MIN_RATING, MAX_RATING)
        integer(self.remaining_bonus, 0, 1500)
        integer(self.completed_games, 0, MAX_RATING)
        boolean(self.newcomer_enabled)
        integer(self.difficulty, 0, 4000)
        m = self.multiplier
        if (
            type(m) is not Decimal
            or not m.is_finite()
            or not Decimal('0.10') <= m <= Decimal('5.00')
            or m != m.quantize(Decimal('0.01'))
        ):
            raise ValueError('Invalid weighted-rating multiplier')
        expected = sum(BONUSES[self.completed_games :]) if self.newcomer_enabled else 0
        if self.remaining_bonus != expected:
            raise ValueError('Newcomer balance and completed count disagree')
        if self.perf_version != PERF_VERSION or self.rating_version != RATING_VERSION:
            raise ValueError('Unsupported weighted-rating version')

    @property
    def internal_rating(self):
        return self.public_rating + self.remaining_bonus

    @property
    def ordinal(self):
        return self.completed_games + 1

    @property
    def streak_protection(self):
        return clamp((self.ordinal - 5) / 5, 0.0, 1.0) if self.newcomer_enabled else 1.0

    @property
    def rating_protection(self):
        return 0.2 + 0.8 * self.streak_protection

    @property
    def speed_factors(self):
        t = math.exp(-max(0.0, (self.internal_rating - 1500) / 1000))
        return 0.25 + 0.75 * t, 2.0 - t

    @property
    def bonus(self):
        if self.newcomer_enabled and self.completed_games < len(BONUSES):
            return BONUSES[self.completed_games]
        return 0


def _softplus(x):
    return max(x, 0) + math.log1p(math.exp(-abs(x)))


def _logadd(a, b):
    hi, lo = max(a, b), min(a, b)
    return hi + math.log1p(math.exp(lo - hi))


def performance(snapshot: Snapshot, correct_weight, wrong_weight):
    c, w = weight(correct_weight), weight(wrong_weight)
    u = snapshot.internal_rating
    if c == w == 0:
        return float(u)
    z = math.log(10) * (u - snapshot.difficulty) / 400
    a = _logadd(math.log(10) - _softplus(-z), math.log(c) if c else -math.inf)
    b = _logadd(math.log(10) - _softplus(z), math.log(w) if w else -math.inf)
    return finite(snapshot.difficulty + 400 / math.log(10) * (a - b))


@dataclass(frozen=True)
class AnswerInput:
    correct: bool
    draw: int
    global_before: int

    def __post_init__(self):
        boolean(self.correct)
        integer(self.draw, 5, 15)
        integer(self.global_before, 0, MAX_RATING - 1)


@dataclass(frozen=True)
class Evidence:
    answered_count: int
    self_streak: int
    correct_weight: float
    wrong_weight: float
    perf: float | None


def _question(snapshot, answer, self_before):
    reward = 1 + 0.30 * (-math.expm1(-max(0, self_before - 1) / 10))
    penalty = 1 + 0.40 * (-math.expm1(-max(0, answer.global_before - 1) / 8))
    raw = reward if answer.correct else penalty
    factor = 1 + (raw - 1) * snapshot.streak_protection
    points = answer.draw * float(snapshot.multiplier) * factor
    return points if answer.correct else -points, factor


def evidence(snapshot: Snapshot, answers: Sequence[AnswerInput]):
    """Reconstruct from saved draws, not rounded display values or cached totals.

    Room-order validation belongs to the adapter: this is one user's subsequence.
    Other users' answers must never reset this user's personal streak.
    """
    correct, wrong, streak = [], [], 0
    for answer in answers:
        if type(answer) is not AnswerInput:
            raise ValueError('Expected saved weighted-rating answer input')
        points, _ = _question(snapshot, answer, streak)
        (correct if answer.correct else wrong).append(abs(points) / 10)
        streak = streak + 1 if answer.correct else 0
    c, w = weight(math.fsum(correct)), weight(math.fsum(wrong))
    return Evidence(len(answers), streak, c, w, performance(snapshot, c, w) if answers else None)


@dataclass(frozen=True)
class AnswerScore:
    answer: AnswerInput
    self_before: int
    self_after: int
    global_after: int
    effective_multiplier: float
    raw_point_delta: float
    weight_delta: float
    before: Evidence
    after: Evidence
    perf_delta: float


def score_answer(snapshot: Snapshot, previous: Sequence[AnswerInput], answer: AnswerInput):
    if type(answer) is not AnswerInput:
        raise ValueError('Expected saved weighted-rating answer input')
    before = evidence(snapshot, previous)
    after = evidence(snapshot, (*previous, answer))
    points, factor = _question(snapshot, answer, before.self_streak)
    previous_perf = before.perf if before.perf is not None else snapshot.internal_rating
    return AnswerScore(
        answer,
        before.self_streak,
        after.self_streak,
        answer.global_before + 1 if answer.correct else 0,
        factor,
        points,
        abs(points) / 10,
        before,
        after,
        after.perf - previous_perf,
    )


@dataclass(frozen=True)
class CompetitiveChange:
    base: float
    speed: float
    full: float
    protected: float
    no_gain_gate: bool
    before_rounding: float
    delta: int


def competitive_change(snapshot: Snapshot, perf_final, correct_weight, wrong_weight):
    c, w = weight(correct_weight), weight(wrong_weight)
    gap = finite(perf_final) - snapshot.internal_rating
    base = clamp(0.5 * gap, -200.0, 200.0)
    up, down = snapshot.speed_factors
    speed = base * (up if base > 0 else down if base < 0 else 1)
    full = clamp(speed, -200.0, 200.0)
    protected = full * snapshot.rating_protection
    gate = c <= w + 1e-12 * max(1, c, w)
    final = min(0, protected) if gate else protected
    return CompetitiveChange(base, speed, full, protected, gate, final, round_rating(final))


@dataclass(frozen=True)
class SettlementProposal:
    eligible: bool
    evidence: Evidence
    competitive: CompetitiveChange | None
    bonus: int
    public_after: int
    remaining_after: int
    internal_after: int
    completed_after: int


def settlement_proposal(snapshot: Snapshot, answers: Sequence[AnswerInput], *, rated, finished):
    """Arithmetic only: NOT a receipt, permission check or idempotency mechanism."""
    boolean(rated)
    boolean(finished)
    result = evidence(snapshot, answers)
    eligible = rated and finished and result.answered_count > 0
    if not eligible:
        return SettlementProposal(
            False,
            result,
            None,
            0,
            snapshot.public_rating,
            snapshot.remaining_bonus,
            snapshot.internal_rating,
            snapshot.completed_games,
        )
    change = competitive_change(snapshot, result.perf, result.correct_weight, result.wrong_weight)
    bonus = snapshot.bonus
    public = snapshot.public_rating + change.delta + bonus
    integer(public, MIN_RATING, MAX_RATING)
    integer(snapshot.completed_games + 1, 0, MAX_RATING)
    return SettlementProposal(
        True,
        result,
        change,
        bonus,
        public,
        snapshot.remaining_bonus - bonus,
        snapshot.internal_rating + change.delta,
        snapshot.completed_games + 1,
    )
