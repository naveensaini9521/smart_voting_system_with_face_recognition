from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
import os
from datetime import datetime
from config import config_map, DevelopmentConfig 
from flask_socketio import SocketIO
from extensions import mongo, jwt, mail, bcrypt, socketio
from create_mongo_collections import create_collections
from routes.auth import auth_bp
from routes.voters import voting_bp
from routes.admin import admin_bp
from routes.otp import otp_bp
from frontend import frontend_bp  
from routes.register import register_bp
from routes.stats import stats_bp
from routes.home import home_bp  
from routes.test_mongodb import mongodb_bp 
from routes.dashboard import dashboard_bp
from routes.elections import election_bp
from socket_events import register_socket_events
from dotenv import load_dotenv

load_dotenv()

def create_app():

    app = Flask(__name__, instance_relative_config=True)

    env = os.getenv("ENVIRONMENT", "DEVELOPMENT")
    app.config.from_object(config_map.get(env, DevelopmentConfig))
    
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

    os.makedirs(app.config.get("UPLOAD_FOLDER", "uploads"), exist_ok=True)
    
    CORS(app, 
        origins=[
            "http://localhost:5000",
            "http://127.0.0.1:5000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",     
            "http://127.0.0.1:3001",    
            "http://localhost:5173",
            "http://127.0.0.1:5173"
        ],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        supports_credentials=True)

    # extensions
    mongo.init_app(app)
    jwt.init_app(app)
    mail.init_app(app)
    bcrypt.init_app(app)
    
    app.connected_clients = {}
    
    socketio.init_app(
    app, 
    cors_allowed_origins="*",
    # async_mode="threading",
    async_mode="gevent",
    logger=True,
    engineio_logger=True,
    transports=['polling', 'websocket'], 
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1e8,
    allow_upgrades=True,
    http_compression=True,
    cookie=None
)


    register_socket_events(socketio)

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(voting_bp, url_prefix="/api/voter")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(otp_bp, url_prefix="/api/otp")
    app.register_blueprint(register_bp, url_prefix='/api/register')
    app.register_blueprint(stats_bp, url_prefix="/api")
    app.register_blueprint(home_bp, url_prefix="/api/home")
    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(election_bp, url_prefix='/api/election')
    app.register_blueprint(mongodb_bp, url_prefix="/api/mongodb")

    # Register React frontend 
    app.register_blueprint(frontend_bp)


    # Global error handlers 
    @app.errorhandler(404)
    def api_not_found(error):
        if request.path.startswith('/api/'):
            return jsonify({'message': 'API resource not found'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'message': 'Internal server error'}), 500

    @app.route('/api/test')
    def test_api():
        return jsonify({'message': 'API is working!', 'status': 'success'})

    @app.route('/api/socket-health')
    def socket_health():
        return jsonify({
            'message': 'Socket.IO is available!', 
            'status': 'success',
            'connected_clients': len(getattr(socketio, 'connected_clients', {}))
        })
    

    @app.route('/api/socket-debug')
    def socket_debug():
        """Debug Socket.IO connection issues"""
        return jsonify({
            'server_info': {
                'flask_env': app.config.get('ENV', 'unknown'),
                'debug': app.config.get('DEBUG', False),
                'socketio_async_mode': getattr(socketio, 'async_mode', 'unknown'),
            },
            'client_advice': {
                'recommended_transports': ['polling', 'websocket'],
                'connection_url': f'ws://{request.host}/socket.io/',
                'api_base': f'http://{request.host}/api/'
            }
        })

    @app.route('/api/websocket-test')
    def websocket_test():
        """Test if WebSocket connections are working"""
        return jsonify({
            'message': 'WebSocket test endpoint',
            'timestamp': datetime.utcnow().isoformat(),
            'server_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        })
    # Create tables
    with app.app_context():
        try:
            create_collections(app)
            # Test MongoDB connection
            mongo.db.command('ping')
            collections = mongo.db.list_collection_names()
            print(f"MongoDB connected. Available collections: {collections}")
        except Exception as e:
            print(f"MongoDB connection issue: {str(e)}")
            print("Continuing without MongoDB collections - some features may not work")
        
    return app, socketio