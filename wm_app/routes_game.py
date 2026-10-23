"""HTTP game adapter: identity comes exclusively from the server-side session."""

from flask import Blueprint, current_app, jsonify, request

from .security.http import api_endpoint
from .security.rate_limit import consume_attempts
from .services import game, game_end_requests, lobby
from .services.errors import positive_int, text
from .services.game_requests import command_options
from .services.pagination import ListQuery, boolean_query

bp = Blueprint('game', __name__)


def changed(game_id, result):
    from .socket_game import publish_game_state

    publish_game_state(game_id)
    return jsonify(success=True, **result)


@bp.post('/api/game/create')
@api_endpoint()
def api_game_create(data, user):
    return jsonify(
        success=True,
        **game.create_game(
            user['id'],
            positive_int(data, 'dict_id'),
            rated=data.get('rated', True),
            **command_options(data),
        ),
    ), 201


@bp.get('/api/game/list')
@api_endpoint()
def api_game_list(data, user):
    return jsonify(
        success=True,
        **lobby.list_games(user['id'], ListQuery.parse(data), lobby.status_query(data)),
    )


@bp.get('/api/game/<int:game_id>')
@api_endpoint()
def api_game_get(data, user, game_id):
    return jsonify(success=True, game=game.get_game_state(game_id))


@bp.post('/api/game/<int:game_id>/rename')
@api_endpoint()
def api_game_rename(data, user, game_id):
    if set(data) != {'name', 'request_id', 'expected_version'}:
        from .services.errors import GameError

        raise GameError(
            'name, request_id and expected_version are required', 400, 'invalid_parameters'
        )
    return changed(
        game_id, game.rename_game(game_id, user['id'], data['name'], **command_options(data))
    )


@bp.post('/api/game/<int:game_id>/join')
@api_endpoint()
def api_game_join(data, user, game_id):
    return changed(game_id, game.join_game(game_id, user['id'], **command_options(data)))


@bp.post('/api/game/<int:game_id>/leave')
@api_endpoint()
def api_game_leave(data, user, game_id):
    return changed(game_id, game.leave_game(game_id, user['id'], **command_options(data)))


@bp.post('/api/game/<int:game_id>/start')
@api_endpoint()
def api_game_start(data, user, game_id):
    return changed(game_id, game.start_game(game_id, user['id'], **command_options(data)))


@bp.post('/api/game/<int:game_id>/cancel')
@api_endpoint()
def api_game_cancel(data, user, game_id):
    return changed(game_id, game.cancel_game(game_id, user['id'], **command_options(data)))


@bp.post('/api/game/<int:game_id>/answer')
@api_endpoint()
def api_game_answer(data, user, game_id):
    return changed(
        game_id,
        game.answer_game(
            game_id,
            user['id'],
            positive_int(data, 'word_id'),
            text(data, 'answer'),
            **command_options(data),
        ),
    )


@bp.post('/api/game/<int:game_id>/end-requests')
@api_endpoint()
def api_send_end_request(data, user, game_id):
    consume_attempts(
        [
            (f'game-end-request:actor:{user["id"]}', 10, current_app.config['AUTH_LIMIT_WINDOW']),
            (
                f'game-end-request:ip:{request.remote_addr or "unknown"}',
                30,
                current_app.config['AUTH_LIMIT_WINDOW'],
            ),
        ]
    )
    return jsonify(success=True, **game_end_requests.send(game_id, user['id'], data)), 201


@bp.get('/api/game/<int:game_id>/end-requests')
@api_endpoint()
def api_game_end_requests(data, user, game_id):
    return jsonify(
        success=True,
        **game_end_requests.listing(
            user['id'],
            ListQuery.parse(data),
            game_id=game_id,
            include_finished=True,
        ),
    )


@bp.get('/api/game-end-requests')
@api_endpoint()
def api_end_requests(data, user):
    return jsonify(
        success=True,
        **game_end_requests.listing(
            user['id'],
            ListQuery.parse(data),
            include_finished=boolean_query(data, 'include_finished'),
        ),
    )


@bp.post('/api/game/<int:game_id>/end')
@api_endpoint()
def api_game_end(data, user, game_id):
    return changed(game_id, game.end_game(game_id, user['id'], **command_options(data)))
