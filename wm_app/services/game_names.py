"""Display metadata, never a room identifier or dictionary/snapshot title."""

import unicodedata

from .errors import GameError


def parse(value):
    if not isinstance(value, str):
        raise GameError('Game name must be text', 400, 'invalid_game_name')
    value = value.strip()
    if not 1 <= len(value) <= 100 or any(
        unicodedata.category(char) in ('Cc', 'Cs', 'Zl', 'Zp') for char in value
    ):
        raise GameError('Game name must be 1–100 characters on one line', 400, 'invalid_game_name')
    return value


def stored(row):
    value = row.get('name')
    if value is None:
        return None  # No invented historical title; the UI shows the unchanged room number.
    try:
        if parse(value) == value:
            return value
    except GameError:
        pass
    raise GameError('Stored game name requires review', 409, 'invalid_game_name')
