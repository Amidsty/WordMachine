import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, inspect, text

from wm_app import socketio
from wm_app.db import reading, transaction
from wm_app.services import auth
from wm_app.services.errors import ApiError

pytestmark = pytest.mark.mysql


def query(app, sql, params=()):
    with app.app_context(), reading() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def execute(app, sql, params=()):
    with app.app_context(), transaction() as cursor:
        cursor.execute(sql, params)


def test_legacy_login_upgrades_hash_and_never_stores_raw_session(mysql_app, mysql_login):
    old = query(mysql_app, 'SELECT pwhash FROM user WHERE id = 1')[0]['pwhash']
    assert old == hashlib.sha256(b'test-password').hexdigest()
    client, csrf = mysql_login(1)
    user = query(mysql_app, 'SELECT pwhash FROM user WHERE id = 1')[0]
    assert user['pwhash'].startswith('scrypt:32768:8:1$')
    token = client.get_cookie('wm_session').value
    row = query(mysql_app, 'SELECT token_hash, csrf_token FROM auth_session WHERE user_id = 1')[0]
    assert row['token_hash'] == auth.token_digest(token) and row['token_hash'] != token
    assert row['csrf_token'] == csrf
    data = client.get('/api/session').json
    assert data['user']['id'] == 1 and 'pwhash' not in data['user']
    assert 'token_hash' not in data and 'token' not in data


def test_registration_sets_role_and_enforces_unique_username(mysql_app):
    client = mysql_app.test_client()
    csrf = client.get('/api/session').json['csrf_token']
    client.environ_base['HTTP_X_CSRF_TOKEN'] = csrf
    response = client.post(
        '/api/register', json={'username': 'new-user', 'password': ' secret ', 'type': 'root'}
    )
    assert response.status_code == 201
    row = query(mysql_app, 'SELECT type, pwhash FROM user WHERE id = %s', (response.json['uid'],))[
        0
    ]
    assert row['type'] == 'normal' and row['pwhash'].startswith('scrypt:')
    assert (
        client.post(
            '/api/register', json={'username': 'NEW-USER', 'password': 'secret'}
        ).status_code
        == 409
    )
    assert (
        client.post('/api/login', json={'username': 'new-user', 'password': 'secret'}).status_code
        == 401
    )
    assert (
        client.post('/api/login', json={'username': 'new-user', 'password': ' secret '}).status_code
        == 200
    )


def test_concurrent_registration_cannot_duplicate_accounts(mysql_app):
    barrier = threading.Barrier(2)

    def register():
        with mysql_app.app_context():
            barrier.wait(timeout=10)
            try:
                auth.create_user('same-name', 'secret')
                return 201
            except ApiError as error:
                return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: register(), range(2)))
    assert sorted(results) == [201, 409]
    assert (
        query(mysql_app, 'SELECT COUNT(*) AS n FROM user WHERE username = %s', ('same-name',))[0][
            'n'
        ]
        == 1
    )


def test_logout_revokes_current_session_and_socket_only(mysql_app, mysql_login):
    client, csrf = mysql_login(1)
    other, _ = mysql_login(1)
    stolen_token = client.get_cookie('wm_session').value
    socket = socketio.test_client(mysql_app, flask_test_client=client, auth={'csrf_token': csrf})
    assert socket.is_connected()
    assert client.post('/api/logout', json={}).status_code == 200
    assert not socket.is_connected()
    assert other.get('/api/game/list').status_code == 200
    replay = mysql_app.test_client()
    replay.set_cookie('wm_session', stolen_token)
    assert replay.get('/api/game/list').status_code == 401


def test_password_change_revokes_every_session(mysql_app, mysql_login):
    client, _ = mysql_login(1)
    other, _ = mysql_login(1)
    assert client.post('/api/user/2/update', json={'introduction': 'forged'}).status_code == 403
    assert (
        client.post(
            '/api/user/1/update', json={'new_password': 'new-secret', 'current_password': 'wrong'}
        ).status_code
        == 401
    )
    assert other.get('/api/game/list').status_code == 200
    response = client.post(
        '/api/user/1/update',
        json={'new_password': 'new-secret', 'current_password': 'test-password'},
    )
    assert response.status_code == 200 and response.json['reauthenticate'] is True
    assert not query(mysql_app, 'SELECT * FROM auth_session WHERE user_id = 1')
    assert other.get('/api/game/list').status_code == 401
    fresh, _ = mysql_login(1, 'new-secret')
    assert fresh.get('/api/game/list').status_code == 200


def test_admin_ban_restore_and_reset_revoke_sessions(mysql_app, mysql_login):
    user, _ = mysql_login(1)
    admin, _ = mysql_login(3)
    assert user.post('/api/admin/user/2/delete', json={}).status_code == 403
    assert admin.post('/api/admin/user/3/delete', json={}).status_code == 400
    assert admin.post('/api/admin/user/1/delete', json={}).status_code == 200
    assert user.get('/api/game/list').status_code == 401
    assert admin.post('/api/admin/user/1/restore', json={}).status_code == 200
    assert user.get('/api/game/list').status_code == 401  # Restoration never revives old tokens.
    user, _ = mysql_login(1)
    assert (
        admin.post(
            '/api/admin/user/1/reset-password', json={'new_password': 'reset-secret'}
        ).status_code
        == 200
    )
    assert user.get('/api/game/list').status_code == 401
    fresh, _ = mysql_login(1, 'reset-secret')
    assert fresh.get('/api/game/list').status_code == 200


def test_expiry_and_csrf_rotation(mysql_app, mysql_login):
    client = mysql_app.test_client()
    old_csrf = client.get('/api/session').json['csrf_token']
    response = client.post(
        '/api/login',
        json={'username': 'user1', 'password': 'test-password'},
        headers={'X-CSRF-Token': old_csrf},
    )
    assert response.status_code == 200
    new_csrf = response.json['csrf_token']
    assert new_csrf != old_csrf
    assert (
        client.post(
            '/api/dict', json={'dictname': 'bad'}, headers={'X-CSRF-Token': old_csrf}
        ).status_code
        == 403
    )
    assert (
        client.post(
            '/api/dict', json={'dictname': 'good'}, headers={'X-CSRF-Token': new_csrf}
        ).status_code
        == 201
    )
    execute(mysql_app, "UPDATE auth_session SET expires_at = '2000-01-01' WHERE user_id = 1")
    assert client.get('/api/game/list').status_code == 401


def test_account_limit_uses_database_collation_and_persists(mysql_app):
    mysql_app.config.update(LOGIN_ACCOUNT_LIMIT=2, LOGIN_IP_LIMIT=100)
    client = mysql_app.test_client()
    csrf = client.get('/api/session').json['csrf_token']
    headers = {'X-CSRF-Token': csrf}
    assert (
        client.post(
            '/api/login', json={'username': 'user1', 'password': 'wrong'}, headers=headers
        ).status_code
        == 401
    )
    assert (
        client.post(
            '/api/login', json={'username': 'USER1', 'password': 'wrong'}, headers=headers
        ).status_code
        == 401
    )
    blocked = client.post(
        '/api/login', json={'username': 'user1', 'password': 'test-password'}, headers=headers
    )
    assert blocked.status_code == 429 and int(blocked.headers['Retry-After']) > 0
    execute(mysql_app, "UPDATE auth_rate_limit SET window_started = '2000-01-01'")
    assert (
        client.post(
            '/api/login', json={'username': 'user1', 'password': 'test-password'}, headers=headers
        ).status_code
        == 200
    )


def test_dictionary_ownership_and_csv_atomicity(mysql_app, mysql_login):
    owner, _ = mysql_login(1)
    stranger, _ = mysql_login(2)
    admin, _ = mysql_login(3)
    assert owner.put('/api/dict/1', json={'dictname': 'system'}).status_code == 403
    assert admin.put('/api/dict/1', json={'dictname': 'system'}).status_code == 200
    forged = owner.post('/api/dict', json={'dictname': 'owned', 'ownerid': 2})
    assert forged.status_code == 400
    created = owner.post('/api/dict', json={'dictname': 'owned'})
    assert created.status_code == 201
    did = created.json['dict_id']
    assert query(mysql_app, 'SELECT ownerid FROM dict WHERE id = %s', (did,))[0]['ownerid'] == 1
    assert stranger.get(f'/api/dict/{did}/words').status_code == 200
    for method, path, body in [
        ('put', f'/api/dict/{did}', {'dictname': 'stolen'}),
        ('delete', f'/api/dict/{did}', {}),
        ('post', f'/api/dict/{did}/word', {'english': 'bad', 'chinese': '坏'}),
        ('post', f'/api/dict/{did}/import-csv', {'csv': 'bad,坏'}),
    ]:
        assert getattr(stranger, method)(path, json=body).status_code == 403
    failed = owner.post(f'/api/dict/{did}/import-csv', json={'csv': 'apple,苹果\nbad'})
    assert failed.status_code == 400 and failed.json['details']['errors'][0]['line'] == 2
    assert not owner.get(f'/api/dict/{did}/words').json['words']
    content = '\ufeff"say ""hi"", please","第一行\n第二行"\r\napple,苹果\r\n'
    imported = owner.post(f'/api/dict/{did}/import-csv', json={'csv': content})
    assert imported.status_code == 200 and imported.json['count'] == 2
    wid = owner.get(f'/api/dict/{did}/words').json['words'][0]['id']
    assert (
        stranger.put(f'/api/word/{wid}', json={'english': 'bad', 'chinese': '坏'}).status_code
        == 403
    )
    assert stranger.delete(f'/api/word/{wid}', json={}).status_code == 403
    assert admin.put(f'/api/word/{wid}', json={'english': 'ok', 'chinese': '好'}).status_code == 200
    assert stranger.get(f'/api/dict/{did}/export-csv').json['content'].startswith('ok,好')
    assert owner.delete(f'/api/dict/{did}', json={}).status_code == 200
    assert all(
        row['deleted'] == 1
        for row in query(mysql_app, 'SELECT deleted FROM word WHERE dictid = %s', (did,))
    )


def test_migration_adopts_legacy_without_rewriting_users_or_games(
    legacy_database, migrate_database
):
    engine = create_engine(legacy_database['url'])
    try:
        with engine.connect() as connection:
            before = [
                dict(row) for row in connection.execute(text('SELECT * FROM game')).mappings()
            ]
            password = connection.execute(text('SELECT pwhash FROM user WHERE id = 1')).scalar_one()
        migrate_database(legacy_database)
        with engine.connect() as connection:
            after = [dict(row) for row in connection.execute(text('SELECT * FROM game')).mappings()]
            assert all(row.pop('version') == 0 for row in after)
            assert all(
                row.pop('question_mode') == 0 and row.pop('dictname_snapshot') is None
                for row in after
            )
            assert all(
                row.pop('participant_mode') == 0 and row.pop('participant_count') is None
                for row in after
            )
            assert all(
                row.pop('answer_mode') == 0 and row.pop('answer_count') is None for row in after
            )
            assert all(row.pop('settlement_mode') == 0 for row in after)
            assert all(
                row.pop('perf_mode') == 0 and row.pop('multiplier_snapshot') is None
                for row in after
            )
            assert after == before
            assert (
                connection.execute(text('SELECT pwhash FROM user WHERE id = 1')).scalar_one()
                == password
            )
            assert (
                connection.execute(text('SELECT ownerid FROM dict WHERE id = 1')).scalar_one()
                is None
            )
            assert (
                connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0012_manual_rating'
            )
    finally:
        engine.dispose()


def test_migration_rejects_duplicate_usernames_before_auth_ddl(legacy_database, migrate_database):
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO user (username, rating, type, deleted) VALUES ('USER1', 0, 'normal', 0)"
                )
            )
        with pytest.raises(RuntimeError, match='Duplicate usernames'):
            migrate_database(legacy_database)
        inspector = inspect(engine)
        assert 'auth_session' not in inspector.get_table_names()
        assert 'ownerid' not in {column['name'] for column in inspector.get_columns('dict')}
        with engine.connect() as connection:
            assert connection.execute(text('SELECT COUNT(*) FROM user')).scalar_one() == 4
    finally:
        engine.dispose()


def test_explicit_migration_can_initialize_an_empty_test_database(
    legacy_database, migrate_database
):
    assert legacy_database['url'].database.startswith('wm_test_')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as connection:
            for table in ('game', 'word', 'dict', 'user'):
                connection.execute(text(f'DROP TABLE `{table}`'))
        migrate_database(legacy_database)
        assert {'user', 'dict', 'word', 'game', 'auth_session', 'auth_rate_limit'} <= set(
            inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()
