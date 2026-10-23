"""Creation-time policy. Missing keys only occur in pre-0013 audit rows/test fixtures."""

from .errors import GameError

UNRATED_VERSION = 'unrated-v1'


def choice(value):
    if type(value) is not bool:
        raise GameError('rated must be a boolean', 400, 'invalid_parameters')
    return value


def rated(game):
    value = game.get('rated', 1)
    if type(value) is not int or value not in (0, 1):
        raise GameError(
            'Game Rating policy requires review; run audit-legacy',
            409,
            'invalid_game_rating_policy',
        )
    return value == 1
