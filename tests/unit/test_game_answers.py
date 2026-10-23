from datetime import datetime
from unittest.mock import MagicMock

import pytest

from wm_app.services import game
from wm_app.services import game_answers as answers
from wm_app.services.errors import GameError


def current(**changes):
    return {
        'id': 7,
        'answer_mode': 1,
        'answer_count': 1,
        'question_mode': 1,
        'participant_mode': 1,
        'wordlist': [11, 22],
        'users': [2, 1],
        'status': 0,
        'result': 'invalid archive',
        **changes,
    }


def row(**changes):
    return {
        'game_id': 7,
        'position': 0,
        'user_id': 2,
        'answer': 'apple',
        'correct': 1,
        'usercombo': 1,
        'globalcombo': 1,
        'perf_delta': 11.123456789012345,
        'perf': 1511.1234567890124,
        'rating_version': 'legacy-v1',
        'answered_at': datetime(2026, 1, 1),
        'recorded_at': datetime(2026, 1, 1),
        **changes,
    }


def test_relational_load_ignores_archived_json_and_keeps_protocol_and_floats():
    cursor = MagicMock()
    cursor.fetchall.return_value = [row()]
    result = answers.load(cursor, current())[0]
    assert result == {
        'uid': 2,
        'word_id': 11,
        'answer': 'apple',
        'result': True,
        'usercombo': 1,
        'globalcombo': 1,
        'perf_delta': row()['perf_delta'],
        'perf': row()['perf'],
        'rating_version': 'legacy-v1',
    }
    assert result['perf'].hex() == row()['perf'].hex()
    assert 'ORDER BY position' in cursor.execute.call_args.args[0]


@pytest.mark.parametrize(
    'changes',
    [
        {'answer_mode': True},
        {'answer_mode': 2},
        {'answer_mode': 0},
        {'answer_count': None},
        {'answer_count': True},
        {'answer_count': -1},
        {'answer_count': 2147483648},
        {'question_mode': 0},
        {'participant_mode': 0},
        {'participant_mode': True},
    ],
)
def test_reject_invalid_metadata(changes):
    with pytest.raises(GameError) as error:
        answers.relational(current(**changes))
    assert error.value.code == 'invalid_game_answers'


@pytest.mark.parametrize(
    'changes',
    [
        {'position': 1},
        {'position': True},
        {'game_id': 8},
        {'user_id': 1},
        {'user_id': True},
        {'correct': 2},
        {'correct': '1'},
        {'answer': 'APPLE'},
        {'answer': ' apple'},
        {'answer': ''},
        {'answer': '\ud800'},
        {'answer': '🍎' * 16384},
        {'answer': None},
        {'usercombo': -1},
        {'globalcombo': True},
        {'perf': float('inf')},
        {'perf_delta': float('nan')},
        {'perf': True},
        {'rating_version': None},
        {'rating_version': 'guessed'},
        {'answered_at': '2026-01-01'},
        {'recorded_at': None},
    ],
)
def test_reject_invalid_record_without_repair(changes):
    with pytest.raises(GameError) as error:
        answers.validate_rows(current(), [row(**changes)])
    assert error.value.code == 'invalid_game_answers'


@pytest.mark.parametrize(
    'changes,rows',
    [
        ({}, []),
        ({'answer_count': 0}, [row()]),
        ({'status': -1}, [row()]),
        ({'status': 2}, [row()]),
        ({'status': 9}, [row()]),
        ({'wordlist': [11]}, [row()]),
    ],
)
def test_reject_incomplete_or_impossible_committed_prefix(changes, rows):
    with pytest.raises(GameError):
        answers.validate_rows(current(**changes), rows)


def test_early_finish_and_unknown_historical_timestamp_are_representable():
    assert len(answers.validate_rows(current(status=1), [row(answered_at=None)])) == 1
    assert answers.validate_rows(current(status=1, answer_count=0), []) == []


def test_append_inserts_only_new_row_and_count_not_another_json_copy():
    cursor = MagicMock()
    state = current(answer_count=0, result=[])
    entry = answers.validate_rows(current(), [row()])[0]
    answers.append(cursor, state, entry)
    calls = cursor.execute.call_args_list
    assert len(calls) == 2 and calls[0].args[0].startswith('INSERT INTO game_answer')
    assert calls[0].args[1]['answered_at'] == calls[0].args[1]['recorded_at']
    assert calls[1].args == ('UPDATE game SET answer_count = %s WHERE id = %s', (1, 7))
    assert state['result'] == [entry] and state['answer_count'] == 1


def test_legacy_json_uses_same_result_shape_without_querying_relations():
    cursor = MagicMock()
    state = current(answer_mode=0, answer_count=None, result='[{"uid": 2, "perf": 1511}]')
    state['result'] = answers.load(cursor, state)
    cursor.execute.assert_not_called()
    answers.append(cursor, state, {'uid': 1, 'perf': 1501})
    assert cursor.execute.call_args.args[0].startswith('UPDATE game SET result')
    assert len(state['result']) == 2


@pytest.mark.parametrize('value', [None, 1, '', ' ' * 256, 'a' * 256, '\ud800'])
def test_shared_answer_entry_rejects_invalid_input_before_any_connection(monkeypatch, value):
    transaction = MagicMock(side_effect=AssertionError('must not connect'))
    monkeypatch.setattr(game, 'transaction', transaction)
    with pytest.raises(GameError) as error:
        game.answer_game(1, 1, 11, value)
    assert error.value.code == 'invalid_parameters'
    transaction.assert_not_called()
