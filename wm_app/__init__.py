import secrets

from flask import Flask, jsonify

from .config import load_config, validate_config
from .db import reading
from .extensions import socketio
from .observability import configure_logging
from .security.http import configure_security


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(load_config())
    if config:
        app.config.update(config)
    validate_config(app.config)
    app.json.sort_keys = False
    configure_logging(app)
    if not app.config['SECRET_KEY']:
        app.config['SECRET_KEY'] = secrets.token_hex(32)
        app.logger.warning(
            'Using a temporary development secret; set WM_SECRET_KEY for persistent CSRF tokens and rate limits'
        )
    configure_security(app)

    from .frontend import bp as frontend_bp
    from .routes_admin import bp as admin_bp
    from .routes_auth import bp as auth_bp
    from .routes_dict import bp as dict_bp
    from .routes_game import bp as game_bp
    from .routes_main import bp as main_bp

    for bp in (frontend_bp, main_bp, auth_bp, admin_bp, dict_bp, game_bp):
        app.register_blueprint(bp)

    socketio.init_app(app, manage_session=False)
    from .socket_game import register_handlers

    register_handlers(socketio, app)

    from .audit import audit_legacy_command

    app.cli.add_command(audit_legacy_command)
    from .cli import (
        convert_game_answers_command,
        convert_game_participants_command,
        create_admin_command,
        create_master_command,
        purge_auth_command,
    )

    app.cli.add_command(create_admin_command)
    app.cli.add_command(create_master_command)
    app.cli.add_command(purge_auth_command)
    app.cli.add_command(convert_game_participants_command)
    app.cli.add_command(convert_game_answers_command)

    @app.get('/health/live')
    def health_live():
        return jsonify(status='ok')

    @app.get('/health/ready')
    def health_ready():
        try:
            with reading() as cursor:
                cursor.execute('SELECT version_num FROM alembic_version')
                versions = {row['version_num'] for row in cursor.fetchall()}
                if versions != {'0019_manual_visibility'}:
                    return jsonify(status='migration_required'), 503
            return jsonify(status='ok')
        except Exception:
            app.logger.exception('Database readiness check failed')
            return jsonify(status='unavailable'), 503

    return app
