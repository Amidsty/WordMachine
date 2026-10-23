"""Reviewed 1-indexed dictionary ranges, not word IDs or filtered page offsets.

All normal word writers share actor -> dictionary locks. The confirmation binds
an actor, dictionary metadata and the complete active word sequence/content.
A second submit cannot delete a shifted next range. No DDL or history rewrites.
"""

import hashlib
import json
import re

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pymysql.cursors import SSDictCursor

from ..db import reading, transaction
from ..security.permissions import require_dictionary_owner
from .dictionary import _dictionary, _writable_dictionary
from .errors import ApiError

CONFIRM_SECONDS = 600
MAX_INDEX = 2147483647


def bounds(data):
    if set(data) != {'l', 'r'} or any(type(data[key]) is not int for key in ('l', 'r')):
        raise ApiError('l and r must be integers', 400, 'invalid_word_range')
    left, right = data['l'], data['r']
    if not 1 <= left <= right <= MAX_INDEX:
        raise ApiError('Range must satisfy 1 <= l <= r <= 2147483647', 400, 'invalid_word_range')
    return left, right


def _signer():
    return URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'],
        salt='dictionary-word-range-v1',
        signer_kwargs={'digest_method': hashlib.sha256},
    )


def _stale():
    return ApiError(
        'Words or dictionary changed, or confirmation expired; check the result and preview again',
        409,
        'stale_word_range',
    )


def _snapshot(cursor, dictionary, left, right):
    digest = hashlib.sha256()

    def add(value):
        data = json.dumps(value, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode(
            'ascii'
        )
        digest.update(len(data).to_bytes(8, 'big'))
        digest.update(data)

    # config_version alone is NOT a word-list version. Hash all active words too.
    add(
        [
            dictionary['id'],
            dictionary['dictname'],
            dictionary['ownerid'],
            dictionary['config_version'],
            str(dictionary['multiplier']) if dictionary.get('multiplier') is not None else None,
            dictionary.get('difficulty'),
            dictionary.get('rated_min'),
            dictionary.get('rated_max'),
        ]
    )
    total, first_id, last_id, samples = 0, None, None, []
    # Same transaction/connection, bounded Python memory for large dictionaries.
    with cursor.connection.cursor(SSDictCursor) as stream:
        stream.execute(
            'SELECT id, english, chinese FROM word WHERE dictid = %s AND deleted = 0 ORDER BY id',
            (dictionary['id'],),
        )
        for total, word in enumerate(stream, 1):
            add([word['id'], word['english'], word['chinese']])
            if total == left:
                first_id = word['id']
            if total == right:
                last_id = word['id']
            if left <= total <= right and (total < left + 5 or total > right - 5):
                samples.append({'position': total, **word})
    return {
        'total': total,
        'fingerprint': digest.hexdigest(),
        'first_id': first_id,
        'last_id': last_id,
        'words': samples,
    }


def _within(total, right):
    if right > total:
        raise ApiError(
            'Range exceeds the current active word count',
            400,
            'invalid_word_range',
            {'total': total},
        )


def preview(actor_id, dict_id, data):
    left, right = bounds(data)
    with reading() as cursor:
        cursor.execute('SELECT id, admin_level, deleted FROM user WHERE id = %s', (actor_id,))
        actor = cursor.fetchone()
        if actor is None or actor['deleted'] != 0:
            raise ApiError('Authentication required', 401, 'unauthenticated')
        dictionary = _dictionary(cursor, dict_id)
        require_dictionary_owner(actor, dictionary)
        state = _snapshot(cursor, dictionary, left, right)
        _within(state['total'], right)
        token = _signer().dumps(
            {
                'v': 1,
                'actor_id': actor_id,
                'dict_id': dict_id,
                'l': left,
                'r': right,
                'fingerprint': state['fingerprint'],
            }
        )
    return {
        'dict_id': dict_id,
        'dictname': dictionary['dictname'],
        'l': left,
        'r': right,
        'count': right - left + 1,
        'total': state['total'],
        'words': state['words'],
        'confirmation_token': token,
        'expires_in': CONFIRM_SECONDS,
    }


def _confirmation(actor_id, dict_id, data):
    if (
        set(data) != {'confirmation_token'}
        or not isinstance(data['confirmation_token'], str)
        or not 1 <= len(data['confirmation_token']) <= 2048
    ):
        raise ApiError('A range confirmation token is required', 400, 'invalid_range_confirmation')
    try:
        decision = _signer().loads(data['confirmation_token'], max_age=CONFIRM_SECONDS)
    except SignatureExpired:
        raise _stale() from None
    except BadSignature:
        raise ApiError('Invalid range confirmation', 400, 'invalid_range_confirmation') from None
    if (
        not isinstance(decision, dict)
        or set(decision) != {'v', 'actor_id', 'dict_id', 'l', 'r', 'fingerprint'}
        or type(decision['v']) is not int
        or decision['v'] != 1
        or any(type(decision[key]) is not int for key in ('actor_id', 'dict_id'))
        or not isinstance(decision['fingerprint'], str)
        or re.fullmatch('[0-9a-f]{64}', decision['fingerprint']) is None
    ):
        raise ApiError('Invalid range confirmation', 400, 'invalid_range_confirmation')
    if decision['actor_id'] != actor_id or decision['dict_id'] != dict_id:
        raise ApiError('Confirmation belongs to another actor or dictionary', 403, 'forbidden')
    bounds({'l': decision['l'], 'r': decision['r']})
    return decision


def delete(actor_id, dict_id, data):
    decision = _confirmation(actor_id, dict_id, data)
    left, right = decision['l'], decision['r']
    with transaction() as cursor:
        dictionary = _writable_dictionary(cursor, actor_id, dict_id)
        # First consistent read is AFTER actor and dictionary locks. Do not use a
        # pre-lock snapshot: another writer may have committed while we waited.
        state = _snapshot(cursor, dictionary, left, right)
        if state['fingerprint'] != decision['fingerprint']:
            raise _stale()
        _within(state['total'], right)
        # IDs identify this exact reviewed interval, even with ID gaps/soft deletes.
        cursor.execute(
            'UPDATE word SET deleted = 1 WHERE dictid = %s AND deleted = 0 AND id BETWEEN %s AND %s',
            (dict_id, state['first_id'], state['last_id']),
        )
        if cursor.rowcount != right - left + 1:
            raise _stale()  # Entire statement/transaction rolls back; never accept a partial batch.
    return {
        'dict_id': dict_id,
        'l': left,
        'r': right,
        'deleted_count': right - left + 1,
        'message': 'Reviewed word range deleted',
    }
