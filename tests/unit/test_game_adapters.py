from unittest.mock import Mock

import pytest

from wm_app import socketio
from wm_app.services.errors import GameError


@pytest.mark.parametrize(
    'payload', [None, [], {}, {'word_id': True}, {'word_id': 1.5}, {'word_id': 'bad'}]
)
def test_bad_parameters_are_client_errors(authenticated_client, payload):
    response = authenticated_client.post(
        '/api/game/1/answer', json=payload, content_type='application/json'
    )
    assert response.status_code == 400
    assert response.json['success'] is False


def test_answer_http_and_socket_use_same_service(app, authenticated_client, identity, monkeypatch):
    answer = Mock(return_value={'correct': True, 'perf': 1511, 'status': 0})
    publish = Mock()
    monkeypatch.setattr('wm_app.services.game.answer_game', answer)
    monkeypatch.setattr('wm_app.socket_game.publish_game_state', publish)
    options = {'request_id': '12345678-1234-4234-8234-123456789012', 'expected_version': 0}
    payload = {
        'uid': 999,
        'word_id': 7,
        'answer': 'apple',
        **options,
    }  # Forged UID is not identity.
    response = authenticated_client.post('/api/game/9/answer', json=payload)
    assert response.status_code == 200
    assert response.json['perf'] == 1511
    answer.assert_called_with(9, 1, 7, 'apple', **options)
    socket = socketio.test_client(
        app, flask_test_client=authenticated_client, auth={'csrf_token': identity.csrf_token}
    )
    try:
        socket.emit('game.answer', {**payload, 'game_id': 9, 'csrf_token': identity.csrf_token})
        event = next(item for item in socket.get_received() if item['name'] == 'game.answer_result')
        assert event['args'][0] == response.json
        assert answer.call_count == publish.call_count == 2
        answer.assert_called_with(9, 1, 7, 'apple', **options)
    finally:
        socket.disconnect()


def test_domain_error_has_same_code_in_both_transports(
    app, authenticated_client, identity, monkeypatch
):
    monkeypatch.setattr(
        'wm_app.services.game.answer_game', Mock(side_effect=GameError('Not your turn'))
    )
    payload = {'word_id': 7, 'answer': 'apple', 'game_id': 9, 'csrf_token': identity.csrf_token}
    response = authenticated_client.post('/api/game/9/answer', json=payload)
    assert response.status_code == 409
    socket = socketio.test_client(
        app, flask_test_client=authenticated_client, auth={'csrf_token': identity.csrf_token}
    )
    try:
        socket.emit('game.answer', payload)
        assert socket.get_received()[0]['args'][0] == response.json
    finally:
        socket.disconnect()


@pytest.mark.parametrize('connected', [False, True])
def test_room_join_distinguishes_disconnect_races_from_real_errors(app, monkeypatch, connected):
    from flask import request

    from wm_app.socket_game import _join_connected

    join = Mock(side_effect=ValueError('room failure'))
    monkeypatch.setattr('wm_app.socket_game.join_room', join)
    monkeypatch.setattr(socketio.server.manager, 'is_connected', Mock(return_value=connected))
    with app.test_request_context('/'):
        request.sid = 'connection-under-test'
        if connected:
            with pytest.raises(ValueError, match='room failure'):
                _join_connected(9)
        else:
            assert _join_connected(9) is False
    join.assert_called_once_with('game_9')


def test_failed_post_commit_broadcast_does_not_turn_success_into_error(
    authenticated_client, monkeypatch
):
    monkeypatch.setattr(
        'wm_app.services.game.end_game', Mock(return_value={'already_finished': False})
    )
    monkeypatch.setattr(
        'wm_app.services.game.get_game_state', Mock(side_effect=RuntimeError('notification failed'))
    )
    response = authenticated_client.post('/api/game/1/end', json={})
    assert response.status_code == 200
    assert response.json['success'] is True
