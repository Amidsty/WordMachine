"""A ban committed after HTTP authentication must win before any new game write."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from wm_app import socketio
from wm_app.services import auth, game

from .test_game_mysql import query

pytestmark = pytest.mark.mysql


@pytest.mark.parametrize(
    'action,transport',
    [(action, 'http') for action in ('create', 'join', 'leave', 'start', 'cancel', 'answer', 'end')]
    + [('answer', 'socket')],
)
def test_ban_after_authentication_before_user_lock_rolls_back_command(
    mysql_app, mysql_login, monkeypatch, action, transport
):
    monkeypatch.setattr(game.random, 'shuffle', lambda rows: None)
    with mysql_app.app_context():
        gid = game.create_game(1, 1)['game_id']
        if action != 'join':
            game.join_game(gid, 2)
        if action in ('answer', 'end'):
            game.start_game(gid, 1)
    uid = 2 if action in ('join', 'leave') else 1
    actor, csrf = mysql_login(uid)
    admin, _ = mysql_login(3)
    tables = (
        'game',
        'game_question',
        'game_participant',
        'game_answer',
        'game_request',
        'game_settlement',
        'game_rating',
        'rating_event',
        'dictionary_audit',
    )
    before = {table: query(mysql_app, f'SELECT * FROM `{table}`') for table in tables}
    balances = query(
        mysql_app,
        'SELECT id,rating,gamehistory,ratinghistory,rating_ledger_id,rating_event_id FROM user ORDER BY id',
    )
    entered, release = Event(), Event()
    original = game._OPERATIONS[action]

    def paused(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setitem(game._OPERATIONS, action, paused)
    payload = {'request_id': str(uuid4())}
    path = f'/api/game/{gid}/{action}'
    if action == 'create':
        path = '/api/game/create'
        payload['dict_id'] = 1
    if action == 'answer':
        payload.update(word_id=11, answer='apple')
    socket = (
        socketio.test_client(mysql_app, flask_test_client=actor, auth={'csrf_token': csrf})
        if transport == 'socket'
        else None
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = (
                pool.submit(
                    socket.emit,
                    'game.answer',
                    {**payload, 'game_id': gid, 'csrf_token': csrf},
                    callback=True,
                )
                if socket
                else pool.submit(actor.post, path, json=payload)
            )
            try:
                assert entered.wait(10)
                if socket:
                    # Commit actual ban/session revocation, deliberately defer transport
                    # eviction so the in-flight handler's own rejection can be inspected.
                    with mysql_app.app_context():
                        auth.admin_user_action(3, uid, 'delete')
                else:
                    assert admin.post(f'/api/admin/user/{uid}/delete', json={}).status_code == 200
            finally:
                release.set()
            result = pending.result(timeout=10)
        if socket:
            assert result['code'] == 'forbidden', result
            assert result['success'] is False
        else:
            assert result.status_code == 403, result.json
            assert result.json['code'] == 'forbidden'
    finally:
        if socket and socket.is_connected():
            socket.disconnect()
    for table in tables:
        assert query(mysql_app, f'SELECT * FROM `{table}`') == before[table]
    assert (
        query(
            mysql_app,
            'SELECT id,rating,gamehistory,ratinghistory,rating_ledger_id,rating_event_id FROM user ORDER BY id',
        )
        == balances
    )
