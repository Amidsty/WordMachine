import hmac
import secrets
from functools import wraps
from urllib.parse import urlsplit

from flask import current_app, g, redirect, request, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..services import auth
from ..services.errors import ApiError
from .permissions import require_root

SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


def request_identity():
    if 'identity' not in g:
        g.identity = auth.resolve_session(
            request.cookies.get(current_app.config['AUTH_COOKIE_NAME'])
        )
    return g.identity


def validate_origin():
    if request.headers.get('Sec-Fetch-Site') == 'cross-site':
        raise ApiError('Cross-site request rejected', 403, 'csrf_failed')
    origin = request.headers.get('Origin')
    if origin:
        try:
            parsed, expected = urlsplit(origin), urlsplit(request.host_url)

            def endpoint(url):
                return (
                    url.scheme.lower(),
                    url.hostname,
                    url.port or (443 if url.scheme == 'https' else 80),
                )

            valid = (
                origin != 'null'
                and not parsed.username
                and not parsed.password
                and not parsed.query
                and not parsed.fragment
                and parsed.path in ('', '/')
                and endpoint(parsed) == endpoint(expected)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ApiError('Origin does not match this server', 403, 'csrf_failed')


def _serializer():
    return URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'], salt='wordmachine-anonymous-csrf'
    )


def valid_anonymous_csrf(token):
    if not isinstance(token, str) or len(token) > 256:
        return False
    try:
        payload = _serializer().loads(token, max_age=current_app.config['CSRF_SECONDS'])
        return isinstance(payload, str) and len(payload) == 64
    except (BadSignature, SignatureExpired):
        return False


def anonymous_csrf():
    token = request.cookies.get(current_app.config['CSRF_COOKIE_NAME'])
    return token if valid_anonymous_csrf(token) else _serializer().dumps(secrets.token_hex(32))


def validate_csrf(identity, supplied=None):
    validate_origin()
    supplied = request.headers.get('X-CSRF-Token') if supplied is None else supplied
    expected = (
        identity.csrf_token
        if identity
        else request.cookies.get(current_app.config['CSRF_COOKIE_NAME'])
    )
    if (
        not isinstance(supplied, str)
        or not isinstance(expected, str)
        or len(supplied) > 256
        or not supplied.isascii()
        or not expected.isascii()
        or not hmac.compare_digest(supplied, expected)
    ):
        raise ApiError('Invalid or missing CSRF token', 403, 'csrf_failed')
    if identity is None and not valid_anonymous_csrf(expected):
        raise ApiError('Expired CSRF token', 403, 'csrf_failed')


def cookie_options():
    return {
        'httponly': True,
        'secure': current_app.config['SESSION_COOKIE_SECURE'],
        'samesite': 'Lax',
        'path': '/',
    }


def clear_login_cookie(response):
    response.delete_cookie(current_app.config['AUTH_COOKIE_NAME'], **cookie_options())


def issue_login_cookie(response, token):
    response.set_cookie(
        current_app.config['AUTH_COOKIE_NAME'],
        token,
        max_age=current_app.config['AUTH_SESSION_SECONDS'],
        **cookie_options(),
    )
    response.delete_cookie(current_app.config['CSRF_COOKIE_NAME'], **cookie_options())


def issue_anonymous_cookie(response, token):
    response.set_cookie(
        current_app.config['CSRF_COOKIE_NAME'],
        token,
        max_age=current_app.config['CSRF_SECONDS'],
        **cookie_options(),
    )


def read_json():
    if not request.get_data(cache=True):
        return {}
    if not request.is_json:
        raise ApiError('Expected application/json')
    data = request.get_json()
    if not isinstance(data, dict):
        raise ApiError('Expected a JSON object')
    return data


def api_endpoint(*, authenticated=True, root=False):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            identity = request_identity()
            if authenticated and identity is None:
                raise ApiError('Authentication required', 401, 'unauthenticated')
            if request.method not in SAFE_METHODS:
                validate_csrf(identity)
            user = identity.user if identity else None
            if root:
                require_root(user)
            data = request.args if request.method in SAFE_METHODS else read_json()
            return view(data, user, *args, **kwargs)

        return wrapped

    return decorate


def page_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if request_identity() is None:
            return redirect(url_for('main.login', next=request.path))
        return view(*args, **kwargs)

    return wrapped


def configure_security(app):
    @app.after_request
    def security_headers(response):
        if request.path.startswith('/api/') or response.mimetype == 'text/html':
            response.headers['Cache-Control'] = 'no-store'
            response.vary.add('Cookie')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        # One-way retirement: old credential cookies are never read for identity.
        for legacy_name in ('uid', 'pwhash'):
            if legacy_name in request.cookies:
                response.delete_cookie(legacy_name, path='/')
        return response
