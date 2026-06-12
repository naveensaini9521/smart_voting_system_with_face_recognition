from flask_bcrypt import Bcrypt
from flask_caching import Cache
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_mail import Mail
from flask_pymongo import PyMongo
from flask_socketio import SocketIO

mongo = PyMongo()
jwt = JWTManager()
mail = Mail()
cors = CORS()
bcrypt = Bcrypt()
cache = Cache()

socketio = SocketIO(
    cors_allowed_origins="*", async_mode="gevent", logger=False, engineio_logger=False
)
