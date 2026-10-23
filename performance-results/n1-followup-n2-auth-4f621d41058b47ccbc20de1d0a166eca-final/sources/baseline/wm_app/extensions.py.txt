from flask_socketio import SocketIO

# Missing dependencies and handler initialization errors must fail startup.
# No wildcard CORS: Engine.IO checks the request origin by default.
socketio = SocketIO(async_mode='threading')
