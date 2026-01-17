from flask import Flask
from flask_socketio import SocketIO

socketio = SocketIO()  # Not bound yet

def create_app():
    app = Flask(__name__)
    app.secret_key = "dev"

    # bind socketio to app
    socketio.init_app(app)

    # import routes AFTER socketio is created
    from flaskr.routes import bp
    app.register_blueprint(bp)

    return app