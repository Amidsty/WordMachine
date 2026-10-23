from flask import Blueprint, current_app, jsonify, request

from .security.http import api_endpoint
from .security.rate_limit import consume_attempts
from .services import auth, rating_adjustments
from .services.pagination import ListQuery, boolean_query

bp = Blueprint('admin', __name__)


@bp.get('/api/admin/check')
@api_endpoint()
def api_admin_check(data, user):
    return jsonify(success=True, type=user['type'])


@bp.get('/api/admin/users')
@api_endpoint(root=True)
def api_admin_users(data, user):
    return jsonify(
        success=True,
        **auth.list_users(user, boolean_query(data, 'include_deleted'), ListQuery.parse(data)),
    )


@bp.get('/api/admin/user/<int:target_uid>')
@api_endpoint(root=True)
def api_managed_user(data, user, target_uid):
    return jsonify(success=True, user=auth.managed_user(user['id'], target_uid))


@bp.get('/api/admin/user/<int:target_uid>/rating')
@api_endpoint(root=True)
def api_rating_review(data, user, target_uid):
    return jsonify(success=True, **rating_adjustments.review(user['id'], target_uid))


@bp.post('/api/admin/user/<int:target_uid>/rating')
@api_endpoint(root=True)
def api_adjust_rating(data, user, target_uid):
    config = current_app.config
    consume_attempts(
        [
            (
                f'rating:actor:{user["id"]}',
                config['RATING_ADJUST_LIMIT'],
                config['AUTH_LIMIT_WINDOW'],
            ),
            (
                f'rating:ip:{request.remote_addr or "unknown"}',
                config['LOGIN_IP_LIMIT'],
                config['AUTH_LIMIT_WINDOW'],
            ),
        ]
    )
    return jsonify(success=True, **rating_adjustments.adjust(user['id'], target_uid, data))


def _action(user, target_uid, action, password=None):
    result = auth.admin_user_action(user['id'], target_uid, action, password)
    from .socket_game import disconnect_identity

    disconnect_identity(user_id=target_uid)
    return jsonify(success=True, **result)


@bp.post('/api/admin/user/<int:target_uid>/update')
@api_endpoint(root=True)
def api_admin_update_user(data, user, target_uid):
    result = auth.admin_update_user(user['id'], target_uid, data)
    from .socket_game import disconnect_identity

    disconnect_identity(user_id=target_uid)
    return jsonify(success=True, **result)


@bp.post('/api/admin/user/<int:target_uid>/level')
@api_endpoint(root=True)
def api_admin_set_level(data, user, target_uid):
    result = auth.set_admin_level(user['id'], target_uid, data)
    from .socket_game import disconnect_identity

    disconnect_identity(user_id=target_uid)
    return jsonify(success=True, **result)


@bp.post('/api/admin/user/<int:target_uid>/reset-password')
@api_endpoint(root=True)
def api_admin_reset_password(data, user, target_uid):
    return _action(user, target_uid, 'reset-password', data.get('new_password'))


@bp.post('/api/admin/user/<int:target_uid>/delete')
@api_endpoint(root=True)
def api_admin_delete_user(data, user, target_uid):
    return _action(user, target_uid, 'delete')


@bp.post('/api/admin/user/<int:target_uid>/restore')
@api_endpoint(root=True)
def api_admin_restore_user(data, user, target_uid):
    return _action(user, target_uid, 'restore')
