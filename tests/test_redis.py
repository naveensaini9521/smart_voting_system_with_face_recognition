# tests/test_redis.py
import sys
import os
from unittest.mock import patch, MagicMock

# Add project root to Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

# Mock the redis module BEFORE importing any smart_app modules
mock_redis = MagicMock()
sys.modules["redis"] = mock_redis
# Also mock other potential dependencies
sys.modules["smart_app.backend.routes.redis.redis"] = mock_redis

import json
import pytest
from flask import Flask

# Import your Redis blueprint (adjust the import path as needed)
# For example, if your route is in smart_app/backend/routes/redis.py
from smart_app.backend.routes.redis import redis_bp


@pytest.fixture
def app():
    """Create a Flask app with the redis blueprint registered."""
    app = Flask(__name__)
    app.register_blueprint(redis_bp, url_prefix="/api/redis")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


def test_redis_connection_success(client):
    """Test Redis connection route when everything works."""
    with patch("smart_app.backend.routes.redis.redis.Redis") as MockRedis:
        # Create a mock Redis instance
        mock_redis_instance = MagicMock()
        mock_redis_instance.set.return_value = True
        mock_redis_instance.get.return_value = "ok"
        MockRedis.return_value = mock_redis_instance

        response = client.get("/api/redis/test-connection")
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["status"] == "success"
        assert data["message"] == "Redis connection successful"
        assert data["test_key"] == "test"
        assert data["test_value"] == "ok"

        # Verify the Redis operations were called
        mock_redis_instance.set.assert_called_once_with("test", "ok")
        mock_redis_instance.get.assert_called_once_with("test")


def test_redis_connection_failure(client):
    """Test Redis connection when an exception occurs."""
    with patch("smart_app.backend.routes.redis.redis.Redis") as MockRedis:
        MockRedis.side_effect = Exception("Connection refused")

        response = client.get("/api/redis/test-connection")
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["status"] == "error"
        assert "Connection refused" in data["message"]


def test_redis_operation_failure(client):
    """Test when Redis set operation fails."""
    with patch("smart_app.backend.routes.redis.redis.Redis") as MockRedis:
        mock_redis_instance = MagicMock()
        mock_redis_instance.set.side_effect = Exception("SET command failed")
        MockRedis.return_value = mock_redis_instance

        response = client.get("/api/redis/test-connection")
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["status"] == "error"
        assert "SET command failed" in data["message"]


def test_redis_get_none(client):
    """Test when Redis get returns None (key not found)."""
    with patch("smart_app.backend.routes.redis.redis.Redis") as MockRedis:
        mock_redis_instance = MagicMock()
        mock_redis_instance.set.return_value = True
        mock_redis_instance.get.return_value = None
        MockRedis.return_value = mock_redis_instance

        response = client.get("/api/redis/test-connection")
        data = json.loads(response.data)

        # Depending on your endpoint logic, this might still be success
        assert response.status_code == 200
        assert data["status"] == "success"
        assert data["test_value"] is None
