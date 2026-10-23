"""Independent SQL checks after real browser expiry and rate-limit flows."""

from datetime import datetime

import pytest

from tests.browser.test_management_browser import unchanged_history
from tests.integration.test_game_mysql import query

__all__ = ['unchanged_history']
pytestmark = pytest.mark.mysql


def test_real_browser_natural_expiry(mysql_app, run_browser, unchanged_history):
    mysql_app.config['AUTH_SESSION_SECONDS'] = 12
    run_browser('expiry.spec.ts')
    assert all(
        row['introduction'] is None
        for row in query(mysql_app, 'SELECT introduction FROM user ORDER BY id')
    )
    sessions = query(mysql_app, 'SELECT user_id, created_at, expires_at FROM auth_session')
    assert len(sessions) == 1 and sessions[0]['user_id'] == 1
    assert sessions[0]['created_at'] < sessions[0]['expires_at'] <= datetime.utcnow()
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM dict')[0]['n'] == 1
    assert not mysql_app.extensions['socket_connections'].snapshot()


def test_real_browser_rate_limit_recovery(mysql_app, run_browser, unchanged_history):
    mysql_app.config.update(LOGIN_ACCOUNT_LIMIT=1, LOGIN_IP_LIMIT=20, AUTH_LIMIT_WINDOW=4)
    run_browser('rate-limit.spec.ts')
    counters = query(mysql_app, 'SELECT attempts FROM auth_rate_limit')
    assert len(counters) == 2 and all(row['attempts'] == 1 for row in counters)
    assert not query(mysql_app, 'SELECT token_hash FROM auth_session')
    assert all(
        row['introduction'] is None
        for row in query(mysql_app, 'SELECT introduction FROM user ORDER BY id')
    )
    assert query(mysql_app, 'SELECT COUNT(*) AS n FROM dict')[0]['n'] == 1
    assert not mysql_app.extensions['socket_connections'].snapshot()
