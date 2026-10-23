"""Session-authenticated Socket.IO adapters using the shared game service."""

from functools import wraps
from threading import RLock

from flask import current_app, request
from flask_socketio import emit, join_room, leave_room

from .extensions import socketio
from .security.http import validate_csrf, validate_origin
from .services import auth, game
from .services.errors import ApiError, positive_int, text
from .services.game_requests import command_options


class Connections:
    def __init__(self):
        self.lock = RLock()
        self.entries = {}
        self.views = {}  # sid -> playing page; connections/room membership alone are not views.
        self.presence_revision = 0

    def add(self, sid, identity):
        with self.lock:
            self.entries[sid] = identity

    def remove(self, sid):
        with self.lock:
            self.entries.pop(sid, None)
            return self.views.pop(sid, None)

    def snapshot(self):
        with self.lock:
            return list(self.entries.items())


def _room_for(game_id):
    return f'game_{game_id}'


def _disconnect(sid):
    game_id = current_app.extensions['socket_connections'].remove(sid)
    socketio.server.disconnect(sid, namespace='/')
    if game_id is not None:
        _publish_presence(game_id)


def disconnect_identity(*, token_hash=None, user_id=None):
    """Post-commit eviction on logout, password change or administrative revocation."""
    for sid, identity in current_app.extensions['socket_connections'].snapshot():
        if identity.token_hash == token_hash or identity.user['id'] == user_id:
            try:
                _disconnect(sid)
            except Exception:
                current_app.logger.exception('Socket eviction failed')


def _publish_presence(game_id, state=None):
    """Ephemeral, process-local viewers; never a participant or authorization source."""
    registry = current_app.extensions['socket_connections']
    expired = []
    try:
        # Serialize snapshots/emissions so revisions also order concurrent disconnects.
        # No game/user write locks are taken; business notifications run post-commit.
        with registry.lock:
            if game_id not in registry.views.values():
                return
            state = state if state is not None else game.get_game_state(game_id)
            members = {user['id'] for user in state['users']} | {int(uid) for uid in state['perf']}
            people = {}
            recipients = []
            for sid, viewed in list(registry.views.items()):
                if viewed != game_id:
                    continue
                identity = registry.entries.get(sid)
                fresh = auth.resolve_digest(identity.token_hash) if identity else None
                if fresh is None:
                    registry.remove(sid)
                    expired.append(sid)
                    continue
                recipients.append(sid)
                user = fresh.user
                if user['id'] not in members:
                    people[user['id']] = {
                        'id': user['id'],
                        'username': user['username'],
                        'rating': user['rating'],
                    }
            registry.presence_revision += 1
            if recipients:
                socketio.emit(
                    'game.presence',
                    {
                        'game_id': game_id,
                        'revision': registry.presence_revision,
                        'spectators': [people[uid] for uid in sorted(people)],
                    },
                    to=recipients,
                )
    except Exception:
        current_app.logger.exception('Presence broadcast failed game_id=%s', game_id)
    finally:
        # Entries were removed first: disconnect callbacks cannot recursively publish.
        for sid in expired:
            try:
                socketio.server.disconnect(sid, namespace='/')
            except Exception:
                current_app.logger.exception('Expired viewer eviction failed')


def publish_game_state(game_id):
    """Prune revoked/expired connections before broadcasting, including idle sockets."""
    try:
        for sid, identity in current_app.extensions['socket_connections'].snapshot():
            if auth.resolve_digest(identity.token_hash) is None:
                _disconnect(sid)
        state = game.get_game_state(game_id)
        socketio.emit('game.update', state, to=_room_for(game_id))
        _publish_presence(game_id, state)
    except Exception:
        # Notification failure does not undo a committed command; polling repairs state.
        current_app.logger.exception('Post-commit game broadcast failed game_id=%s', game_id)


def _join_connected(game_id):
    """A disconnect during the preceding database work is not a server failure."""
    try:
        join_room(_room_for(game_id))
        return True
    except ValueError:
        if socketio.server.manager.is_connected(request.sid, '/'):
            raise  # Do not conceal an unrelated room/manager failure.
        return False


def _identity():
    return auth.resolve_session(request.cookies.get(current_app.config['AUTH_COOKIE_NAME']))


def _authenticated(handler):
    @wraps(handler)
    def wrapped(data):
        try:
            identity = _identity()  # No per-connection identity cache for authorization.
            if identity is None:
                raise ApiError('Authentication required', 401, 'unauthenticated')
            if not isinstance(data, dict):
                raise ApiError('Expected an object')
            validate_csrf(identity, data.get('csrf_token', ''))
            game_id = positive_int(data, 'game_id')
            return handler(data, identity.user['id'], game_id)
        except ApiError as error:
            payload = error.payload()
            emit('game.error', payload)
            if error.status == 401:
                _disconnect(request.sid)
            return payload
        except Exception:
            current_app.logger.exception('Game socket event failed')
            payload = {'success': False, 'code': 'server_error', 'message': 'Server error'}
            emit('game.error', payload)
            return payload

    return wrapped


def register_handlers(server, app):
    registry = Connections()
    app.extensions['socket_connections'] = registry

    def connect(data=None):
        try:
            validate_origin()
            identity = _identity()
            if identity is None or not isinstance(data, dict):
                return False
            validate_csrf(identity, data.get('csrf_token', ''))
            registry.add(request.sid, identity)
        except ApiError:
            return False
        except Exception:
            current_app.logger.exception('Socket authentication failed')
            return False

    def disconnect(reason=None):
        game_id = registry.remove(request.sid)
        if game_id is not None:
            _publish_presence(game_id)

    @_authenticated
    def subscribe(data, uid, game_id):
        state = game.get_game_state(game_id)
        with registry.lock:
            if request.sid in registry.entries and _join_connected(game_id):
                previous = registry.views.get(request.sid)
                if previous is not None and previous != game_id:
                    leave_room(_room_for(previous))
                registry.views[request.sid] = game_id
                emit('game.update', state)
                _publish_presence(game_id, state)
                if previous is not None and previous != game_id:
                    _publish_presence(previous)
        return {'success': True}

    @_authenticated
    def answer(data, uid, game_id):
        result = game.answer_game(
            game_id,
            uid,
            positive_int(data, 'word_id'),
            text(data, 'answer'),
            **command_options(data),
        )
        publish_game_state(game_id)
        payload = {'success': True, **result}
        emit('game.answer_result', payload)
        return payload

    def command_handler(operation):
        @_authenticated
        def command(data, uid, game_id):
            result = operation(game_id, uid, **command_options(data))
            if operation is game.join_game:
                _join_connected(game_id)
            publish_game_state(game_id)
            return {'success': True, **result}

        return command

    server.on_event('connect', connect)
    server.on_event('disconnect', disconnect)
    server.on_event('game.subscribe', subscribe)
    server.on_event('game.answer', answer)
    for name, operation in (
        ('join', game.join_game),
        ('leave', game.leave_game),
        ('start', game.start_game),
        ('cancel', game.cancel_game),
        ('end', game.end_game),
    ):
        server.on_event(f'game.{name}', command_handler(operation))
