"""Shared fixed-window limits stored in MySQL (works across worker processes)."""

import hashlib
import hmac
from datetime import datetime, timedelta

from flask import current_app

from ..db import reading, transaction
from ..services.errors import ApiError


def consume_attempts(buckets):
    now = datetime.utcnow()
    secret = current_app.config['SECRET_KEY'].encode('utf-8')
    keys = sorted(
        (hmac.new(secret, name.encode('utf-8'), hashlib.sha256).hexdigest(), limit, seconds)
        for name, limit, seconds in buckets
    )
    retry_after = 0
    with transaction() as cursor:
        for key, limit, seconds in keys:
            cursor.execute(
                'INSERT IGNORE INTO auth_rate_limit (key_hash, window_started, attempts) VALUES (%s, %s, 0)',
                (key, now),
            )
            cursor.execute(
                'SELECT window_started, attempts FROM auth_rate_limit WHERE key_hash = %s FOR UPDATE',
                (key,),
            )
            row = cursor.fetchone()
            started = row['window_started']
            if now >= started + timedelta(seconds=seconds):
                started, attempts = now, 1
            else:
                attempts = min(row['attempts'] + 1, limit + 1)
            cursor.execute(
                'UPDATE auth_rate_limit SET window_started = %s, attempts = %s WHERE key_hash = %s',
                (started, attempts, key),
            )
            if attempts > limit:
                retry_after = max(
                    retry_after,
                    int((started + timedelta(seconds=seconds) - now).total_seconds()) + 1,
                )
    # Raise only AFTER commit; rollback must not erase the rate-limit counters.
    if retry_after:
        raise ApiError(
            'Too many attempts; try again later', 429, 'rate_limited', {'retry_after': retry_after}
        )


def limit_login(username, address):
    config = current_app.config
    consume_attempts(
        [(f'login:ip:{address}', config['LOGIN_IP_LIMIT'], config['AUTH_LIMIT_WINDOW'])]
    )
    # Resolve using MySQL's actual collation: case/accent aliases must share a limit.
    with reading() as cursor:
        cursor.execute('SELECT id FROM user WHERE username = %s', (username,))
        user = cursor.fetchone()
    account = f'id:{user["id"]}' if user else f'name:{username.casefold()}'
    consume_attempts(
        [(f'login:account:{account}', config['LOGIN_ACCOUNT_LIMIT'], config['AUTH_LIMIT_WINDOW'])]
    )


def limit_registration(address):
    consume_attempts(
        [
            (
                f'register:ip:{address}',
                current_app.config['REGISTER_IP_LIMIT'],
                current_app.config['AUTH_LIMIT_WINDOW'],
            )
        ]
    )
