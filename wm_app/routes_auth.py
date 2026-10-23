from flask import Blueprint, jsonify, request

from .security.http import (
    anonymous_csrf,
    api_endpoint,
    clear_login_cookie,
    issue_anonymous_cookie,
    issue_login_cookie,
    request_identity,
)
from .security.rate_limit import limit_login, limit_registration
from .services import auth, leaderboard, user_history
from .services.pagination import ListQuery, query_value
from .services.validation import password as validate_password
from .services.validation import username as validate_username

bp = Blueprint('auth', __name__)


@bp.get('/api/session')
@api_endpoint(authenticated=False)
def api_session(data, user):
    identity = request_identity()
    token = identity.csrf_token if identity else anonymous_csrf()
    response = jsonify(
        success=True, authenticated=identity is not None, user=user, csrf_token=token
    )
    if identity is None:
        clear_login_cookie(response)
        issue_anonymous_cookie(response, token)
    return response


@bp.post('/api/register')
@api_endpoint(authenticated=False)
def api_register(data, user):
    limit_registration(request.remote_addr or 'unknown')
    created = auth.create_user(
        data.get('username'), data.get('password'), data.get('introduction', '')
    )
    return jsonify(success=True, uid=created['id'], message='Registration successful'), 201


@bp.post('/api/login')
@api_endpoint(authenticated=False)
def api_login(data, user):
    username = validate_username(data.get('username'), new=False)
    password = validate_password(data.get('password'), new=False)
    limit_login(username, request.remote_addr or 'unknown')
    old_identity = request_identity()
    from flask import current_app

    token, identity = auth.login(
        username, password, request.cookies.get(current_app.config['AUTH_COOKIE_NAME'])
    )
    response = jsonify(
        success=True, authenticated=True, user=identity.user, csrf_token=identity.csrf_token
    )
    issue_login_cookie(response, token)
    if old_identity:
        from .socket_game import disconnect_identity

        disconnect_identity(token_hash=old_identity.token_hash)
    return response


@bp.post('/api/logout')
@api_endpoint()
def api_logout(data, user):
    identity = request_identity()
    auth.logout(identity)
    from .socket_game import disconnect_identity

    disconnect_identity(token_hash=identity.token_hash)
    response = jsonify(success=True, message='Logged out')
    clear_login_cookie(response)
    return response


@bp.get('/api/leaderboard')
@api_endpoint(authenticated=False)
def api_leaderboard(data, user):
    return jsonify(success=True, **leaderboard.list_leaders(ListQuery.parse(data)))


@bp.get('/api/user/<int:uid>')
@api_endpoint(authenticated=False)
def api_get_user(data, user, uid):
    return jsonify(success=True, user=auth.get_user(uid))


@bp.get('/api/user/<int:uid>/rating-state')
@api_endpoint(authenticated=False)
def api_rating_state(data, user, uid):
    return jsonify(success=True, **user_history.account(uid))


@bp.get('/api/user/<int:uid>/history')
@api_endpoint(authenticated=False)
def api_user_history(data, user, uid):
    return jsonify(
        success=True,
        **user_history.listing(uid, query_value(data, 'kind', 'rating'), ListQuery.parse(data)),
    )


@bp.post('/api/user/<int:uid>/update')
@api_endpoint()
def api_update_user(data, user, uid):
    result = auth.update_user(user['id'], uid, data)
    response = jsonify(success=True, **result)
    if result['reauthenticate']:
        from .socket_game import disconnect_identity

        disconnect_identity(user_id=user['id'])
        clear_login_cookie(response)
    return response
