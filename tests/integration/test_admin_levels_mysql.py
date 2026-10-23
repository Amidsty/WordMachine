import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import inspect

from tests.integration.test_auth_dict_mysql import execute, query
from wm_app import socketio
from wm_app.security.permissions import can_manage_dictionary
from wm_app.services import auth
from wm_app.services.admin_policy import generate_master_password, master_password
from wm_app.services.errors import ApiError

pytestmark = pytest.mark.mysql


def rank(app, uid, value):
    execute(
        app,
        'UPDATE user SET admin_level = %s, type = %s WHERE id = %s',
        (value, 'root' if value else 'normal', uid),
    )


@pytest.mark.parametrize(
    'actor_level,target_level,allowed',
    [
        (1, 0, True),
        (2, 1, True),
        (4, 3, True),
        (5, 4, True),
        (2, 2, False),
        (2, 3, False),
        (4, 5, False),
        (0, 0, False),
    ],
)
def test_strict_hierarchy_for_all_user_mutations(
    mysql_app, mysql_login, actor_level, target_level, allowed
):
    rank(mysql_app, 3, actor_level)
    rank(mysql_app, 1, target_level)
    actor, _ = mysql_login(3)
    for action, body in [
        ('update', {'introduction': 'reviewed'}),
        ('reset-password', {'new_password': 'new-test-password'}),
        ('delete', {}),
        ('restore', {}),
    ]:
        response = actor.post(f'/api/admin/user/1/{action}', json=body)
        assert response.status_code == (200 if allowed else 403), (action, response.json)
    rows = query(mysql_app, 'SELECT * FROM admin_audit WHERE actor_id = 3')
    assert len(rows) == (4 if allowed else 0)
    assert 'pwhash' not in str(rows) and 'new-test-password' not in str(rows)


def test_self_profile_allowed_but_self_privilege_and_status_changes_denied(mysql_app, mysql_login):
    actor, _ = mysql_login(3)
    for action in ('delete', 'restore', 'reset-password'):
        assert actor.post(
            f'/api/admin/user/3/{action}', json={'new_password': 'new-secret'}
        ).status_code in (400, 403)
    assert (
        actor.post(
            '/api/admin/user/3/level',
            json={'admin_level': 4, 'expected_version': 0, 'reason': 'self'},
        ).status_code
        == 403
    )
    assert (
        actor.post('/api/admin/user/3/update', json={'introduction': 'my information'}).status_code
        == 200
    )
    assert not actor.get('/api/session').json['authenticated']
    assert query(mysql_app, 'SELECT admin_level, introduction FROM user WHERE id = 3')[0] == {
        'admin_level': 5,
        'introduction': 'my information',
    }


def test_level_change_rechecks_bounds_version_and_revokes_all_target_sessions(
    mysql_app, mysql_login
):
    actor, _ = mysql_login(3)
    target, csrf = mysql_login(1)
    other, _ = mysql_login(1)
    connection = socketio.test_client(
        mysql_app, flask_test_client=target, auth={'csrf_token': csrf}
    )
    body = {'admin_level': 4, 'expected_version': 0, 'reason': 'approved assignment'}
    response = actor.post('/api/admin/user/1/level', json=body)
    assert response.status_code == 200 and response.json['admin_version'] == 1
    assert not connection.is_connected()
    assert not target.get('/api/session').json['authenticated']
    assert not other.get('/api/session').json['authenticated']
    again = actor.post('/api/admin/user/1/level', json=body)
    assert again.status_code == 409 and again.json['code'] == 'stale_admin_version'
    assert (
        actor.post(
            '/api/admin/user/1/level', json={**body, 'admin_level': 5, 'expected_version': 1}
        ).status_code
        == 403
    )
    result = actor.get('/api/admin/users').json
    user = next(row for row in result['users'] if row['id'] == 1)
    assert user['type'] == 'root' and user['admin_level'] == 4
    assert user['capabilities']['can_edit_profile'] and user['capabilities']['can_adjust_rating']
    record = query(mysql_app, "SELECT * FROM admin_audit WHERE action = 'set-level'")[0]
    assert json.loads(record['before_data'])['admin_level'] == 0
    assert json.loads(record['after_data'])['admin_level'] == 4
    assert record['actor_level'] == 5 and record['reason'] == body['reason']


@pytest.mark.parametrize('bad', [True, -1, 6, '4', None, 1.5])
def test_invalid_levels_are_not_coerced(mysql_app, mysql_login, bad):
    actor, _ = mysql_login(3)
    assert (
        actor.post(
            '/api/admin/user/1/level',
            json={'admin_level': bad, 'expected_version': 0, 'reason': 'bad'},
        ).status_code
        == 400
    )
    assert query(mysql_app, 'SELECT admin_level FROM user WHERE id = 1')[0]['admin_level'] == 0


@pytest.mark.parametrize('level', [1, 2, 3, 4, 5])
def test_only_level_five_can_modify_another_personal_dictionary(mysql_app, mysql_login, level):
    rank(mysql_app, 3, level)
    owner, _ = mysql_login(1)
    actor, _ = mysql_login(3)
    did = owner.post('/api/dict', json={'dictname': 'owned'}).json['dict_id']
    assert owner.put(f'/api/dict/{did}', json={'dictname': 'own edit'}).status_code == 200
    response = actor.put(f'/api/dict/{did}', json={'dictname': 'administrator edit'})
    assert response.status_code == (200 if level == 5 else 403)
    assert actor.get(f'/api/dict/{did}').json['dict']['can_manage'] == (level == 5)
    assert can_manage_dictionary({'id': 3, 'admin_level': level}, {'ownerid': None}) == (level >= 3)


def test_rating_threshold_ignores_rating_and_profile_cannot_bypass_review(mysql_app, mysql_login):
    rank(mysql_app, 3, 4)
    execute(mysql_app, 'UPDATE user SET rating = -200 WHERE id = 3')
    actor, _ = mysql_login(3)
    users = actor.get('/api/admin/users').json['users']
    assert all(row['capabilities']['meets_rating_threshold'] for row in users)
    assert all(row['capabilities']['can_adjust_rating'] for row in users)
    assert actor.post('/api/admin/user/3/update', json={'rating': 9999}).status_code == 400
    assert actor.post('/api/admin/user/1/rating', json={'rating': 9999}).status_code == 400
    rank(mysql_app, 3, 3)
    execute(mysql_app, 'UPDATE user SET rating = 9999 WHERE id = 3')
    assert not any(
        row['capabilities']['meets_rating_threshold']
        for row in actor.get('/api/admin/users').json['users']
    )


def test_master_is_explicit_strong_and_never_adopts_an_existing_account(mysql_app):
    with mysql_app.app_context():
        with pytest.raises(ApiError):
            auth.create_user('MASTER', 'short', role='root', level=5)
        with pytest.raises(ApiError):
            auth.create_user('master', 'ordinary-password')
        secret = generate_master_password()
        assert len(secret) == 24 and master_password(secret) == secret
        created = auth.create_user('MASTER', secret, role='root', level=5)
        before = query(mysql_app, 'SELECT * FROM user WHERE id = %s', (created['id'],))
        with pytest.raises(ApiError) as duplicate:
            auth.create_user('MASTER', generate_master_password(), role='root', level=5)
        assert duplicate.value.code == 'username_exists'
        assert query(mysql_app, 'SELECT * FROM user WHERE id = %s', (created['id'],)) == before
    client = mysql_app.test_client()
    csrf = client.get('/api/session').json['csrf_token']
    login = client.post(
        '/api/login',
        json={'username': 'MASTER', 'password': secret},
        headers={'X-CSRF-Token': csrf},
    )
    client.environ_base['HTTP_X_CSRF_TOKEN'] = login.json['csrf_token']
    assert login.json['user']['admin_level'] == 5
    assert (
        client.post(
            f'/api/user/{created["id"]}/update',
            json={'current_password': secret, 'new_password': 'weak-password'},
        ).status_code
        == 400
    )
    assert (
        client.post(
            f'/api/admin/user/{created["id"]}/update', json={'username': 'renamed-master'}
        ).status_code
        == 400
    )


def test_competing_level_changes_are_serialized_and_one_review_version_wins(mysql_app):
    barrier = Barrier(2)

    def change(value):
        with mysql_app.app_context():
            barrier.wait(timeout=5)
            try:
                auth.set_admin_level(
                    3,
                    1,
                    {'admin_level': value, 'expected_version': 0, 'reason': 'concurrency test'},
                )
                return 200
            except ApiError as error:
                return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(change, (1, 2)))
    assert sorted(results) == [200, 409]
    assert len(query(mysql_app, "SELECT id FROM admin_audit WHERE action = 'set-level'")) == 1


def test_audit_failure_rolls_back_level_and_session_revocation(mysql_app, mysql_login, monkeypatch):
    target, _ = mysql_login(1)
    before = query(mysql_app, 'SELECT * FROM user WHERE id = 1')

    def fail(*args, **kwargs):
        raise RuntimeError('injected audit failure')

    monkeypatch.setattr(auth, 'audit', fail)
    with mysql_app.app_context(), pytest.raises(RuntimeError, match='injected audit'):
        auth.set_admin_level(3, 1, {'admin_level': 1, 'expected_version': 0, 'reason': 'test'})
    assert query(mysql_app, 'SELECT * FROM user WHERE id = 1') == before
    assert target.get('/api/session').json['authenticated']


def test_actor_demotion_after_http_authentication_is_rechecked_in_transaction(
    mysql_app, mysql_login, monkeypatch
):
    actor, _ = mysql_login(3)
    original = auth.set_admin_level

    def demote(*args):
        rank(mysql_app, 3, 0)
        return original(*args)

    monkeypatch.setattr(auth, 'set_admin_level', demote)
    response = actor.post(
        '/api/admin/user/1/level', json={'admin_level': 1, 'expected_version': 0, 'reason': 'test'}
    )
    assert response.status_code == 403
    assert query(mysql_app, 'SELECT admin_level FROM user WHERE id = 1')[0]['admin_level'] == 0


def test_migration_requires_review_before_ddl_and_refuses_partial_schema(
    legacy_database, migrate_database
):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    migrate_database(legacy_database, '0008_list_indexes')
    engine = create_engine(legacy_database['url'])
    try:
        with engine.begin() as connection:
            config = Config('alembic.ini')
            config.attributes['connection'] = connection
            config.attributes['admin_levels'] = {}
            with pytest.raises(RuntimeError, match='exact reviewed mapping'):
                command.upgrade(config, 'head')
            assert 'admin_level' not in {c['name'] for c in inspect(connection).get_columns('user')}
            assert (
                connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
                == '0008_list_indexes'
            )
            connection.execute(text('ALTER TABLE user ADD COLUMN admin_level INT NULL'))
            config.attributes['admin_levels'] = {'3': 5}
            with pytest.raises(RuntimeError, match='Partial/custom'):
                command.upgrade(config, 'head')
    finally:
        engine.dispose()
