"""Configuration is loaded per application, never captured at import time."""

import os
from pathlib import Path


def _boolean(name, default=False):
    value = os.environ.get(name, str(default)).lower()
    if value not in {'true', 'false', '1', '0'}:
        raise ValueError(f'{name} must be true or false')
    return value in {'true', '1'}


def load_config():
    return {
        'ENVIRONMENT': os.environ.get('WM_ENV', 'development'),
        'DEBUG': _boolean('WM_DEBUG'),
        'SECRET_KEY': os.environ.get('WM_SECRET_KEY'),
        'HOST': os.environ.get('WM_HOST', '127.0.0.1'),
        'PORT': int(os.environ.get('WM_PORT', '5000')),
        'LOG_LEVEL': os.environ.get('WM_LOG_LEVEL', 'INFO').upper(),
        'DB_HOST': os.environ.get('WM_DB_HOST', '127.0.0.1'),
        'DB_PORT': int(os.environ.get('WM_DB_PORT', '3306')),
        'DB_USER': os.environ.get('WM_DB_USER', 'wm'),
        'DB_PASSWORD': os.environ.get('WM_DB_PASSWORD', ''),
        'DB_NAME': os.environ.get('WM_DB_NAME', 'wm'),
        'DB_CONNECT_TIMEOUT': 5,
        'DB_READ_TIMEOUT': 10,
        'DB_WRITE_TIMEOUT': 10,
        'MAX_CONTENT_LENGTH': 2 * 1024 * 1024,
        'FRONTEND_DIST': str(Path(__file__).resolve().parent.parent / 'frontend' / 'dist'),
        'AUTH_COOKIE_NAME': 'wm_session',
        'CSRF_COOKIE_NAME': 'wm_csrf',
        'AUTH_SESSION_SECONDS': int(os.environ.get('WM_SESSION_SECONDS', str(7 * 24 * 3600))),
        'CSRF_SECONDS': 3600,
        'AUTH_LIMIT_WINDOW': int(os.environ.get('WM_AUTH_LIMIT_WINDOW', '300')),
        'LOGIN_IP_LIMIT': int(os.environ.get('WM_LOGIN_IP_LIMIT', '30')),
        'LOGIN_ACCOUNT_LIMIT': int(os.environ.get('WM_LOGIN_ACCOUNT_LIMIT', '10')),
        'REGISTER_IP_LIMIT': int(os.environ.get('WM_REGISTER_IP_LIMIT', '10')),
        'RATING_ADJUST_LIMIT': int(os.environ.get('WM_RATING_ADJUST_LIMIT', '10')),
        'CSV_MAX_BYTES': 512 * 1024,
        'CSV_MAX_ROWS': 5000,
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SAMESITE': 'Lax',
        'SESSION_COOKIE_SECURE': os.environ.get('WM_ENV') == 'production',
    }


def validate_config(config):
    if config['ENVIRONMENT'] not in {'development', 'testing', 'production'}:
        raise ValueError('WM_ENV must be development, testing or production')
    if not 1 <= config['PORT'] <= 65535 or not 1 <= config['DB_PORT'] <= 65535:
        raise ValueError('Ports must be between 1 and 65535')
    for key in (
        'AUTH_SESSION_SECONDS',
        'CSRF_SECONDS',
        'AUTH_LIMIT_WINDOW',
        'LOGIN_IP_LIMIT',
        'LOGIN_ACCOUNT_LIMIT',
        'REGISTER_IP_LIMIT',
        'RATING_ADJUST_LIMIT',
        'CSV_MAX_BYTES',
        'CSV_MAX_ROWS',
    ):
        if config[key] <= 0:
            raise ValueError(f'{key} must be positive')
    if config['ENVIRONMENT'] == 'production':
        config['SESSION_COOKIE_SECURE'] = True
        if config['DEBUG']:
            raise ValueError('Debug mode must be disabled in production')
        if not config['DB_PASSWORD']:
            raise ValueError('WM_DB_PASSWORD is required in production')
        if not config['SECRET_KEY'] or len(config['SECRET_KEY']) < 32:
            raise ValueError('WM_SECRET_KEY must contain at least 32 characters in production')
