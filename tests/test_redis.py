import sys
import os
import json
from unittest.mock import patch, MagicMock

import pytest
from flask import Flask

# ----------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

# Mock the redis module BEFORE importing any smart_app modules
mock_redis = MagicMock()
sys.modules["redis"] = mock_redis
sys.modules["smart_app.backend.routes.redis.redis"] = mock_redis

from smart_app.backend.routes.redis import redis_bp

# ----------------------------------------------------------------------


@pytest.fixture
def app():
    app = Flask(__name__)
    app.register_blueprint(redis_bp, url_prefix="/api/redis")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_redis_connection_success(client):
    with patch("smart_app.backend.routes.redis.redis.Redis") as MockRedis:
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

        mock_redis_instance.set.assert_called_once_with("test", "ok")
        mock_redis_instance.get.assert_called_once_with("test")


def test_redis_connection_failure(client):
    with patch("smart_app.backend.routes.redis.redis.Redis") as MockRedis:
        MockRedis.side_effect = Exception("Connection refused")

        response = client.get("/api/redis/test-connection")
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["status"] == "error"
        assert "Connection refused" in data["message"]


def test_redis_operation_failure(client):
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
    with patch("smart_app.backend.routes.redis.redis.Redis") as MockRedis:
        mock_redis_instance = MagicMock()
        mock_redis_instance.set.return_value = True
        mock_redis_instance.get.return_value = None
        MockRedis.return_value = mock_redis_instance

        response = client.get("/api/redis/test-connection")
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["status"] == "success"
        assert data["test_value"] is None
