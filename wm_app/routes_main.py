from flask import Blueprint, abort

from .frontend import frontend_page
from .security.http import page_login_required, request_identity
from .security.permissions import admin_level
from .services import auth

bp = Blueprint('main', __name__)


@bp.get('/')
@page_login_required
def home():
    return frontend_page()


@bp.get('/login/')
def login():
    return frontend_page()


@bp.get('/register/')
def register():
    return frontend_page()


@bp.get('/changepw/')
@page_login_required
def changepw():
    return frontend_page()


@bp.get('/admin/')
@page_login_required
def admin():
    return frontend_page()


@bp.get('/admin/dicts/<int:dict_id>/')
@page_login_required
def dictionary_detail(dict_id):
    return frontend_page()


@bp.get('/admin/dictionary-promotions/')
@page_login_required
def dictionary_promotions():
    return frontend_page()


@bp.get('/admin/users/')
@page_login_required
def user_management():
    if admin_level(request_identity().user) == 0:
        abort(403)
    return frontend_page()


@bp.get('/user/<int:profile_id>/')
def user_profile(profile_id):
    from .services.errors import ApiError

    try:
        auth.get_user(profile_id)  # Keep the existing HTTP 404 for missing/deleted profiles.
    except ApiError as error:
        if error.status == 404:
            abort(404)
        raise
    return frontend_page()


@bp.get('/game-end-requests/')
@page_login_required
def game_end_requests():
    return frontend_page()


@bp.get('/leaderboard/')
def leaderboard():
    return frontend_page()


@bp.get('/game/<int:game_id>/detail/')
@page_login_required
def game_detail(game_id):
    return frontend_page()


@bp.get('/game/<int:game_id>/')
@page_login_required
def game_playing(game_id):
    return frontend_page()
