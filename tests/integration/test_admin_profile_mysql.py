import pytest

from tests.integration.test_auth_dict_mysql import execute, query
from wm_app import socketio
from wm_app.services import auth
from wm_app.services.errors import ApiError

pytestmark = pytest.mark.mysql


def test_admin_edits_profile_revokes_sessions_and_preserves_other_facts(mysql_app, mysql_login):
    admin, _ = mysql_login(3)
    target, csrf = mysql_login(1)
    other_session, _ = mysql_login(1)
    socket = socketio.test_client(mysql_app, flask_test_client=target, auth={'csrf_token': csrf})
    before = query(mysql_app, 'SELECT * FROM user WHERE id = 1')[0]
    games = query(mysql_app, 'SELECT * FROM game')
    dictionaries = query(mysql_app, 'SELECT * FROM dict')
    try:
        result = admin.post(
            '/api/admin/user/1/update', json={'username': ' renamed ', 'introduction': ' 新简介 '}
        )
        assert result.status_code == 200, result.json
        after = query(mysql_app, 'SELECT * FROM user WHERE id = 1')[0]
        assert after == {**before, 'username': 'renamed', 'introduction': '新简介'}
        assert query(mysql_app, 'SELECT * FROM game') == games
        assert query(mysql_app, 'SELECT * FROM dict') == dictionaries
        assert not query(mysql_app, 'SELECT * FROM auth_session WHERE user_id = 1')
        assert not target.get('/api/session').json['authenticated']
        assert not other_session.get('/api/session').json['authenticated']
        assert not socket.is_connected()
        assert admin.get('/api/session').json['authenticated']
        login = target.post(
            '/api/login',
            json={'username': 'renamed', 'password': 'test-password'},
            headers={'X-CSRF-Token': target.get('/api/session').json['csrf_token']},
        )
        assert login.status_code == 200 and login.json['user']['id'] == 1
    finally:
        if socket.is_connected():
            socket.disconnect()


def test_duplicate_name_uses_mysql_collation_and_rolls_back_without_revoking(
    mysql_app, mysql_login
):
    admin, _ = mysql_login(3)
    target, _ = mysql_login(1)
    before = query(mysql_app, 'SELECT * FROM user WHERE id = 1')
    response = admin.post(
        '/api/admin/user/1/update', json={'username': 'USER2', 'introduction': 'must roll back'}
    )
    assert response.status_code == 409 and response.json['code'] == 'username_exists'
    assert query(mysql_app, 'SELECT * FROM user WHERE id = 1') == before
    assert target.get('/api/session').json['authenticated']


@pytest.mark.parametrize('field', ['rating', 'type', 'deleted', 'pwhash', 'uid', 'gamehistory'])
def test_protected_fields_reject_entire_update(mysql_app, mysql_login, field):
    admin, _ = mysql_login(3)
    before = query(mysql_app, 'SELECT * FROM user WHERE id = 1')
    response = admin.post(
        '/api/admin/user/1/update', json={'username': 'should-not-save', field: 'forged'}
    )
    assert response.status_code == 400
    assert query(mysql_app, 'SELECT * FROM user WHERE id = 1') == before


def test_access_csrf_and_root_targets_are_denied(mysql_app, mysql_login):
    normal, _ = mysql_login(1)
    admin, _ = mysql_login(3)
    path = '/api/admin/user/2/update'
    body = {'introduction': 'not allowed'}
    before = query(mysql_app, 'SELECT * FROM user ORDER BY id')
    assert mysql_app.test_client().post(path, json=body).status_code == 401
    assert normal.post(path, json=body).status_code == 403
    assert admin.post(path, json=body, headers={'X-CSRF-Token': 'bad'}).status_code == 403
    assert (
        admin.post(path, json=body, headers={'Origin': 'https://foreign.invalid'}).status_code
        == 403
    )
    assert query(mysql_app, 'SELECT * FROM user ORDER BY id') == before
    execute(mysql_app, "UPDATE user SET type = 'root', admin_level = 5 WHERE id = 2")
    assert admin.post(path, json=body).status_code == 403
    assert admin.post('/api/admin/user/999/update', json=body).status_code == 404


def test_service_rechecks_actor_and_supports_banned_normal_user_without_restoring(
    mysql_app, mysql_login
):
    admin, _ = mysql_login(3)
    execute(mysql_app, "UPDATE user SET username = 'x', deleted = 1 WHERE id = 1")
    response = admin.post('/api/admin/user/1/update', json={'username': 'x', 'introduction': ''})
    assert response.status_code == 200
    row = query(mysql_app, 'SELECT * FROM user WHERE id = 1')[0]
    assert row['deleted'] == 1 and row['username'] == 'x' and row['introduction'] == ''
    assert admin.post('/api/admin/user/1/update', json={'username': 'y'}).status_code == 400
    execute(mysql_app, "UPDATE user SET type = 'normal', admin_level = 0 WHERE id = 3")
    with mysql_app.app_context(), pytest.raises(ApiError) as denied:
        auth.admin_update_user(3, 1, {'introduction': 'blocked'})
    assert denied.value.status == 403
    execute(mysql_app, "UPDATE user SET type = 'root', admin_level = 5, deleted = 1 WHERE id = 3")
    with mysql_app.app_context(), pytest.raises(ApiError) as banned:
        auth.admin_update_user(3, 1, {'introduction': 'blocked'})
    assert banned.value.status == 401
    assert query(mysql_app, 'SELECT * FROM user WHERE id = 1')[0] == row
