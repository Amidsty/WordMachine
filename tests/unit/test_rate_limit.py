from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from wm_app.security.rate_limit import consume_attempts
from wm_app.services.errors import ApiError


def setup_transaction(monkeypatch, row):
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    outcome = []

    @contextmanager
    def transaction():
        try:
            yield cursor
        except Exception:
            outcome.append('rollback')
            raise
        else:
            outcome.append('commit')

    monkeypatch.setattr('wm_app.security.rate_limit.transaction', transaction)
    return cursor, outcome


def test_limit_counters_commit_before_429_and_identifiers_are_hashed(app, monkeypatch):
    cursor, outcome = setup_transaction(
        monkeypatch, {'window_started': datetime.utcnow(), 'attempts': 2}
    )
    with app.app_context(), pytest.raises(ApiError) as exc:
        consume_attempts([('sensitive-account-name', 2, 300)])
    assert exc.value.status == 429 and exc.value.details['retry_after'] > 0
    assert outcome == ['commit']
    assert 'sensitive-account-name' not in str(cursor.execute.call_args_list)
    assert cursor.execute.call_args.args[1][1] == 3


def test_expired_window_resets_counter(app, monkeypatch):
    cursor, outcome = setup_transaction(
        monkeypatch, {'window_started': datetime.utcnow() - timedelta(seconds=301), 'attempts': 100}
    )
    with app.app_context():
        consume_attempts([('ip-address', 2, 300)])
    assert outcome == ['commit']
    assert cursor.execute.call_args.args[1][1] == 1
