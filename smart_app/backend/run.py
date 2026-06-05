import logging
from app import create_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app, socketio = create_app()

if __name__ == "__main__":
    print("=" * 50)
    print("Starting Smart Voting System (Docker Ready)")
    print("Server: http://0.0.0.0:5000")
    print("=" * 50)

    socketio.run(
        app,
        host="0.0.0.0",
        port=5001,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True
    )