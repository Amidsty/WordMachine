import hashlib
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock

import pytest

from wm_app.services import auth
from wm_app.services.errors import ApiError


@pytest.mark.parametrize('deleted', [0, 1, None])
@pytest.mark.parametrize('rating', [None, 0, -1, 2400])
def test_public_person_exposes_only_current_active_rating(deleted, rating):
    row = {'id': 1, 'username': '<img>', 'deleted': deleted, 'rating': rating, 'pwhash': 'private'}
    before = dict(row)
    assert auth.public_person(row) == {
        'id': 1,
        'username': '<img>',
        'rating': rating if deleted == 0 else None,
    }
    assert row == before


def test_missing_person_or_visibility_is_not_assigned_a_rating():
    assert auth.public_person(None) is None
    assert auth.public_person({'id': 1, 'username': None, 'rating': 2400}) == {
        'id': 1,
        'username': None,
        'rating': None,
    }


@pytest.fixture
def legacy_user_cursor(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.return_value = {
        'id': 1,
        'username': 'first',
        'pwhash': hashlib.sha256(b'secret').hexdigest(),
        'type': 'normal',
        'deleted': 0,
        'rating': 1500,
        'introduction': '',
    }

    @contextmanager
    def transaction():
        yield cursor

    monkeypatch.setattr(auth, 'transaction', transaction)
    return cursor


def test_successful_legacy_login_upgrades_and_persists_only_session_digest(app, legacy_user_cursor):
    with app.app_context():
        token, identity = auth.login('first', 'secret')
    updates = [
        call
        for call in legacy_user_cursor.execute.call_args_list
        if call.args[0].startswith('UPDATE')
    ]
    assert len(updates) == 1 and updates[0].args[1][0].startswith('scrypt:')
    insert = legacy_user_cursor.execute.call_args_list[-1]
    assert insert.args[0].startswith('INSERT INTO auth_session')
    assert insert.args[1][0] == auth.token_digest(token) == identity.token_hash
    assert token not in insert.args[1]
    assert 'pwhash' not in identity.user


def test_failed_legacy_login_never_updates_password_or_issues_session(app, legacy_user_cursor):
    with app.app_context(), pytest.raises(ApiError) as exc:
        auth.login('first', 'wrong')
    assert exc.value.code == 'invalid_credentials'
    assert legacy_user_cursor.execute.call_count == 1


def test_cli_create_admin_uses_interactive_password_and_does_not_echo_it(app, monkeypatch):
    create = Mock(return_value={'id': 99})
    monkeypatch.setattr('wm_app.cli.create_user', create)
    result = app.test_cli_runner().invoke(
        args=['create-admin', 'admin-new'], input='secret-value\nsecret-value\n'
    )
    assert result.exit_code == 0, result.output
    create.assert_called_once_with('admin-new', 'secret-value', role='root', level=1)
    assert 'secret-value' not in result.output and 'id=99' in result.output


@pytest.mark.parametrize(
    'version,status',
    [
        ('0011_dictionary_multipliers', 503),
        ('0012_manual_rating', 200),
        ('0010_rating_events', 503),
        ('0009_admin_levels', 503),
        ('0008_list_indexes', 503),
        ('0007_game_settlements', 503),
        ('0006_game_answers', 503),
        ('0005_game_participants', 503),
        ('0004_game_questions', 503),
        ('0003_game_requests', 503),
        ('0002_sessions_dict', 503),
        ('0001_legacy', 503),
    ],
)
def test_readiness_requires_current_migration(client, monkeypatch, version, status):
    cursor = MagicMock()
    cursor.fetchall.return_value = [{'version_num': version}]

    @contextmanager
    def reading():
        yield cursor

    monkeypatch.setattr('wm_app.reading', reading)
    assert client.get('/health/ready').status_code == status


def test_normal_users_can_open_dictionary_management_but_not_user_management(authenticated_client):
    response = authenticated_client.get('/admin/')
    assert response.status_code == 200
    assert '<div id="app">' in response.text and 'usersTableBody' not in response.text
    assert authenticated_client.get('/admin/users/').status_code == 403
    assert response.headers['Cache-Control'] == 'no-store'
