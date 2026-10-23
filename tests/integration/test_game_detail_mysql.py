"""Real MySQL/HTTP read contracts for the Vue history page, not browser stubs."""

import json

import pytest

from wm_app.services import game

from .test_game_mysql import execute, query

pytestmark = pytest.mark.mysql


def test_current_name_rating_is_shared_by_lobby_and_game_without_exposing_private_fields(
    mysql_app, mysql_login
):
    client, _ = mysql_login()
    execute(mysql_app, 'UPDATE user SET rating = 2400 WHERE id = 1')
    for deleted in (0, 1, None):
        for rating in (None, 0, -1, 1600):
            execute(
                mysql_app,
                'UPDATE user SET rating = %s, deleted = %s WHERE id = 2',
                (rating, deleted),
            )
            before = {
                table: query(mysql_app, f'SELECT * FROM `{table}` ORDER BY id')
                for table in ('user', 'game', 'game_rating')
            }
            state = client.get('/api/game/1').json['game']
            lobby = client.get('/api/game/list').json['games'][0]
            for view in (state, lobby):
                assert view['owner'] == {'id': 1, 'username': 'user1', 'rating': 2400}
                assert view['users'][0] == view['owner']
                assert view['users'][1] == {
                    'id': 2,
                    'username': 'user2',
                    'rating': rating if deleted == 0 else None,
                }
            assert before == {
                table: query(mysql_app, f'SELECT * FROM `{table}` ORDER BY id') for table in before
            }


def test_history_shell_guard_and_saved_game_rating_survive_later_settlement(
    mysql_app, mysql_login, monkeypatch
):
    monkeypatch.setattr(game.random, 'shuffle', lambda values: None)
    client, _ = mysql_login()
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        game.join_game(gid, 2)
        game.start_game(gid, 1)
        game.answer_game(gid, 1, 11, 'apple')
        game.end_game(gid, 2)
    rating = query(
        mysql_app, 'SELECT delta, rating_after FROM game_rating WHERE game_id = %s', (gid,)
    )[0]
    before = client.get(f'/api/game/{gid}').json['game']
    assert before['question_source'] == 'snapshot' and before['status'] == 1
    assert before['current_index'] == 1 and before['total_words'] == 3
    assert before['next_word'] is before['next_turn'] is None
    assert 'english' in before['words'][0] and all(
        'english' not in word for word in before['words'][1:]
    )
    assert before['userrating'][0]['ratinghistory'] == [
        {'game_id': gid, 'delta': rating['delta'], 'new_rating': rating['rating_after']}
    ]
    assert before['userrating'][1]['ratinghistory'] == []
    assert before['users'][0]['rating'] == rating['rating_after']
    path = f'/game/{gid}/detail/'
    shell = client.get(path)
    assert shell.status_code == 200 and '<div id="app">' in shell.text
    assert '/static/js/game-detail.js' not in shell.text
    assert shell.headers['Cache-Control'] == 'no-store'
    anonymous = mysql_app.test_client()
    assert anonymous.get(path).status_code == 302
    assert anonymous.get(f'/api/game/{gid}').status_code == 401
    with mysql_app.app_context():
        later = game.create_game(1, 1)['game_id']
        game.join_game(later, 2)
        game.start_game(later, 1)
        game.answer_game(later, 1, 11, 'wrong')
        game.end_game(later, 1)
    after = client.get(f'/api/game/{gid}').json['game']
    assert after['version'] == before['version']
    assert after['result'] == before['result']
    assert after['userrating'][0]['ratinghistory'][0] == before['userrating'][0]['ratinghistory'][0]
    assert after['userrating'][0]['ratinghistory'][-1]['game_id'] == later
    assert (
        after['users'][0]['rating']
        == query(mysql_app, 'SELECT rating FROM user WHERE id = 1')[0]['rating']
    )
    assert after['owner']['rating'] == after['users'][0]['rating']
    assert after['users'][0]['rating'] != before['users'][0]['rating']
    assert client.get('/api/game/2147483647').status_code == 404
    reader, _ = mysql_login(2)
    execute(mysql_app, 'UPDATE user SET deleted = 1 WHERE id = 1')
    masked = reader.get(f'/api/game/{gid}').json['game']
    assert masked['owner']['rating'] is masked['users'][0]['rating'] is None
    assert masked['userrating'] == after['userrating']
    assert masked['result'] == after['result']
    assert masked['version'] == after['version']


def test_legacy_missing_fields_and_user_references_remain_visible_without_read_repair(
    mysql_app, mysql_login
):
    raw = ' [{"uid":1,"word_id":33,"answer":null,"perf":null}] '
    execute(mysql_app, 'UPDATE game SET result = %s, status = 1 WHERE id = 1', (raw,))
    execute(mysql_app, 'DELETE FROM user WHERE id = 2')
    client, _ = mysql_login()
    before = query(mysql_app, 'SELECT * FROM game WHERE id = 1')
    response = client.get('/api/game/1')
    assert response.status_code == 200
    state = response.json['game']
    assert state['question_source'] == 'legacy_live'
    assert state['result'] == json.loads(raw)
    assert 'result' not in state['result'][0] and 'rating_version' not in state['result'][0]
    assert [user['id'] for user in state['users']] == [1]
    assert set(state['perf']) == {
        '1',
        '2',
    }  # Missing user info must not silently erase its summary ID.
    assert state['perf']['1']['perf'] is None
    assert 'english' in state['words'][0] and all(
        'english' not in word for word in state['words'][1:]
    )
    assert query(mysql_app, 'SELECT * FROM game WHERE id = 1') == before
    assert not query(mysql_app, 'SELECT * FROM game_rating')
