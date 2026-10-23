"""Owner consent and reviewed transfer. Lock order: actor -> dict -> application.

No request lock before users; same-dictionary submissions/reviews serialize on
its parent. Approval validates a signed current-content review, not config_version
alone (word edits do not advance it). Terminal decisions are immutable receipts.
"""

import hashlib
import json
from datetime import datetime

import pymysql
from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..db import reading, transaction
from ..security.permissions import admin_level, lock_actor
from . import dictionary, rated_eligibility, word_ranges
from .errors import ApiError
from .game_requests import validate_options
from .pagination import ListQuery, page_offset
from .validation import string

REVIEW_SECONDS = 600


def _error(message, code='promotion_conflict', status=409):
    return ApiError(message, status, code)


def _reviewer(actor):
    if admin_level(actor) < 4:
        raise _error('Dictionary promotion review requires level 4 or higher', 'forbidden', 403)


def _uuid(value):
    if value is None:
        raise ApiError('request_id is required')
    return validate_options(value)[0]


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    ).hexdigest()


def _signer():
    return URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'],
        salt='dictionary-promotion-review-v1',
        signer_kwargs={'digest_method': hashlib.sha256},
    )


def _dict(cursor, dict_id):
    cursor.execute(
        'SELECT id, dictname, ownerid, deleted, multiplier, difficulty, config_version, rated_min, rated_max FROM dict WHERE id=%s FOR UPDATE',
        (dict_id,),
    )
    value = cursor.fetchone()
    if value is None:
        raise _error('Dictionary not found', 'not_found', 404)
    return value


def _application(cursor, request_id, dict_id, *, lock=False):
    cursor.execute(
        'SELECT * FROM dictionary_promotion WHERE request_id=%s' + (' FOR UPDATE' if lock else ''),
        (request_id,),
    )
    row = cursor.fetchone()
    if row is None or row['dict_id'] != dict_id:
        raise _error('Application not found', 'not_found', 404)
    return row


def _public(row):
    keys = (
        'request_id',
        'dict_id',
        'applicant_id',
        'reason',
        'state',
        'reviewer_id',
        'reviewer_level',
        'review_reason',
        'rated_min',
        'rated_max',
        'result_version',
    )
    result = {key: row[key] for key in keys}
    for key in ('submitted_at', 'reviewed_at'):
        result[key] = row[key].isoformat() + 'Z' if row[key] else None
    return result


def _reader(cursor, actor_id):
    cursor.execute('SELECT id, admin_level, deleted FROM user WHERE id=%s', (actor_id,))
    actor = cursor.fetchone()
    if actor is None or actor['deleted'] != 0:
        raise _error('Account is no longer active', 'forbidden', 403)
    return actor


def submit(actor_id, dict_id, data):
    if set(data) != {'request_id', 'expected_version', 'reason'}:
        raise ApiError('request_id, expected_version and reason are required')
    request_id = _uuid(data['request_id'])
    expected = data['expected_version']
    if type(expected) is not int or not 0 <= expected <= 2147483647:
        raise ApiError('expected_version must be a nonnegative INT')
    reason = string(data['reason'], 'Reason', minimum=1, maximum=500)
    fingerprint = _hash([actor_id, dict_id, expected, reason])
    with transaction() as cursor:
        lock_actor(cursor, actor_id)
        source = _dict(cursor, dict_id)
        # Nonlocking missing-key read: no insert gap-lock upgrade between different dicts.
        cursor.execute('SELECT * FROM dictionary_promotion WHERE request_id=%s', (request_id,))
        previous = cursor.fetchone()
        if previous is not None:
            if (
                previous['applicant_id'] != actor_id
                or previous['dict_id'] != dict_id
                or previous['submit_hash'] != fingerprint
            ):
                raise _error('Request ID belongs to a different application', 'request_id_conflict')
            return {
                'request_id': request_id,
                'dict_id': dict_id,
                'message': 'Application submitted',
            }
        if source['deleted'] != 0 or source['ownerid'] != actor_id:
            raise _error(
                'Only the owner of an active personal dictionary may apply', 'forbidden', 403
            )
        if source['config_version'] != expected:
            raise _error('Dictionary changed; refresh before applying', 'stale_dictionary_version')
        cursor.execute(
            'SELECT request_id FROM dictionary_promotion WHERE pending_dict_id=%s', (dict_id,)
        )
        if cursor.fetchone():
            raise _error('This dictionary already has a pending application', 'promotion_pending')
        try:
            cursor.execute(
                'INSERT INTO dictionary_promotion (request_id, dict_id, applicant_id, submit_hash, reason, submitted_at) VALUES (%s,%s,%s,%s,%s,%s)',
                (request_id, dict_id, actor_id, fingerprint, reason, datetime.utcnow()),
            )
        except pymysql.IntegrityError as error:
            if error.args[0] != 1062:
                raise
            raise _error(
                'Request ID or pending application already exists', 'request_id_conflict'
            ) from None
    return {'request_id': request_id, 'dict_id': dict_id, 'message': 'Application submitted'}


def listing(actor_id, query=ListQuery()):
    with reading() as cursor:
        actor = _reader(cursor, actor_id)
        where, params = '1=1', []
        if admin_level(actor) < 4:
            where, params = 'p.applicant_id=%s', [actor_id]
        if query.q:
            where += " AND d.dictname LIKE %s ESCAPE '!'"
            params.append(query.like)
        source = 'dictionary_promotion p JOIN dict d ON d.id=p.dict_id'
        cursor.execute('SELECT COUNT(*) AS total FROM ' + source + ' WHERE ' + where, params)
        pagination = query.metadata(cursor.fetchone()['total'])
        cursor.execute(
            'SELECT p.*, d.dictname FROM '
            + source
            + ' WHERE '
            + where
            + ' ORDER BY p.submitted_at DESC, p.request_id DESC LIMIT %s OFFSET %s',
            [*params, query.per_page, page_offset(pagination)],
        )
        items = [{**_public(row), 'dictname': row['dictname']} for row in cursor.fetchall()]
    return {'applications': items, 'pagination': pagination}


def review(actor_id, dict_id, request_id):
    request_id = _uuid(request_id)
    with reading() as cursor:
        actor = _reader(cursor, actor_id)
        row = _application(cursor, request_id, dict_id)
        if row['applicant_id'] != actor_id and admin_level(actor) < 4:
            raise _error('Application is private', 'forbidden', 403)
        cursor.execute(
            'SELECT id, dictname, ownerid, deleted, multiplier, difficulty, config_version, rated_min, rated_max FROM dict WHERE id=%s',
            (dict_id,),
        )
        source = cursor.fetchone()
        result = {
            'application': _public(row),
            'dict': dictionary._public(source),
            'review_token': None,
            'word_count': None,
        }
        if (
            admin_level(actor) >= 4
            and row['state'] == 0
            and source['deleted'] == 0
            and source['ownerid'] == row['applicant_id']
        ):
            state = word_ranges._snapshot(cursor, source, 1, 1)
            result['word_count'] = state['total']
            result['review_token'] = _signer().dumps(
                {
                    'actor_id': actor_id,
                    'dict_id': dict_id,
                    'request_id': request_id,
                    'fingerprint': state['fingerprint'],
                }
            )
    return result


def decide(actor_id, dict_id, request_id, data):
    request_id = _uuid(request_id)
    approve = data.get('approve')
    if type(approve) is not bool:
        raise ApiError('approve must be a boolean')
    fields = {'approve', 'reason'} | (
        {'rated_min', 'rated_max', 'review_token'} if approve else set()
    )
    if set(data) != fields:
        raise ApiError(
            'Approval requires explicit bounds and a review token; rejection only requires a reason'
        )
    reason = string(data['reason'], 'Reason', minimum=1, maximum=500)
    lower, upper = (
        rated_eligibility.bounds(data['rated_min'], data['rated_max']) if approve else (None, None)
    )
    if approve and (
        not isinstance(data['review_token'], str) or not 1 <= len(data['review_token']) <= 2048
    ):
        raise ApiError('Invalid review token')
    digest = _hash([actor_id, dict_id, request_id, data])
    with transaction() as cursor:
        actor = lock_actor(cursor, actor_id)
        _reviewer(actor)
        source = _dict(cursor, dict_id)
        row = _application(cursor, request_id, dict_id, lock=True)
        if row['state'] != 0:
            if row['reviewer_id'] == actor_id and row['review_hash'] == digest:
                return {'application': _public(row), 'message': 'Application reviewed'}
            raise _error('Application already reviewed; refresh its result')
        version, content_hash = None, None
        if approve:
            if source['deleted'] != 0 or source['ownerid'] != row['applicant_id']:
                raise _error('Dictionary is no longer the applicant personal dictionary')
            try:
                token = _signer().loads(data['review_token'], max_age=REVIEW_SECONDS)
            except BadSignature:
                raise _error(
                    'Review expired or invalid; review again', 'stale_promotion_review'
                ) from None
            state = word_ranges._snapshot(cursor, source, 1, 1)
            content_hash = state['fingerprint']
            if token != {
                'actor_id': actor_id,
                'dict_id': dict_id,
                'request_id': request_id,
                'fingerprint': content_hash,
            }:
                raise _error('Dictionary or words changed; review again', 'stale_promotion_review')
            before = rated_eligibility.stored(source)
            version = dictionary._next_version(source)
            cursor.execute(
                'UPDATE dict SET ownerid=NULL, rated_min=%s, rated_max=%s, config_version=%s WHERE id=%s',
                (lower, upper, version, dict_id),
            )
            cursor.execute(
                'INSERT INTO dictionary_rated_audit (dict_id, actor_id, actor_level, min_before, max_before, min_after, max_after, config_version, reason, recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (
                    dict_id,
                    actor_id,
                    admin_level(actor),
                    *before,
                    lower,
                    upper,
                    version,
                    reason,
                    datetime.utcnow(),
                ),
            )
        cursor.execute(
            'UPDATE dictionary_promotion SET state=%s, reviewer_id=%s, reviewer_level=%s, review_reason=%s, reviewed_at=%s, review_hash=%s, reviewed_fingerprint=%s, rated_min=%s, rated_max=%s, result_version=%s WHERE request_id=%s',
            (
                1 if approve else 2,
                actor_id,
                admin_level(actor),
                reason,
                datetime.utcnow(),
                digest,
                content_hash,
                lower,
                upper,
                version,
                request_id,
            ),
        )
        row = _application(cursor, request_id, dict_id, lock=True)
    return {'application': _public(row), 'message': 'Application reviewed'}
