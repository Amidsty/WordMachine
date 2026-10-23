"""Durable command receipts. Reservation, game writes and receipt commit together.

Reserve before taking game/user locks. actor_id deliberately has no FK: an FK
check here would take a shared user lock before the game's ordered user locks,
causing lock inversions/upgrades between concurrent answers. Authorization lives
at the HTTP/Socket boundary; receipts also survive account archival.
"""

import hashlib
import json
from uuid import UUID

import pymysql

from .errors import GameError

MAX_VERSION = 2147483647


def validate_options(request_id=None, expected_version=None):
    if request_id is not None:
        try:
            parsed = UUID(request_id) if isinstance(request_id, str) else None
        except (ValueError, AttributeError):
            parsed = None
        if parsed is None or parsed.version != 4 or str(parsed) != request_id.lower():
            raise GameError('request_id must be a canonical UUID v4', 400, 'invalid_parameters')
        request_id = str(parsed)
    if expected_version is not None and (
        type(expected_version) is not int or not 0 <= expected_version <= MAX_VERSION
    ):
        raise GameError('expected_version must be a nonnegative INT', 400, 'invalid_parameters')
    return request_id, expected_version


def command_options(data):
    """Only transport metadata; never accepts actor identity from the payload."""
    options = {key: data[key] for key in ('request_id', 'expected_version') if key in data}
    if any(value is None for value in options.values()):
        raise GameError('Command metadata cannot be null', 400, 'invalid_parameters')
    validate_options(**options)
    return options


def reserve(cursor, actor_id, request_id, action, game_id, payload, expected_version):
    if request_id is None:
        return None  # Compatibility only: legacy callers have no replay guarantee.
    canonical = json.dumps(
        [action, game_id, payload, expected_version],
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True,
        allow_nan=False,
    )
    digest = hashlib.sha256(canonical.encode('ascii')).hexdigest()
    try:
        cursor.execute(
            'INSERT INTO game_request (actor_id, request_id, action, payload_hash, created_at) '
            'VALUES (%s, %s, %s, %s, UTC_TIMESTAMP())',
            (actor_id, request_id, action, digest),
        )
    except pymysql.IntegrityError as error:
        if error.args[0] != 1062:
            raise
        # Multiple duplicates can hold shared index locks; never upgrade them to
        # FOR UPDATE. A current shared read sees the winner after its commit.
        cursor.execute(
            'SELECT payload_hash, response FROM game_request '
            'WHERE actor_id = %s AND request_id = %s FOR SHARE',
            (actor_id, request_id),
        )
        row = cursor.fetchone()
        # Duplicate-key errors are expected here, not the cause of a public domain error.
        if row is None or row['response'] is None:
            raise GameError(
                'Stored request requires review', 503, 'invalid_request_record'
            ) from None
        if row['payload_hash'] != digest:
            raise GameError(
                'request_id was already used for a different command', 409, 'request_id_conflict'
            ) from None
        try:
            response = json.loads(row['response'])
        except (TypeError, ValueError):
            raise GameError(
                'Stored request requires review', 503, 'invalid_request_record'
            ) from None
        if not isinstance(response, dict):
            raise GameError(
                'Stored request requires review', 503, 'invalid_request_record'
            ) from None
        return response
    return None


def check_version(game, expected_version):
    version = game['version']
    if type(version) is not int or not 0 <= version <= MAX_VERSION:
        raise GameError('Invalid stored game version', 409, 'legacy_data_error')
    if expected_version is not None and version != expected_version:
        raise GameError(
            'Game changed; refresh before issuing a new command', 409, 'stale_game_version'
        )


def complete(cursor, actor_id, request_id, game_id, version, response):
    # JSON round trip gives both first replies and replays the same key/value types.
    response = {**response, 'version': version}
    if request_id is not None:
        response['request_id'] = request_id
    encoded = json.dumps(response, ensure_ascii=True, allow_nan=False)
    if request_id is not None:
        cursor.execute(
            'UPDATE game_request SET game_id = %s, response = %s '
            'WHERE actor_id = %s AND request_id = %s',
            (game_id, encoded, actor_id, request_id),
        )
    return json.loads(encoded)
