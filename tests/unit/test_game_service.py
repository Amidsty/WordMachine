"""Control-flow tests only. MySQL integration tests validate transactions/locks."""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from wm_app.services import game
from wm_app.services.errors import GameError


def row(**changes):
    values = {
        'id': 1,
        'ownerid': 1,
        'dictid': 1,
        'users': '[1, 2]',
        'wordlist': '[11, 22]',
        'result': '[]',
        'status': 0,
        'version': 0,
    }
    values.update(changes)
    return values


@pytest.fixture
def cursor(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {'id': 11, 'english': 'apple', 'chinese': '苹果'},
        {'id': 22, 'english': 'banana', 'chinese': '香蕉'},
    ]

    @contextmanager
    def transaction():
        yield cursor

    monkeypatch.setattr(game, 'transaction', transaction)
    return cursor


def test_finished_game_never_updates_rating_again(cursor):
    cursor.fetchone.side_effect = [row(status=game.FINISHED), {'id': 1, 'deleted': 0}]
    result = game.end_game(1, 1)
    assert result['already_finished'] is True
    assert cursor.execute.call_count == 2
    assert 'FOR UPDATE' in cursor.execute.call_args.args[0]


def test_non_participant_cannot_end_even_finished_game(cursor):
    cursor.fetchone.return_value = row(status=game.FINISHED)
    with pytest.raises(GameError) as exc:
        game.end_game(1, 3)
    assert exc.value.status == 403


@pytest.mark.parametrize('status', [game.WAITING, game.FINISHED, game.CANCELLED])
def test_answer_rejects_non_running_games(cursor, status):
    cursor.fetchone.return_value = row(status=status)
    with pytest.raises(GameError):
        game.answer_game(1, 1, 11, 'apple')
    assert cursor.execute.call_count == 1


def test_owner_only_and_minimum_two_players(cursor):
    cursor.fetchone.return_value = row(status=game.WAITING)
    with pytest.raises(GameError, match='owner'):
        game.start_game(1, 2)
    cursor.fetchone.return_value = row(status=game.WAITING, users='[1]')
    with pytest.raises(GameError, match='2 players'):
        game.start_game(1, 1)


@pytest.mark.parametrize('action,uid', [('join', 1), ('leave', 1), ('start', 2), ('cancel', 2)])
def test_lobby_flags_share_command_preconditions_and_denied_commands_never_write(
    cursor, action, uid
):
    current = row(status=game.WAITING)
    cursor.fetchone.return_value = current
    assert game.lobby_actions(game._decode_game(current), uid)[action] is False
    with pytest.raises(GameError):
        getattr(game, action + '_game')(1, uid)
    assert cursor.execute.call_count == 1


def test_http_answer_uses_decoded_next_word_id_and_records_perf(cursor, monkeypatch):
    cursor.fetchone.side_effect = [
        row(),
        {'id': 1, 'deleted': 0, 'rating': 1500, 'gamehistory': '[]', 'ratinghistory': None},
        {'id': 2, 'rating': 1500, 'gamehistory': None, 'ratinghistory': None},
    ]
    monkeypatch.setattr('wm_app.services.rating.random.randint', lambda low, high: low)
    result = game.answer_game(1, 1, 11, 'APPLE')
    assert result['perf'] == 1511
    assert result['next_word'] == {'id': 22, 'chinese': '香蕉'}
    assert result['next_turn'] == 2
    updates = [
        call.args
        for call in cursor.execute.call_args_list
        if call.args[0].startswith('UPDATE game SET result')
    ]
    saved = json.loads(updates[0][1][0])[0]
    assert saved['perf'] == 1511
    assert saved['rating_version'] == 'legacy-v1'


def test_unanswered_players_get_no_rating_updates(cursor):
    cursor.fetchone.side_effect = [
        row(),
        {'id': 1, 'deleted': 0, 'rating': 1500, 'gamehistory': None, 'ratinghistory': None},
        {'id': 2, 'rating': 1200, 'gamehistory': None, 'ratinghistory': None},
        None,
    ]
    result = game.end_game(1, 1)
    assert result['perf'] == {}
    assert not any(call.args[0].startswith('UPDATE user') for call in cursor.execute.call_args_list)


def test_state_hides_future_answers_and_retains_answered_words(cursor, monkeypatch):
    @contextmanager
    def reading():
        yield cursor

    monkeypatch.setattr(game, 'reading', reading)
    cursor.fetchone.side_effect = [
        row(dictname='test', result='[{"uid": 1, "word_id": 11, "result": true, "perf": 1511}]'),
        {'id': 1, 'username': 'first', 'ratinghistory': None},
        {'id': 2, 'username': 'second', 'ratinghistory': None},
        {'id': 1, 'username': 'first'},
    ]
    cursor.fetchall.side_effect = [
        [],
        [],
        [],
        cursor.fetchall.return_value,
    ]  # Game ledger, events, manual sources, legacy words.
    state = game.get_game_state(1)
    assert state['words'][0]['english'] == 'apple'
    assert 'english' not in state['words'][1]
    assert state['next_word'] == {'id': 22, 'chinese': '香蕉'}
    assert state['perf'][1] == {'correct': 1, 'wrong': 0, 'perf': 1511}


def test_missing_legacy_perf_is_not_guessed(cursor):
    cursor.fetchone.side_effect = [
        row(result='[{"uid": 1, "word_id": 11, "result": true}]'),
        {'id': 1, 'deleted': 0, 'rating': 1500, 'gamehistory': None, 'ratinghistory': None},
        {'id': 2, 'rating': 1500, 'gamehistory': None, 'ratinghistory': None},
    ]
    with pytest.raises(GameError) as exc:
        game.end_game(1, 1)
    assert exc.value.code == 'legacy_data_error'
    assert not any(call.args[0].startswith('UPDATE') for call in cursor.execute.call_args_list)
