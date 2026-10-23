import json
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

import pymysql
import pytest

from wm_app.services import answer_conversion as conversion
from wm_app.services import game_answers as answers
from wm_app.services.errors import GameError

NOW = datetime(2026, 1, 1, 0, 0, 0, 123456)


def current(**changes):
    return {
        'id': 7,
        'version': 9,
        'ownerid': 1,
        'question_mode': 1,
        'participant_mode': 1,
        'participant_count': 2,
        'answer_mode': 0,
        'answer_count': None,
        'settlement_mode': 0,
        'wordlist': [11, 22],
        'users': [1, 2],
        'status': 0,
        **changes,
    }


def entry(**changes):
    return {
        'uid': 1,
        'word_id': 11,
        'answer': 'apple',
        'result': True,
        'usercombo': 1,
        'globalcombo': 1,
        'perf_delta': 11.123456789012345,
        'perf': 1511.1234567890124,
        'rating_version': 'legacy-v1',
        **changes,
    }


def test_complete_entry_is_copied_without_judging_or_inferring_history():
    original = entry(answer='not the expected answer', perf=1512.3456789012345)
    parsed, rows = conversion.prepare(current(), json.dumps([original]), NOW)
    assert parsed == [original]  # Even recorded correctness is not recomputed.
    assert rows[0]['perf'].hex() == original['perf'].hex()
    assert rows[0]['answered_at'] is None and rows[0]['recorded_at'] == NOW
    assert answers.validate_rows(current(answer_mode=1, answer_count=1), rows) == parsed


@pytest.mark.parametrize(
    'raw',
    [
        None,
        '',
        '  ',
        'null',
        '{}',
        '[null]',
        '[[]]',
        '[1]',
        '[true]',
        '[{"uid":1,"uid":2}]',
        '[{"uid":1,"\\u0075id":2}]',
        '[NaN]',
        '[Infinity]',
        '[-Infinity]',
        '[' * 1500 + ']' * 1500,
    ],
)
def test_ambiguous_or_malformed_json_is_not_fixed(raw):
    with pytest.raises(GameError) as error:
        conversion.prepare(current(), raw, NOW)
    assert error.value.code == 'unconvertible_game_answers'
    assert 'uid' not in error.value.message


@pytest.mark.parametrize('field', sorted(answers.ANSWER_FIELDS))
def test_no_missing_field_is_inferred(field):
    value = entry()
    del value[field]
    with pytest.raises(GameError) as error:
        conversion.prepare(current(), json.dumps([value]), NOW)
    assert error.value.code == 'unconvertible_game_answers'


@pytest.mark.parametrize(
    'value',
    [
        entry(extra='retain me'),
        entry(answered_at='2020-01-01'),
        entry(result=1),
        entry(result='true'),
        entry(uid=True),
        entry(uid=2),
        entry(word_id=True),
        entry(word_id=22),
        entry(answer=' APPLE '),
        entry(answer='\ud800'),
        entry(globalcombo=True),
        entry(usercombo=-1),
        entry(usercombo=2147483648),
        entry(rating_version='unknown'),
    ],
)
def test_extra_fields_wrong_order_and_values_are_not_discarded_or_normalized(value):
    with pytest.raises(GameError):
        conversion.prepare(current(), json.dumps([value]), NOW)


@pytest.mark.parametrize(
    'value', [True, '1', None, float('inf'), float('nan'), -0.0, 2**53 + 1, 10**400]
)
def test_nonfinite_or_inexact_scores_are_rejected_without_rounding(value):
    for field in ('perf', 'perf_delta'):
        with pytest.raises(GameError) as error:
            conversion.prepare(current(), json.dumps([entry(**{field: value})]), NOW)
        assert error.value.code == 'unconvertible_game_answers'


@pytest.mark.parametrize('value', [1500, 2**54, 1511.1234567890124, -10.5, 0.0])
def test_exact_binary64_scores_and_integers_are_preserved(value):
    parsed, rows = conversion.prepare(current(), json.dumps([entry(perf=value)]), NOW)
    assert rows[0]['perf'] == parsed[0]['perf'] == value


@pytest.mark.parametrize(
    'status,values',
    [(-1, [entry()]), (2, [entry()]), (9, []), (0, [entry(), entry(uid=2, word_id=22)])],
)
def test_invalid_state_or_unsettled_complete_prefix_is_rejected(status, values):
    with pytest.raises(GameError) as error:
        conversion.prepare(current(status=status), json.dumps(values), NOW)
    assert error.value.code == 'invalid_game_answers'


@pytest.mark.parametrize('status', [-1, 0, 1, 2])
def test_explicit_empty_array_is_valid_without_inventing_answers(status):
    assert conversion.prepare(current(status=status), ' [ ] ', NOW) == ([], [])


@pytest.mark.parametrize(
    'options',
    [
        dict(apply=True),
        dict(expected_version=True),
        dict(expected_version=-1),
        dict(expected_version='1'),
        dict(game_id=True),
        dict(game_id=0),
        dict(game_id=2147483648),
        dict(apply='false'),
    ],
)
def test_invalid_parameters_fail_before_any_connection(monkeypatch, options):
    connect = MagicMock(side_effect=AssertionError('must not connect'))
    monkeypatch.setattr(conversion, 'transaction', connect)
    monkeypatch.setattr(conversion, 'reading', connect)
    with pytest.raises(GameError) as error:
        conversion.convert_game(**{'game_id': 7, **options})
    assert error.value.code == 'invalid_parameters'
    connect.assert_not_called()


def test_default_transaction_is_read_only_and_report_has_no_answers(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [current(wordlist='[11,22]', result=json.dumps([entry()])), None]
    cursor.fetchall.side_effect = [
        [
            {'game_id': 7, 'user_id': uid, 'position': index, 'joined_at': None, 'recorded_at': NOW}
            for index, uid in enumerate([1, 2])
        ],
        [
            {'position': index, 'word_id': wid, 'english': 'private answer', 'chinese': '私有题面'}
            for index, wid in enumerate([11, 22])
        ],
        [{'id': 1}, {'id': 2}],
        [],
        [],
    ]

    @contextmanager
    def reading():
        yield cursor

    monkeypatch.setattr(conversion, 'reading', reading)
    report = conversion.convert_game(7)
    assert report == {'game_id': 7, 'status': 'ready', 'answers': 1, 'version': 9}
    queries = [call.args[0] for call in cursor.execute.call_args_list]
    assert queries[0] == 'SET TRANSACTION READ ONLY'
    assert all(sql.startswith(('SELECT ', 'SET TRANSACTION READ ONLY')) for sql in queries)
    assert not any(
        'FOR UPDATE' in sql or 'FOR SHARE' in sql or 'FROM word ' in sql for sql in queries
    )


@pytest.mark.parametrize(
    'kind,module', [('answers', 'answer_conversion'), ('participants', 'participant_conversion')]
)
def test_conversion_cli_database_errors_are_generic_and_do_not_claim_rollback(
    app, monkeypatch, kind, module
):
    fail = MagicMock(
        side_effect=pymysql.OperationalError(2013, 'secret SQL or connection information')
    )
    monkeypatch.setattr(f'wm_app.services.{module}.convert_game', fail)
    result = app.test_cli_runner().invoke(args=[f'convert-game-{kind}', '--game-id', '7'])
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        'game_id': 7,
        'code': 'conversion_database_error',
        'message': 'Database operation failed; inspect current state before retrying conversion',
    }
    assert 'secret' not in result.output and 'rollback' not in result.output
