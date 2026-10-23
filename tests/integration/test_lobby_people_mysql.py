import pytest

from wm_app.db import transaction

pytestmark = pytest.mark.mysql


def test_lobby_pagination_active_lookup_and_summary_privacy(mysql_app, mysql_login):
    client, _ = mysql_login(1)
    with mysql_app.app_context(), transaction() as cursor:
        for _ in range(22):
            cursor.execute(
                'INSERT INTO game (ownerid, dictid, users, wordlist, result, status) VALUES (2, 1, %s, %s, %s, -1)',
                ('[2]', '[11]', '[]'),
            )
    data = client.get('/api/game/list?status=waiting&per_page=20').json
    assert len(data['games']) == 20 and data['pagination']['total'] == 22
    assert data['active_game_id'] == 1  # Seeded running game, absent from this filtered page.
    assert data['games'][0]['actions']['join'] is True
    assert not {'wordlist', 'result', 'ratingdelta', 'perf'}.intersection(data['games'][0])
    last = client.get('/api/game/list?status=waiting&per_page=20&page=99').json
    assert len(last['games']) == 2 and last['pagination']['page'] == 2
    assert client.get('/api/game/list?status=finished').json['games'] == []
    assert (
        client.get('/api/game/list', query_string={'q': '%', 'status': 'waiting'}).json['games']
        == []
    )


def test_lobby_active_membership_is_numeric_and_invalid_data_is_not_repaired(
    mysql_app, mysql_login
):
    client, _ = mysql_login(1)
    with mysql_app.app_context(), transaction() as cursor:
        cursor.execute('UPDATE game SET users = %s WHERE id = 1', ('[11, 2]',))
    assert client.get('/api/game/list').json['active_game_id'] is None
    with mysql_app.app_context(), transaction() as cursor:
        cursor.execute(
            'INSERT INTO game (ownerid, dictid, users, wordlist, result, status) VALUES (2, 1, %s, %s, %s, 0)',
            ('broken-json', '[11]', '[]'),
        )
    # Invalid unrelated JSON cannot establish membership. Viewing that row requests review.
    assert client.get('/api/game/list?status=waiting').status_code == 200
    response = client.get('/api/game/list?status=running')
    assert response.status_code == 409 and response.json['code'] == 'legacy_data_error'


def test_lobby_actions_still_use_game_service(mysql_app, mysql_login):
    owner, _ = mysql_login(1)
    other, _ = mysql_login(2)
    game_id = owner.post('/api/game/create', json={'dict_id': 1}).json['game_id']
    assert other.post(f'/api/game/{game_id}/start', json={}).status_code == 403
    assert other.post(f'/api/game/{game_id}/join', json={}).status_code == 200
    assert owner.get('/api/game/list?status=waiting').json['games'][0]['actions']['start']
    assert owner.post(f'/api/game/{game_id}/cancel', json={}).status_code == 200
    cancelled = owner.get('/api/game/list?status=cancelled').json['games'][0]
    assert cancelled['id'] == game_id and not any(cancelled['actions'].values())


def test_public_leaderboard_pagination_keeps_top_100_and_null_ratings(mysql_app):
    with mysql_app.app_context(), transaction() as cursor:
        for uid in range(4, 106):
            cursor.execute(
                'INSERT INTO user (id, username, pwhash, rating, deleted) VALUES (%s, %s, %s, 1500, 0)',
                (uid, f'leader{uid}', 'unused-test-only'),
            )
        cursor.execute('UPDATE user SET deleted = 1 WHERE id = 2')
        cursor.execute('UPDATE user SET rating = NULL WHERE id = 105')
    client = mysql_app.test_client()
    first = client.get('/api/leaderboard?per_page=60').json
    assert first['pagination']['total'] == 100
    assert [row['id'] for row in first['users'][:3]] == [1, 3, 4]
    last = client.get('/api/leaderboard?per_page=60&page=2').json
    assert len(last['users']) == 40 and last['users'][-1]['rank'] == 100
    assert all(
        set(row) == {'id', 'username', 'introduction', 'rating', 'rank'} for row in last['users']
    )
    assert client.get('/api/user/2').status_code == 404
    assert client.get('/api/user/105').json['user']['rating'] is None
    assert client.get('/user/2/').status_code == 404
