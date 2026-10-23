"""Bounded per-answer Perf v2; v1 remains immutable for historical validation.

Difficulty is a frozen, mild directional factor. Dictionary multiplier scales
all evidence/Perf increments linearly for the same saved answer sequence. No
inverse odds, dynamic-Perf penalty, SQL, random draws or implicit adoption.
"""

import math
from dataclasses import dataclass
from typing import Sequence

from . import weighted_rating as v1
from .weighted_rating import (
    BONUS_VERSION as BONUS_VERSION,
)
from .weighted_rating import (
    BONUSES as BONUSES,
)
from .weighted_rating import (
    MAX_RATING as MAX_RATING,
)
from .weighted_rating import (
    MIN_RATING as MIN_RATING,
)
from .weighted_rating import (
    AnswerInput as AnswerInput,
)
from .weighted_rating import (
    AnswerScore as AnswerScore,
)
from .weighted_rating import (
    Evidence as Evidence,
)
from .weighted_rating import (
    SettlementProposal as SettlementProposal,
)
from .weighted_rating import (
    boolean as boolean,
)
from .weighted_rating import (
    finite as finite,
)
from .weighted_rating import (
    integer as integer,
)
from .weighted_rating import (
    weight as weight,
)

PERF_VERSION = 'weighted-perf-v2'
RATING_VERSION = 'weighted-rating-v2'


@dataclass(frozen=True)
class Snapshot(v1.Snapshot):
    perf_version: str = PERF_VERSION
    rating_version: str = RATING_VERSION

    def __post_init__(self):
        # Share state/multiplier validation, not v1's numerical formulas.
        v1.Snapshot(
            self.public_rating,
            self.remaining_bonus,
            self.completed_games,
            self.newcomer_enabled,
            self.difficulty,
            self.multiplier,
        )
        if self.perf_version != PERF_VERSION or self.rating_version != RATING_VERSION:
            raise ValueError('Unsupported bounded-rating version')

    @property
    def difficulty_factors(self):
        adjustment = 0.25 * math.tanh((self.difficulty - self.internal_rating) / 800)
        return 1 + adjustment, 1 - adjustment

    @property
    def global_protection(self):
        # Newcomers still feel a broken room streak; never erase this feedback.
        return 0.5 + 0.5 * self.streak_protection

    @property
    def speed_factors(self):
        t = math.exp(-max(0.0, (self.internal_rating - 1500) / 1000))
        return 0.75 + 0.25 * t, 1.25 - 0.25 * t


def _question(snapshot, answer, self_before):
    if answer.correct:
        factor = (
            1 + 0.30 * (-math.expm1(-max(0, self_before - 1) / 10)) * snapshot.streak_protection
        )
    else:
        factor = 1 + 2 * (-math.expm1(-answer.global_before / 8)) * snapshot.global_protection
    points = answer.draw * float(snapshot.multiplier) * factor
    return points if answer.correct else -points, factor


def performance(snapshot: Snapshot, correct_weight, wrong_weight):
    c, w = weight(correct_weight), weight(wrong_weight)
    up, down = snapshot.difficulty_factors
    return finite(snapshot.internal_rating + 10 * math.fsum((c * up, -w * down)))


def evidence(snapshot: Snapshot, answers: Sequence[AnswerInput]):
    correct, wrong, streak = [], [], 0
    for answer in answers:
        if type(answer) is not AnswerInput:
            raise ValueError('Expected saved weighted-rating answer input')
        points, _ = _question(snapshot, answer, streak)
        (correct if answer.correct else wrong).append(abs(points) / 10)
        streak = streak + 1 if answer.correct else 0
    c, w = weight(math.fsum(correct)), weight(math.fsum(wrong))
    return Evidence(len(answers), streak, c, w, performance(snapshot, c, w) if answers else None)


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


def competitive_change(snapshot: Snapshot, perf_final, correct_weight, wrong_weight):
    # The two caps, protection, nonpositive-net-weight gain gate and rounding remain.
    # Dispatches the frozen v2 speed_factors property, not the old asymmetric curve.
    return v1.competitive_change(snapshot, perf_final, correct_weight, wrong_weight)


def settlement_proposal(snapshot: Snapshot, answers: Sequence[AnswerInput], *, rated, finished):
    boolean(rated)
    boolean(finished)
    result = evidence(snapshot, answers)
    if not (rated and finished and result.answered_count > 0):
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
