"""Explicit, lossless single-game answer conversion. No HTTP/Socket or startup hook.

Only existing snapshots and normalized participants are eligible. Never rejudge,
reroll scores, infer missing fields/times, convert settlements, or repair data.
"""

import json
import math
from datetime import datetime

from ..db import reading, transaction
from . import (
    game_answers as answers,
)
from . import (
    game_participants as participants,
)
from . import (
    game_questions as questions,
)
from . import game_requests, game_settlements
from .errors import GameError
from .legacy_game import unique_ids


def unsupported():
    return GameError(
        'Stored answers cannot be copied losslessly; review the original data',
        409,
        'unconvertible_game_answers',
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise unsupported()  # json.loads normally discards earlier duplicate keys.
        result[key] = value
    return result


def _invalid_constant(value):
    raise unsupported()  # NaN/Infinity are accepted by Python's default decoder, not here.


def _exact_score(value):
    if type(value) not in (int, float):
        raise unsupported()
    try:
        binary64 = float(value)
    except (OverflowError, ValueError):
        raise unsupported() from None
    if (
        not math.isfinite(binary64)
        or binary64 != value
        or (binary64 == 0 and math.copysign(1, binary64) < 0)
    ):
        # Reject inexact integers and signed zero, rather than relying on SQL or
        # its text protocol to silently round/erase a historical numeric value.
        raise unsupported()


def prepare(game, raw, recorded_at):
    """Validate the source before writing; share target shape/order rules with runtime."""
    if not isinstance(raw, str):
        raise unsupported()  # NULL/blank does not prove an explicitly empty history.
    try:
        entries = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (TypeError, ValueError, RecursionError):
        raise unsupported() from None
    if not isinstance(entries, list):
        raise unsupported()
    rows = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != answers.ANSWER_FIELDS:
            raise unsupported()  # No defaults, discarded extra fields or inferred version.
        for field in ('perf', 'perf_delta'):
            _exact_score(entry[field])
        rows.append(answers.encode(game, index, entry, answered_at=None, recorded_at=recorded_at))
    candidate = {**game, 'answer_mode': 1, 'answer_count': len(rows)}
    # Includes known states, a complete prefix, and no un-settled final answer.
    answers.validate_rows(candidate, rows)
    return entries, rows


def _check_references(cursor, ids):
    placeholders = ', '.join(['%s'] * len(ids))
    cursor.execute('SELECT id FROM user WHERE id IN (' + placeholders + ')', ids)
    if {row['id'] for row in cursor.fetchall()} != set(ids):
        raise participants.invalid_participants()


def _check_settlement(cursor, game):
    # Check both modes, including unexpected partial copies. This is not a full
    # user-rating-history audit and never computes or writes any settlement.
    cursor.execute('SELECT * FROM game_settlement WHERE game_id = %s', (game['id'],))
    header = cursor.fetchone()
    cursor.execute('SELECT * FROM game_rating WHERE game_id = %s ORDER BY user_id', (game['id'],))
    game_settlements.validate_rows(game, header, cursor.fetchall())


def convert_game(game_id, *, apply=False, expected_version=None):
    if type(game_id) is not int or not 1 <= game_id <= answers.MAX_INT or type(apply) is not bool:
        raise GameError('Invalid conversion parameters', 400, 'invalid_parameters')
    game_requests.validate_options(expected_version=expected_version)
    if apply and expected_version is None:
        raise GameError(
            'Applying conversion requires expected_version from a reviewed dry run',
            400,
            'invalid_parameters',
        )
    with transaction() if apply else reading() as cursor:
        if not apply:
            cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute(
            'SELECT * FROM game WHERE id = %s' + (' FOR UPDATE' if apply else ''), (game_id,)
        )
        game = cursor.fetchone()
        if game is None:
            raise GameError('Game not found', 404, 'not_found')
        game_requests.check_version(game, expected_version)
        normalized = answers.relational(game)
        if questions.source(game) != 'snapshot':
            raise GameError(
                'Answer conversion requires existing question snapshots; no questions were created',
                409,
                'answer_conversion_requires_snapshot',
            )
        if not participants.relational(game):
            raise GameError(
                'Answer conversion requires normalized participants; convert membership explicitly first',
                409,
                'answer_conversion_requires_participants',
            )
        game['wordlist'] = unique_ids(game['wordlist'])
        participants.load_many(cursor, [game])
        questions.load(cursor, game)  # Never capture/live-read today's dictionary.
        _check_references(cursor, game['users'])  # Soft-deleted user references are retained.
        stored = answers.read_rows(cursor, game_id)
        if normalized:
            game['result'] = answers.validate_rows(game, stored)
            _check_settlement(cursor, game)
            return {
                'game_id': game_id,
                'status': 'already_normalized',
                'answers': len(stored),
                'version': game['version'],
            }
        if stored:
            raise answers.invalid_answers()  # Never merge/overwrite a partial copy.
        entries, rows = prepare(game, game['result'], datetime.utcnow())
        candidate = {**game, 'answer_mode': 1, 'answer_count': len(rows), 'result': entries}
        _check_settlement(cursor, candidate)
        if game['version'] == game_requests.MAX_VERSION:
            raise GameError('Game version exhausted', 409, 'invalid_game_state')
        report = {
            'game_id': game_id,
            'status': 'ready',
            'answers': len(rows),
            'version': game['version'],
        }
        if not apply:
            return report
        # Same game -> ascending user -> child-reference order as normal writes.
        # No shared-to-exclusive user lock upgrade and no rating/history changes.
        participants.lock_references(cursor, game['users'])
        # prepare() used a validation timestamp. Record the actual write phase
        # after potentially waiting for references, never a historical answer time.
        recorded_at = datetime.utcnow()
        for row in rows:
            row['recorded_at'] = recorded_at
            answers.insert(cursor, row)
        version = game['version'] + 1
        cursor.execute(
            'UPDATE game SET answer_mode = 1, answer_count = %s, version = %s WHERE id = %s',
            (len(rows), version, game_id),
        )
        copied = answers.read_rows(cursor, game_id)
        answers.validate_rows(candidate, copied)
        if copied != rows:
            raise unsupported()  # Verify SQL/text/timestamp round trip before committing.
        return {**report, 'status': 'converted', 'version': version}
