"""Serve only explicitly migrated pages; never use a catch-all SPA fallback."""

from pathlib import Path

from flask import Blueprint, abort, current_app, send_from_directory

bp = Blueprint('frontend', __name__)


def frontend_directory():
    return Path(current_app.config['FRONTEND_DIST']).resolve()


def frontend_page():
    directory = frontend_directory()
    if not (directory / 'index.html').is_file():
        abort(503, description='Frontend build missing. Run npm ci && npm run build in frontend/.')
    response = send_from_directory(directory, 'index.html', max_age=0)
    response.headers['Cache-Control'] = 'no-store'
    return response


@bp.get('/ui/assets/<path:filename>')
def frontend_asset(filename):
    # send_from_directory prevents path traversal; missing assets remain 404.
    response = send_from_directory(frontend_directory() / 'assets', filename, max_age=31536000)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response
