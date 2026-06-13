import sys
import os
import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

# ----------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

# Mock the mongo module BEFORE importing any smart_app modules
mock_mongo = MagicMock()
sys.modules["smart_app.backend.routes.mongodb.mongo"] = mock_mongo
sys.modules["mongo_models"] = MagicMock()

from smart_app.backend.routes.mongodb import mongodb_bp  # noqa: E402


@pytest.fixture
def app():
    app = Flask(__name__)
    app.register_blueprint(mongodb_bp, url_prefix="/api/mongodb")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_mongodb_connection_success(client):
    with patch("smart_app.backend.routes.mongodb.mongo") as mock_mongo:
        mock_mongo.db.list_collection_names.return_value = ["users", "voters"]
        mock_mongo.db.command.return_value = {
            "collections": 2,
            "objects": 150,
            "dataSize": 50000,
        }
        mock_mongo.db.name = "smart_voting_db"

        response = client.get("/api/mongodb/test-connection")
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["status"] == "success"
        assert data["database"] == "smart_voting_db"
        assert data["stats"]["collections"] == 2
        assert data["stats"]["objects"] == 150
        assert data["stats"]["dataSize"] == 50000


def test_mongodb_connection_no_collections(client):
    with patch("smart_app.backend.routes.mongodb.mongo") as mock_mongo:
        mock_mongo.db.list_collection_names.return_value = []
        mock_mongo.db.command.return_value = {
            "collections": 0,
            "objects": 0,
            "dataSize": 0,
        }
        mock_mongo.db.name = "empty_db"

        response = client.get("/api/mongodb/test-connection")
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["status"] == "success"
        assert data["stats"]["collections"] == 0
        assert data["stats"]["objects"] == 0


def test_mongodb_connection_exception(client):
    with patch("smart_app.backend.routes.mongodb.mongo") as mock_mongo:
        mock_mongo.db.list_collection_names.side_effect = Exception(
            "Connection refused"
        )

        response = client.get("/api/mongodb/test-connection")
        data = json.loads(response.data)

        assert response.status_code == 500
        assert data["status"] == "error"
        assert "Connection refused" in data["message"]


def test_mongodb_connection_missing_dbstats(client):
    with patch("smart_app.backend.routes.mongodb.mongo") as mock_mongo:
        mock_mongo.db.list_collection_names.return_value = ["users"]
        mock_mongo.db.command.return_value = {
            "collections": 0,
            "objects": 10,
            "dataSize": 0,
        }
        mock_mongo.db.name = "test_db"

        response = client.get("/api/mongodb/test-connection")
        data = json.loads(response.data)

        assert response.status_code == 200
        assert data["status"] == "success"
        assert data["database"] == "test_db"
        assert data["stats"]["collections"] == 0
        assert data["stats"]["objects"] == 10
