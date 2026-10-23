import json
from unittest.mock import MagicMock
from uuid import uuid4

import pymysql
import pytest

from wm_app.services import game_requests
from wm_app.services.errors import GameError


@pytest.mark.parametrize(
    'data',
    [
        {'request_id': None},
        {'request_id': ''},
        {'request_id': 123},
        {'request_id': 'not-a-uuid'},
        {'request_id': '00000000-0000-1000-8000-000000000000'},
        {'expected_version': None},
        {'expected_version': True},
        {'expected_version': -1},
        {'expected_version': '0'},
        {'expected_version': 1.0},
        {'expected_version': 2147483648},
    ],
)
def test_invalid_metadata_is_rejected_by_both_adapters(data):
    with pytest.raises(GameError) as error:
        game_requests.command_options(data)
    assert error.value.status == 400


def test_command_options_ignore_forged_identity_and_accept_zero():
    rid = str(uuid4())
    assert game_requests.command_options(
        {'uid': 999, 'request_id': rid, 'expected_version': 0}
    ) == {'request_id': rid, 'expected_version': 0}
    assert game_requests.validate_options(rid.upper(), 0) == (rid, 0)
    assert game_requests.command_options({}) == {}


def test_receipt_replay_uses_shared_lock_and_does_not_update():
    cursor = MagicMock()
    cursor.execute.side_effect = [pymysql.IntegrityError(1062, 'duplicate'), None]
    rid = str(uuid4())
    # Capture the canonical hash from a first reservation with a separate fake cursor.
    first = MagicMock()
    game_requests.reserve(first, 1, rid, 'end', 9, {}, 2)
    digest = first.execute.call_args.args[1][3]
    response = {'version': 3, 'perf': {'1': 1511}, 'request_id': rid}
    cursor.fetchone.return_value = {'payload_hash': digest, 'response': json.dumps(response)}
    assert game_requests.reserve(cursor, 1, rid, 'end', 9, {}, 2) == response
    assert cursor.execute.call_count == 2 and 'FOR SHARE' in cursor.execute.call_args.args[0]


def test_non_duplicate_database_errors_are_not_treated_as_replays():
    cursor = MagicMock()
    cursor.execute.side_effect = pymysql.IntegrityError(1452, 'bad reference')
    with pytest.raises(pymysql.IntegrityError):
        game_requests.reserve(cursor, 1, str(uuid4()), 'end', 9, {}, 0)
    cursor.fetchone.assert_not_called()


@pytest.mark.parametrize('response', [None, '{bad', '[]'])
def test_corrupt_receipts_never_reexecute_commands(response):
    cursor = MagicMock()
    cursor.execute.side_effect = [pymysql.IntegrityError(1062, 'duplicate'), None]
    rid = str(uuid4())
    first = MagicMock()
    game_requests.reserve(first, 1, rid, 'end', 9, {}, 2)
    digest = first.execute.call_args.args[1][3]
    cursor.fetchone.return_value = {'payload_hash': digest, 'response': response}
    with pytest.raises(GameError) as error:
        game_requests.reserve(cursor, 1, rid, 'end', 9, {}, 2)
    assert error.value.code == 'invalid_request_record'
    assert error.value.status == 503
    assert error.value.__suppress_context__ is True
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    'row,code,status',
    [
        (None, 'invalid_request_record', 503),
        ({'payload_hash': 'different', 'response': '{}'}, 'request_id_conflict', 409),
    ],
)
def test_duplicate_reservation_domain_errors_hide_expected_database_context(row, code, status):
    cursor = MagicMock()
    duplicate = pymysql.IntegrityError(1062, 'duplicate key with internal database details')
    cursor.execute.side_effect = [duplicate, None]
    cursor.fetchone.return_value = row
    with pytest.raises(GameError) as error:
        game_requests.reserve(cursor, 1, str(uuid4()), 'end', 9, {}, 2)
    assert error.value.code == code and error.value.status == status
    assert error.value.__context__ is duplicate
    assert error.value.__suppress_context__ is True
    assert error.value.__cause__ is None
    assert 'internal database details' not in str(error.value.payload())
    assert cursor.execute.call_count == 2
