from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.mark.parametrize('path', ['/login/', '/register/', '/leaderboard/'])
def test_public_migrated_pages_serve_same_shell(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert '<div id="app">' in response.text
    assert response.headers['Cache-Control'] == 'no-store'
    assert '/static/js/auth.js' not in response.text


def test_profile_shell_keeps_server_login_guard(client, authenticated_client):
    for path in (
        '/',
        '/changepw/',
        '/admin/',
        '/admin/dicts/9/',
        '/admin/users/',
        '/game/1/detail/',
        '/game/1/',
    ):
        response = client.get(path)
        assert response.status_code == 302
        target = urlsplit(response.headers['Location'])
        assert target.path == '/login/'
        assert parse_qs(target.query) == {'next': [path]}
    assert authenticated_client.get('/changepw/').status_code == 200


def test_missing_build_is_explicit_and_not_a_legacy_fallback(app, client, tmp_path):
    app.config['FRONTEND_DIST'] = str(tmp_path / 'missing')
    response = client.get('/login/')
    assert response.status_code == 503
    assert 'Frontend build missing' in response.text
    assert client.get('/health/live').status_code == 200


@pytest.mark.parametrize(
    'path',
    [
        '/unknown/',
        '/api/not-a-route',
        '/ui/assets/not-a-file.js',
        '/ui/index.html',
        '/ui/assets/../index.html',
        '/game/1/detail/unknown/',
        '/game/abc/detail/',
        '/static/js/game-detail.js',
        '/static/js/game-playing.js',
        '/static/js/auth.js',
        '/static/js/basic.js',
        '/static/css/basic.css',
    ],
)
def test_spa_never_swallows_unknown_routes_or_missing_assets(client, path):
    assert client.get(path).status_code == 404


def test_history_missing_build_has_no_legacy_fallback(app, authenticated_client, tmp_path):
    app.config['FRONTEND_DIST'] = str(tmp_path / 'missing')
    response = authenticated_client.get('/game/1/detail/')
    assert response.status_code == 503 and 'Frontend build missing' in response.text
    assert '/static/js/game-detail.js' not in response.text
    assert authenticated_client.get('/game/1/').status_code == 503


def test_hashed_assets_are_served_without_authentication(app, client):
    assets = Path(app.config['FRONTEND_DIST']) / 'assets'
    assets.mkdir()
    (assets / 'index-test.js').write_text('export const test = true;')
    response = client.get('/ui/assets/index-test.js')
    assert response.status_code == 200
    assert 'javascript' in response.mimetype
    assert response.headers['Cache-Control'] == 'public, max-age=31536000, immutable'
    assert 'HttpOnly' not in response.headers.get('Set-Cookie', '')


def test_explicit_pages_share_shell_without_replacing_api(authenticated_client):
    assert '<div id="app">' in authenticated_client.get('/').text
    detail = authenticated_client.get('/game/1/detail/')
    assert '<div id="app">' in detail.text and '/static/js/game-detail.js' not in detail.text
    assert detail.headers['Cache-Control'] == 'no-store'
    playing = authenticated_client.get('/game/1/')
    assert '<div id="app">' in playing.text and '/static/' not in playing.text
    assert '<div id="app">' in authenticated_client.get('/admin/').text
    assert authenticated_client.get('/api/session').is_json
