import logging
import uuid

from flask import g, jsonify, request
from pymysql import MySQLError
from werkzeug.exceptions import HTTPException

from .services.errors import ApiError


def configure_logging(app):
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    app.logger.handlers = [handler]
    app.logger.setLevel(app.config['LOG_LEVEL'])

    @app.before_request
    def assign_request_id():
        g.request_id = uuid.uuid4().hex

    @app.after_request
    def log_response(response):
        response.headers['X-Request-ID'] = g.request_id
        # Never log query strings, cookies, request bodies or password hashes.
        app.logger.info(
            'request_id=%s method=%s path=%s status=%s',
            g.request_id,
            request.method,
            request.path,
            response.status_code,
        )
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        if not request.path.startswith('/api/'):
            return error
        return jsonify(
            success=False, code=error.name.lower().replace(' ', '_'), message=error.description
        ), error.code

    @app.errorhandler(ApiError)
    def business_error(error):
        response = jsonify(error.payload())
        response.status_code = error.status
        if error.status == 429:
            response.headers['Retry-After'] = str(error.details['retry_after'])
        return response

    @app.errorhandler(MySQLError)
    def database_error(error):
        app.logger.exception('Database operation failed request_id=%s', g.get('request_id'))
        return jsonify(
            success=False,
            code='database_unavailable',
            message='Database unavailable; check configuration and migrations',
        ), 503

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception('Unhandled request error request_id=%s', g.get('request_id'))
        return jsonify(success=False, code='server_error', message='Server error'), 500
