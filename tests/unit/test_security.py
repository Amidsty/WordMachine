import hashlib
from unittest.mock import Mock

import pytest

from wm_app import socketio
from wm_app.security.passwords import hash_password, is_legacy_hash, verify_password
from wm_app.services.auth import resolve_session
from wm_app.services.validation import password, string, username


def test_new_password_hash_is_salted_scrypt():
    first = hash_password(' secret ')
    second = hash_password(' secret ')
    assert first.startswith('scrypt:32768:8:1$') and first != second
    assert verify_password(first, ' secret ')
    assert not verify_password(first, 'secret')
    assert not verify_password(first, first)


def test_legacy_hash_only_verifies_plaintext_and_legacy_whitespace():
    legacy = hashlib.sha256(b'secret').hexdigest()
    assert is_legacy_hash(legacy)
    assert verify_password(legacy, ' secret ')
    assert not verify_password(legacy, legacy)
    assert not verify_password(None, 'secret')


@pytest.mark.parametrize('token', [None, '', 'bad', 'x' * 64, {}, True])
def test_invalid_session_cookie_never_accesses_database(app, token):
    with app.app_context():
        assert resolve_session(token) is None


def test_old_credentials_never_authenticate(client):
    client.set_cookie('uid', '1')
    client.set_cookie('pwhash', 'a' * 64)
    response = client.get('/api/game/list?uid=1&pwhash=' + 'a' * 64)
    assert response.status_code == 401
    assert any(cookie.startswith('pwhash=;') for cookie in response.headers.getlist('Set-Cookie'))
    assert client.post('/api/verify', json={'uid': 1, 'pwhash': 'a' * 64}).status_code == 404


def test_anonymous_csrf_bootstrap_and_login_csrf(client, monkeypatch):
    bootstrap = client.get('/api/session')
    assert bootstrap.json['authenticated'] is False
    assert bootstrap.json['user'] is None
    assert 'HttpOnly' in bootstrap.headers.getlist('Set-Cookie')[-1]
    login = Mock()
    monkeypatch.setattr('wm_app.services.auth.login', login)
    assert (
        client.post('/api/login', json={'username': 'first', 'password': 'secret'}).status_code
        == 403
    )
    assert client.post('/api/register', json={}, headers={'X-CSRF-Token': 'bad'}).status_code == 403
    login.assert_not_called()
    # A copied token from another browser cannot pass the cookie-bound comparison.
    other = client.application.test_client()
    assert (
        other.post(
            '/api/login', json={}, headers={'X-CSRF-Token': bootstrap.json['csrf_token']}
        ).status_code
        == 403
    )


def test_authenticated_writes_require_csrf(authenticated_client, monkeypatch):
    command = Mock()
    monkeypatch.setattr('wm_app.services.game.end_game', command)
    authenticated_client.environ_base.pop('HTTP_X_CSRF_TOKEN')
    assert authenticated_client.post('/api/game/1/end', json={}).status_code == 403
    assert (
        authenticated_client.post(
            '/api/game/1/end', json={}, headers={'X-CSRF-Token': '中文'}
        ).status_code
        == 403
    )
    command.assert_not_called()


@pytest.mark.parametrize(
    'origin',
    [
        'https://evil.example',
        'null',
        'http://localhost.evil.test',
        'http://localhost:9999',
        'http://user@localhost',
    ],
)
def test_cross_origin_write_rejected(authenticated_client, origin):
    response = authenticated_client.post('/api/game/1/end', json={}, headers={'Origin': origin})
    assert response.status_code == 403 and response.json['code'] == 'csrf_failed'


def test_admin_endpoints_require_root(authenticated_client):
    assert authenticated_client.get('/api/admin/users').status_code == 403
    for action in ('delete', 'restore', 'reset-password'):
        assert (
            authenticated_client.post(
                '/api/admin/user/2/' + action, json={'uid': 999, 'type': 'root'}
            ).status_code
            == 403
        )


def test_login_sets_http_only_cookie_without_exposing_token_or_hash(client, identity, monkeypatch):
    monkeypatch.setattr('wm_app.routes_auth.limit_login', Mock())
    monkeypatch.setattr('wm_app.services.auth.login', Mock(return_value=('a' * 64, identity)))
    csrf = client.get('/api/session').json['csrf_token']
    client.application.config['SESSION_COOKIE_SECURE'] = True
    response = client.post(
        '/api/login',
        json={'username': 'first', 'password': 'secret'},
        headers={'X-CSRF-Token': csrf},
    )
    assert response.status_code == 200
    assert 'pwhash' not in response.json and 'token' not in response.json
    cookie = next(
        cookie
        for cookie in response.headers.getlist('Set-Cookie')
        if cookie.startswith('wm_session=')
    )
    assert all(flag in cookie for flag in ('HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/'))
    assert response.headers['Cache-Control'] == 'no-store'


def test_foreign_profile_update_forbidden(authenticated_client):
    response = authenticated_client.post('/api/user/2/update', json={'introduction': 'stolen'})
    assert response.status_code == 403


def test_socket_handshake_requires_session_and_csrf(app, authenticated_client, identity):
    assert not socketio.test_client(app, auth={'csrf_token': identity.csrf_token}).is_connected()
    assert not socketio.test_client(
        app, flask_test_client=authenticated_client, auth={}
    ).is_connected()
    assert not socketio.test_client(
        app,
        flask_test_client=authenticated_client,
        auth={'csrf_token': identity.csrf_token},
        headers={'Origin': 'https://evil.example'},
    ).is_connected()


def test_revoked_idle_socket_is_evicted_before_broadcast(
    app, authenticated_client, identity, monkeypatch
):
    socket = socketio.test_client(
        app, flask_test_client=authenticated_client, auth={'csrf_token': identity.csrf_token}
    )
    assert socket.is_connected()
    monkeypatch.setattr('wm_app.services.auth.resolve_digest', lambda *_: None)
    monkeypatch.setattr('wm_app.services.game.get_game_state', lambda _: {'id': 1})
    from wm_app.socket_game import publish_game_state

    with app.app_context():
        publish_game_state(1)
    assert not socket.is_connected()


def test_socket_rechecks_session_for_every_event(app, authenticated_client, identity, monkeypatch):
    socket = socketio.test_client(
        app, flask_test_client=authenticated_client, auth={'csrf_token': identity.csrf_token}
    )
    command = Mock()
    monkeypatch.setattr('wm_app.services.game.answer_game', command)
    monkeypatch.setattr('wm_app.services.auth.resolve_session', lambda *_: None)
    socket.emit(
        'game.answer',
        {'game_id': 1, 'word_id': 11, 'answer': 'apple', 'csrf_token': identity.csrf_token},
    )
    assert not socket.is_connected()
    command.assert_not_called()


@pytest.mark.parametrize('value', [None, 123, True, [], '', 'a' * 256, 'a\x00b', '\ud800'])
def test_string_validation(value):
    from wm_app.services.errors import ApiError

    with pytest.raises(ApiError):
        string(value, 'Name', minimum=1)


def test_legacy_short_username_can_login_but_not_register():
    from wm_app.services.errors import ApiError

    assert username('x', new=False) == 'x'
    with pytest.raises(ApiError):
        username('x')
    assert password(' secret ') == ' secret '


def test_socket_rejects_invalid_csrf_without_invoking_command(
    app, authenticated_client, identity, monkeypatch
):
    command = Mock()
    monkeypatch.setattr('wm_app.services.game.answer_game', command)
    socket = socketio.test_client(
        app, flask_test_client=authenticated_client, auth={'csrf_token': identity.csrf_token}
    )
    try:
        socket.emit(
            'game.answer', {'game_id': 1, 'word_id': 11, 'answer': 'apple', 'csrf_token': '\ud800'}
        )
        assert socket.get_received()[0]['args'][0]['code'] == 'csrf_failed'
        command.assert_not_called()
    finally:
        socket.disconnect()
