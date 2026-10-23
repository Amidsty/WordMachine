"""Natural deadlines, not rewritten timestamps or simulated successful responses."""

import time
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from wm_app import socketio
from wm_app.services import auth
from wm_app.socket_game import publish_game_state

from .test_game_mysql import query

pytestmark = pytest.mark.mysql


def wait_until_expired(app, token):
    expiry = query(
        app,
        'SELECT expires_at FROM auth_session WHERE token_hash = %s',
        (auth.token_digest(token),),
    )[0]['expires_at']
    deadline = time.monotonic() + 15
    while datetime.utcnow() <= expiry:
        assert time.monotonic() < deadline, 'Synthetic session did not reach its deadline'
        time.sleep(0.05)
    # No UPDATE of expires_at, server clock patch, purge, logout or ban.
    assert (
        query(
            app,
            'SELECT expires_at FROM auth_session WHERE token_hash = %s',
            (auth.token_digest(token),),
        )[0]['expires_at']
        == expiry
    )


def facts(app):
    state = {
        table: query(app, f'SELECT * FROM {table} ORDER BY 1, 2')
        for table in (
            'dict',
            'word',
            'game',
            'game_request',
            'game_question',
            'game_participant',
            'game_answer',
            'game_settlement',
            'game_rating',
        )
    }
    state['users'] = query(
        app,
        'SELECT id, introduction, rating, type, deleted, gamehistory, ratinghistory, '
        'rating_ledger_id FROM user ORDER BY id',
    )
    return state


def test_natural_expiry_denies_http_writes_but_preserves_a_committed_receipt(
    mysql_app, mysql_login
):
    mysql_app.config['AUTH_SESSION_SECONDS'] = 5
    client, csrf = mysql_login(1)
    token = client.get_cookie('wm_session').value
    command = {
        'word_id': 11,
        'answer': 'apple',
        'request_id': str(uuid4()),
        'expected_version': 0,
    }
    committed = client.post('/api/game/1/answer', json=command)
    assert committed.status_code == 200 and committed.json['version'] == 1
    before = facts(mysql_app)
    assert len(before['game_request']) == 1
    wait_until_expired(mysql_app, token)
    for path, payload in (
        ('/api/game/1/answer', command),
        ('/api/game/1/end', {'request_id': str(uuid4()), 'expected_version': 1}),
        ('/api/dict', {'dictname': 'expired creation'}),
        ('/api/user/1/update', {'introduction': 'expired profile'}),
    ):
        response = client.post(path, json=payload)
        assert response.status_code == 401 and response.json['code'] == 'unauthenticated'
    assert facts(mysql_app) == before
    replay = mysql_app.test_client()
    replay.set_cookie('wm_session', token)
    assert replay.get('/api/game/1').status_code == 401
    session = replay.get('/api/session').json
    assert session['authenticated'] is False and session['csrf_token'] != csrf
    assert replay.get_cookie('wm_session') is None
    fresh, new_csrf = mysql_login(1)
    assert new_csrf != csrf and fresh.get_cookie('wm_session').value != token
    assert fresh.post('/api/game/1/answer', json=command).json == committed.json
    assert facts(mysql_app) == before  # New session, original UUID/actor/payload; no second score.


@pytest.mark.parametrize('event', ['game.subscribe', 'game.answer', 'game.end'])
def test_natural_expiry_is_rechecked_before_each_socket_event(mysql_app, mysql_login, event):
    mysql_app.config['AUTH_SESSION_SECONDS'] = 5
    client, csrf = mysql_login(1)
    token = client.get_cookie('wm_session').value
    socket = socketio.test_client(mysql_app, flask_test_client=client, auth={'csrf_token': csrf})
    try:
        assert socket.is_connected()
        assert socket.emit('game.subscribe', {'game_id': 1, 'csrf_token': csrf}, callback=True) == {
            'success': True
        }
        socket.get_received()
        before = facts(mysql_app)
        wait_until_expired(mysql_app, token)
        socket.emit(
            event,
            {
                'game_id': 1,
                'csrf_token': csrf,
                'word_id': 11,
                'answer': 'apple',
                'request_id': str(uuid4()),
                'expected_version': 0,
            },
        )
        assert not socket.is_connected()
        assert not mysql_app.extensions['socket_connections'].snapshot()
        assert facts(mysql_app) == before
        rejected = socketio.test_client(
            mysql_app, flask_test_client=client, auth={'csrf_token': csrf}
        )
        assert not rejected.is_connected()  # Same expired raw Cookie cannot reconnect.
    finally:
        if socket.is_connected():
            socket.disconnect()


def test_broadcast_prunes_expired_idle_socket_but_keeps_live_session(mysql_app, mysql_login):
    live, live_csrf = mysql_login(2)
    mysql_app.config['AUTH_SESSION_SECONDS'] = 5
    idle, idle_csrf = mysql_login(1)
    sockets = [
        socketio.test_client(mysql_app, flask_test_client=client, auth={'csrf_token': csrf})
        for client, csrf in ((idle, idle_csrf), (live, live_csrf))
    ]
    try:
        for socket, csrf in zip(sockets, (idle_csrf, live_csrf), strict=True):
            assert socket.is_connected()
            socket.emit('game.subscribe', {'game_id': 1, 'csrf_token': csrf})
            socket.get_received()
        before = facts(mysql_app)
        wait_until_expired(mysql_app, idle.get_cookie('wm_session').value)
        with mysql_app.app_context():
            publish_game_state(1)
        assert not sockets[0].is_connected() and sockets[1].is_connected()
        updates = [event for event in sockets[1].get_received() if event['name'] == 'game.update']
        assert len(updates) == 1 and updates[0]['args'][0]['version'] == 0
        assert len(mysql_app.extensions['socket_connections'].snapshot()) == 1
        assert facts(mysql_app) == before
    finally:
        for socket in sockets:
            if socket.is_connected():
                socket.disconnect()


def test_retry_after_and_persisted_counters_recover_without_rewriting_the_window(mysql_app):
    mysql_app.config.update(LOGIN_ACCOUNT_LIMIT=1, LOGIN_IP_LIMIT=20, AUTH_LIMIT_WINDOW=3)
    client = mysql_app.test_client()
    csrf = client.get('/api/session').json['csrf_token']
    headers = {'X-CSRF-Token': csrf}
    before = facts(mysql_app)
    password_before = query(mysql_app, 'SELECT pwhash FROM user WHERE id = 1')
    assert (
        client.post(
            '/api/login', json={'username': 'user1', 'password': 'wrong'}, headers=headers
        ).status_code
        == 401
    )
    blocked = client.post(
        '/api/login', json={'username': 'USER1', 'password': 'test-password'}, headers=headers
    )
    assert blocked.status_code == 429 and blocked.json['code'] == 'rate_limited'
    retry = int(blocked.headers['Retry-After'])
    # The existing DATETIME column stores whole seconds; MySQL may round the
    # new window forward. Retry-After must cover the stored deadline, not an
    # assumed subsecond timestamp or an exact configured-duration ceiling.
    assert 1 <= retry <= 4 and blocked.json['details']['retry_after'] == retry
    assert blocked.headers['Cache-Control'] == 'no-store'
    counters = query(mysql_app, 'SELECT * FROM auth_rate_limit ORDER BY key_hash')
    assert len(counters) == 2 and all(row['attempts'] == 2 for row in counters)
    assert max(row['window_started'] for row in counters) + timedelta(seconds=3) <= (
        datetime.utcnow() + timedelta(seconds=retry)
    )
    assert not query(mysql_app, 'SELECT token_hash FROM auth_session')
    assert query(mysql_app, 'SELECT pwhash FROM user WHERE id = 1') == password_before
    assert facts(mysql_app) == before
    time.sleep(retry + 0.05)  # Respect the actual response, without changing stored time.
    assert query(mysql_app, 'SELECT * FROM auth_rate_limit ORDER BY key_hash') == counters
    assert not query(mysql_app, 'SELECT token_hash FROM auth_session')
    recovered = client.post(
        '/api/login', json={'username': 'user1', 'password': 'test-password'}, headers=headers
    )
    assert recovered.status_code == 200 and recovered.json['user']['id'] == 1
    assert recovered.json['csrf_token'] != csrf
    assert len(query(mysql_app, 'SELECT token_hash FROM auth_session')) == 1
    reset = query(mysql_app, 'SELECT * FROM auth_rate_limit ORDER BY key_hash')
    assert all(row['attempts'] == 1 for row in reset)
    assert all(
        a['window_started'] < b['window_started'] for a, b in zip(counters, reset, strict=True)
    )
    assert facts(mysql_app) == before
