"""Read-only decoding of legacy game JSON; never repair historical records."""

import json

from .errors import GameError


def invalid_data():
    return GameError('Legacy game data requires review; run audit-legacy', 409, 'legacy_data_error')


def json_list(value):
    try:
        items = json.loads(value) if value else []
    except (TypeError, ValueError):
        raise invalid_data() from None
    if not isinstance(items, list):
        raise invalid_data()
    return items


def unique_ids(value):
    items = json_list(value)
    if any(type(item) is not int or item <= 0 for item in items) or len(set(items)) != len(items):
        raise invalid_data()
    return items
