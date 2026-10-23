from wm_app import create_app, socketio

app = create_app()

if __name__ == '__main__':
    if app.config['ENVIRONMENT'] == 'production':
        raise RuntimeError('app.py is a development entry point; use a production WSGI server')
    socketio.run(
        app,
        host=app.config['HOST'],
        port=app.config['PORT'],
        debug=app.config['DEBUG'],
        allow_unsafe_werkzeug=True,
    )
