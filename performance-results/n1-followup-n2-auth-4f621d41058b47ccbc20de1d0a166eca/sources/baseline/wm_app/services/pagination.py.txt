"""Bounded, deterministic list queries shared by HTTP adapters and services."""

import re
from dataclasses import dataclass

from .errors import ApiError
from .validation import string


def query_value(data, key, default):
    if hasattr(data, 'getlist') and len(data.getlist(key)) > 1:
        raise ApiError(f'Duplicate query parameter: {key}')
    return data.get(key, default)


def boolean_query(data, key, default=False):
    value = query_value(data, key, str(default).lower())
    if not isinstance(value, str) or value.lower() not in ('true', 'false'):
        raise ApiError(f'{key} must be true or false')
    return value.lower() == 'true'


@dataclass(frozen=True)
class ListQuery:
    page: int = 1
    per_page: int = 20
    q: str = ''

    def __post_init__(self):
        for name, value, maximum in (
            ('page', self.page, 1000000),
            ('per_page', self.per_page, 100),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ApiError(f'{name} must be between 1 and {maximum}')
        object.__setattr__(self, 'q', string(self.q, 'Search query', maximum=100))

    @classmethod
    def parse(cls, data):
        values = {}
        for key, default in (('page', '1'), ('per_page', '20')):
            value = query_value(data, key, default)
            if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,6}', value):
                raise ApiError(f'Invalid {key}')
            values[key] = int(value)
        return cls(**values, q=query_value(data, 'q', ''))

    @property
    def like(self):
        # Literal contains search, independent of MySQL backslash SQL mode.
        return '%' + self.q.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'

    def metadata(self, total):
        pages = max(1, (total + self.per_page - 1) // self.per_page)
        return {
            'page': min(self.page, pages),
            'per_page': self.per_page,
            'total': total,
            'pages': pages,
        }


def page_offset(metadata):
    return (metadata['page'] - 1) * metadata['per_page']
