from datetime import datetime, timedelta

import pytest

from wm_app import create_app
from wm_app.services.auth import Identity, token_digest


@pytest.fixture
def app(monkeypatch, tmp_path):
    def no_database():
        raise AssertionError('Unit tests must explicitly mock database access')

    monkeypatch.setattr('wm_app.db.get_db_connection', no_database)
    frontend = tmp_path / 'frontend-dist'
    frontend.mkdir()
    (frontend / 'index.html').write_text(
        '<!doctype html><title>WordMachine</title><div id="app"></div>'
    )
    return create_app(
        {
            'TESTING': True,
            'ENVIRONMENT': 'testing',
            'DEBUG': False,
            'LOG_LEVEL': 'WARNING',
            'SECRET_KEY': 'test-only-secret',
            'FRONTEND_DIST': str(frontend),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def identity():
    return Identity(
        token_digest('a' * 64),
        'b' * 64,
        {'id': 1, 'username': 'first', 'introduction': '', 'rating': 1500, 'type': 'normal'},
        datetime.utcnow() + timedelta(days=1),
    )


@pytest.fixture
def authenticated_client(app, monkeypatch, identity):
    monkeypatch.setattr(
        'wm_app.services.auth.resolve_session',
        lambda token: identity if token == 'a' * 64 else None,
    )
    monkeypatch.setattr(
        'wm_app.services.auth.resolve_digest',
        lambda digest: identity if digest == identity.token_hash else None,
    )
    client = app.test_client()
    client.set_cookie(app.config['AUTH_COOKIE_NAME'], 'a' * 64)
    client.environ_base['HTTP_X_CSRF_TOKEN'] = identity.csrf_token
    return client
