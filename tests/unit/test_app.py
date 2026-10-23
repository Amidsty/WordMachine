from unittest.mock import MagicMock

import pytest

from wm_app import create_app, socketio
from wm_app.config import load_config, validate_config
from wm_app.db import get_db_connection, transaction


def test_liveness_and_pages_without_database(client):
    for path in ('/health/live', '/login/', '/register/'):
        response = client.get(path)
        assert response.status_code == 200
        assert len(response.headers['X-Request-ID']) == 32


def test_readiness_failure_is_not_liveness_failure(client):
    assert client.get('/health/ready').status_code == 503
    assert client.get('/health/live').status_code == 200


def test_readiness_success(client, monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [{'version_num': '0012_manual_rating'}]
    monkeypatch.setattr('wm_app.db.get_db_connection', lambda: connection)
    assert client.get('/health/ready').json == {'status': 'ok'}
    cursor.execute.assert_called_once_with('SELECT version_num FROM alembic_version')
    connection.close.assert_called_once()


def test_env_loaded_per_factory_call(monkeypatch):
    monkeypatch.setenv('WM_DB_NAME', 'first')
    first = create_app({'TESTING': True})
    monkeypatch.setenv('WM_DB_NAME', 'second')
    second = create_app({'TESTING': True})
    assert first.config['DB_NAME'] == 'first'
    assert second.config['DB_NAME'] == 'second'


def test_database_credentials_come_from_config(app, monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr('wm_app.db.pymysql.connect', connect)
    app.config.update(DB_HOST='db.test', DB_PORT=33306, DB_PASSWORD='secret', DB_NAME='test_db')
    with app.app_context():
        get_db_connection()
    kwargs = connect.call_args.kwargs
    assert kwargs['host'] == 'db.test'
    assert kwargs['port'] == 33306
    assert kwargs['database'] == 'test_db'
    assert kwargs['password'] == 'secret'
    assert kwargs['autocommit'] is False
    assert kwargs['init_command'] == 'SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ'


@pytest.mark.parametrize(
    'overrides',
    [
        {'DEBUG': True},
        {'SECRET_KEY': None},
        {'DB_PASSWORD': ''},
    ],
)
def test_production_rejects_unsafe_config(overrides):
    config = load_config()
    config.update(ENVIRONMENT='production', DEBUG=False, DB_PASSWORD='test', SECRET_KEY='x' * 32)
    config.update(overrides)
    with pytest.raises(ValueError):
        validate_config(config)


def test_default_debug_off(monkeypatch):
    monkeypatch.delenv('WM_DEBUG', raising=False)
    assert load_config()['DEBUG'] is False


def test_handler_initialization_is_not_swallowed(monkeypatch):
    def broken(server, app):
        raise ImportError('broken handler')

    monkeypatch.setattr('wm_app.socket_game.register_handlers', broken)
    with pytest.raises(ImportError, match='broken handler'):
        create_app({'TESTING': True})


def test_socket_handlers_registered_for_each_factory():
    for _ in range(2):
        app = create_app({'TESTING': True})
        assert 'game.answer' in socketio.server.handlers['/']
        client = socketio.test_client(app)
        assert not client.is_connected()  # Anonymous sockets are rejected at handshake.


@pytest.mark.parametrize('fail', [False, True])
def test_transaction_always_releases_connection(app, monkeypatch, fail):
    connection = MagicMock()
    monkeypatch.setattr('wm_app.db.get_db_connection', lambda: connection)
    with app.app_context():
        if fail:
            with pytest.raises(ValueError):
                with transaction():
                    raise ValueError('operation failed')
            connection.rollback.assert_called_once()
            connection.commit.assert_not_called()
        else:
            with transaction():
                pass
            connection.commit.assert_called_once()
            connection.rollback.assert_not_called()
    connection.close.assert_called_once()


def test_logs_do_not_include_query_credentials(client, caplog):
    client.application.logger.setLevel('INFO')
    response = client.get('/health/live?uid=1&pwhash=do-not-log-me')
    assert response.status_code == 200
    assert 'do-not-log-me' not in caplog.text
    assert 'path=/health/live' in caplog.text
