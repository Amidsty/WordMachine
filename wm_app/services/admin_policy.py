"""Administrative policy and non-secret audit helpers."""

import json
import secrets
import string as character_sets
from datetime import datetime

from ..security.permissions import (
    ADMIN_LEVEL_EDIT_MIN_LEVEL,
    MAX_ADMIN_LEVEL,
    RATING_EDIT_MIN_LEVEL,
    admin_level,
)
from .errors import ApiError
from .validation import password

MAX_ADMIN_VERSION = 2147483647
MASTER_NAME = 'MASTER'


def master_password(value):
    value = password(value)
    groups = (
        character_sets.ascii_lowercase,
        character_sets.ascii_uppercase,
        character_sets.digits,
        character_sets.punctuation,
    )
    if len(value) < 16 or not all(any(char in group for char in value) for group in groups):
        raise ApiError(
            'Level 5 passwords require at least 16 characters, including uppercase, lowercase, digits and symbols'
        )
    return value


def generate_master_password():
    alphabet = character_sets.ascii_letters + character_sets.digits + '!@#$%&*+-_='
    while True:
        value = ''.join(secrets.choice(alphabet) for _ in range(24))
        try:
            return master_password(value)
        except ApiError:
            pass


def capabilities(actor, target):
    level, target_level = admin_level(actor), admin_level(target)
    self_target = actor['id'] == target['id']
    lower = level > 0 and not self_target and target_level < level
    known = target.get('deleted') in (0, 1)
    return {
        'can_edit_profile': known and level > 0 and (self_target or lower),
        'can_reset_password': level == MAX_ADMIN_LEVEL and lower and known,
        'can_ban': lower and target.get('deleted') == 0,
        'can_restore': lower and target.get('deleted') == 1,
        'can_set_level': level >= ADMIN_LEVEL_EDIT_MIN_LEVEL
        and lower
        and target.get('deleted') == 0,
        'max_assignable_level': max(0, level - 1),
        'meets_rating_threshold': level >= RATING_EDIT_MIN_LEVEL and (self_target or lower),
        'can_adjust_rating': level >= RATING_EDIT_MIN_LEVEL
        and (self_target or lower)
        and target.get('deleted') == 0,
    }


def audit(cursor, actor, target_id, action, before, after, *, reason='', source='http'):
    # Callers pass ONLY explicitly selected non-secret fields, never a whole user row.
    cursor.execute(
        'INSERT INTO admin_audit (actor_id, actor_level, target_id, action, before_data, after_data, reason, source, recorded_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)',
        (
            actor['id'] if actor else None,
            admin_level(actor) if actor else None,
            target_id,
            action,
            json.dumps(before, ensure_ascii=False),
            json.dumps(after, ensure_ascii=False),
            reason,
            source,
            datetime.utcnow(),
        ),
    )


def next_version(user):
    value = user.get('admin_version')
    if type(value) is not int or not 0 <= value < MAX_ADMIN_VERSION:
        raise ApiError('Administrative version requires review', 409, 'invalid_admin_version')
    return value + 1


def validate_level(value):
    if type(value) is not int or not 0 <= value <= MAX_ADMIN_LEVEL:
        raise ApiError('admin_level must be an integer between 0 and 5')
    return value
