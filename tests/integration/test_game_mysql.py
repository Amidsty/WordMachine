import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from wm_app import socketio
from wm_app.db import reading, transaction
from wm_app.services import game, game_settlements
from wm_app.services.errors import GameError
from wm_app.services.rating import rating_delta

pytestmark = pytest.mark.mysql


def query(app, sql, params=()):
    with app.app_context(), reading() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def execute(app, sql, params=()):
    with app.app_context(), transaction() as cursor:
        cursor.execute(sql, params)


def rating_history(app, uid):
    with app.app_context(), reading() as cursor:
        cursor.execute(
            'SELECT id, rating, ratinghistory, rating_ledger_id, rating_event_id FROM user WHERE id = %s',
            (uid,),
        )
        return game_settlements.histories(cursor, [cursor.fetchone()])[0]['ratinghistory']


def parallel(app, *operations):
    barrier = threading.Barrier(len(operations))

    def run(operation):
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                return operation()
            except GameError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        futures = [pool.submit(run, operation) for operation in operations]
        return [future.result(timeout=20) for future in futures]


def test_http_socket_scoring_and_no_future_answers(mysql_app, mysql_login, monkeypatch):
    monkeypatch.setattr('wm_app.services.rating.random.randint', lambda low, high: low)
    client, _ = mysql_login(1)
    state = client.get('/api/game/1').json['game']
    assert 'english' not in state['next_word']
    assert all('english' not in word for word in state['words'])
    response = client.post('/api/game/1/answer', json={'word_id': 11, 'answer': 'APPLE'})
    assert response.status_code == 200
    assert response.json['perf'] == 1511
    assert response.json['next_word'] == {'id': 22, 'chinese': '香蕉'}
    second, csrf = mysql_login(2)
    socket = socketio.test_client(mysql_app, flask_test_client=second, auth={'csrf_token': csrf})
    try:
        socket.emit(
            'game.answer', {'game_id': 1, 'word_id': 22, 'answer': 'banana', 'csrf_token': csrf}
        )
        event = next(
            event for event in socket.get_received() if event['name'] == 'game.answer_result'
        )
        assert event['args'][0]['perf'] == 1511
    finally:
        socket.disconnect()
    results = json.loads(query(mysql_app, 'SELECT result FROM game WHERE id = 1')[0]['result'])
    assert [entry['uid'] for entry in results] == [1, 2]
    assert all(entry['rating_version'] == 'legacy-v1' for entry in results)


def test_concurrent_join_does_not_lose_players(mysql_app):
    execute(mysql_app, "UPDATE game SET status = -1, users = '[1]' WHERE id = 1")
    results = parallel(mysql_app, lambda: game.join_game(1, 2), lambda: game.join_game(1, 3))
    assert all(isinstance(result, dict) for result in results)
    assert set(json.loads(query(mysql_app, 'SELECT users FROM game WHERE id = 1')[0]['users'])) == {
        1,
        2,
        3,
    }


def test_concurrent_duplicate_answer_is_recorded_once(mysql_app):
    results = parallel(
        mysql_app,
        lambda: game.answer_game(1, 1, 11, 'apple'),
        lambda: game.answer_game(1, 1, 11, 'apple'),
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    result = query(mysql_app, 'SELECT result FROM game WHERE id = 1')[0]['result']
    assert len(json.loads(result)) == 1


def test_concurrent_end_and_repeat_do_not_settle_twice(mysql_app):
    with mysql_app.app_context():
        game.answer_game(1, 1, 11, 'apple')
    results = parallel(mysql_app, lambda: game.end_game(1, 1), lambda: game.end_game(1, 2))
    assert sorted(item['already_finished'] for item in results) == [False, True]
    before = query(mysql_app, 'SELECT id, rating, ratinghistory FROM user ORDER BY id')
    with mysql_app.app_context():
        assert game.end_game(1, 1)['already_finished'] is True
    assert query(mysql_app, 'SELECT id, rating, ratinghistory FROM user ORDER BY id') == before
    assert len(rating_history(mysql_app, 1)) == 1
    assert not rating_history(mysql_app, 2)
    assert before[0]['ratinghistory'] is before[1]['ratinghistory'] is None
    assert before[1]['rating'] == 1500


def test_answer_end_race_is_atomic(mysql_app):
    parallel(mysql_app, lambda: game.answer_game(1, 1, 11, 'apple'), lambda: game.end_game(1, 2))
    row = query(mysql_app, 'SELECT result, status FROM game WHERE id = 1')[0]
    user = query(mysql_app, 'SELECT rating, ratinghistory FROM user WHERE id = 1')[0]
    assert row['status'] == game.FINISHED
    answers = json.loads(row['result'])
    if answers:
        assert user['rating'] == 1500 + rating_delta(1500, answers[0]['perf'])
        assert len(rating_history(mysql_app, 1)) == 1
    else:
        assert user['rating'] == 1500 and user['ratinghistory'] is None


def test_final_answer_auto_settles_and_rolls_back_on_failure(mysql_app, monkeypatch):
    execute(mysql_app, "UPDATE game SET wordlist = '[11]' WHERE id = 1")
    settle = game._settle

    def fail_after_settlement(*args):
        settle(*args)
        raise RuntimeError('injected failure after rating updates')

    monkeypatch.setattr(game, '_settle', fail_after_settlement)
    with mysql_app.app_context(), pytest.raises(RuntimeError):
        game.answer_game(1, 1, 11, 'apple')
    row = query(mysql_app, 'SELECT status, result FROM game WHERE id = 1')[0]
    assert row == {'status': game.RUNNING, 'result': '[]'}
    assert query(mysql_app, 'SELECT rating, gamehistory, ratinghistory FROM user WHERE id = 1')[
        0
    ] == {'rating': 1500, 'gamehistory': None, 'ratinghistory': None}
    monkeypatch.setattr(game, '_settle', settle)
    with mysql_app.app_context():
        assert game.answer_game(1, 1, 11, 'apple')['status'] == game.FINISHED
    assert len(rating_history(mysql_app, 1)) == 1


def test_two_games_cannot_lose_rating_changes(mysql_app):
    answers = json.dumps([{'uid': 1, 'word_id': 11, 'result': True, 'perf': 1600}])
    execute(mysql_app, 'UPDATE game SET result = %s WHERE id = 1', (answers,))
    second_answers = json.dumps(
        [
            {'uid': 2, 'word_id': 11, 'result': True, 'perf': 1600},
            {'uid': 1, 'word_id': 22, 'result': True, 'perf': 1600},
        ]
    )
    execute(
        mysql_app,
        "INSERT INTO game (id, ownerid, dictid, users, wordlist, result, status) VALUES (2, 1, 1, '[2, 1]', '[11, 22, 33]', %s, 0)",
        (second_answers,),
    )
    results = parallel(mysql_app, lambda: game.end_game(1, 1), lambda: game.end_game(2, 1))
    assert all(isinstance(result, dict) for result in results)
    user = query(mysql_app, 'SELECT rating, ratinghistory FROM user WHERE id = 1')[0]
    first = 1500 + rating_delta(1500, 1600)
    assert user['rating'] == first + rating_delta(first, 1600)
    assert len(rating_history(mysql_app, 1)) == 2


def test_legacy_missing_perf_returns_conflict_without_modifying_data(mysql_app, mysql_login):
    execute(
        mysql_app,
        'UPDATE game SET result = %s WHERE id = 1',
        ('[{"uid": 1, "word_id": 11, "result": true}]',),
    )
    client, _ = mysql_login()
    response = client.post('/api/game/1/end', json={})
    assert response.status_code == 409
    assert response.json['code'] == 'legacy_data_error'
    assert (
        query(mysql_app, 'SELECT ratinghistory FROM user WHERE id = 1')[0]['ratinghistory'] is None
    )


def test_start_permissions_and_finished_answer(mysql_app, mysql_login):
    execute(mysql_app, 'UPDATE game SET status = -1 WHERE id = 1')
    client, _ = mysql_login(1)
    second, _ = mysql_login(2)
    assert second.post('/api/game/1/start', json={'uid': 1}).status_code == 403
    assert client.post('/api/game/1/start', json={}).status_code == 200
    assert client.post('/api/game/1/start', json={}).status_code == 409
    assert client.post('/api/game/1/end', json={}).status_code == 200
    assert (
        client.post('/api/game/1/answer', json={'word_id': 11, 'answer': 'apple'}).status_code
        == 409
    )
