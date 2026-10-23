"""Exact configuration and immutable per-game Perf policy; no database writes."""

import re
from decimal import Decimal

from .errors import ApiError, GameError
from .rating import CUMULATIVE_PERF_VERSION, MULTIPLIED_PERF_VERSION, RATING_VERSION

MIN_MULTIPLIER = Decimal('0.10')
MAX_MULTIPLIER = Decimal('5.00')
DEFAULT_MULTIPLIER = Decimal('1.00')
PERF_VERSION = 'dict-perf-v1'
MAX_VERSION = 2147483647


def stored(value):
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or not MIN_MULTIPLIER <= value <= MAX_MULTIPLIER
        or value != value.quantize(Decimal('0.01'))
    ):
        raise GameError('Stored multiplier requires review', 409, 'invalid_multiplier')
    return value


def parse(value):
    if not isinstance(value, str) or len(value) > 16:
        raise ApiError(
            'Multiplier must be a decimal string from 0.10 to 5.00', 400, 'invalid_multiplier'
        )
    value = value.strip()
    if not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?', value):
        raise ApiError('Multiplier requires at most two decimal places', 400, 'invalid_multiplier')
    number = Decimal(value)
    if not MIN_MULTIPLIER <= number <= MAX_MULTIPLIER:
        raise ApiError('Multiplier must be between 0.10 and 5.00', 400, 'invalid_multiplier')
    return number.quantize(Decimal('0.01'))


def game_multiplier(game):
    # Missing mode is supported only by pre-migration audit/test input. Runtime
    # projections include both columns. New-mode missing values never fall back.
    mode = game.get('perf_mode', 0)
    value = game.get('multiplier_snapshot')
    if type(mode) is not int or mode not in (0, 1):
        raise GameError('Game multiplier snapshot requires review', 409, 'invalid_multiplier')
    if mode == 0:
        if value is not None:
            raise GameError('Unexpected legacy multiplier snapshot', 409, 'invalid_multiplier')
        return None
    if game.get('question_mode') != 1 or game.get('answer_mode') != 1:
        raise GameError(
            'Game multiplier snapshot requires normalized questions and answers',
            409,
            'invalid_multiplier',
        )
    return stored(value)


def metadata(game):
    from . import weighted_games

    multiplier = game_multiplier(game)
    weighted = weighted_games.enabled(game)
    return {
        # Compatibility field: original multiplier-policy family, not a promise
        # that all answers share one formula. Each answer records its own version.
        'perf_rule_version': PERF_VERSION if multiplier is not None else RATING_VERSION,
        'next_answer_perf_rule_version': (
            weighted_games.rules(game).PERF_VERSION
            if weighted
            else (MULTIPLIED_PERF_VERSION if multiplier is not None else CUMULATIVE_PERF_VERSION)
        )
        if game.get('status') in (-1, 0)
        else None,
        'multiplier_snapshot': format(multiplier, '.2f') if multiplier is not None else None,
    }
