from flask import Flask
from unittest.mock import MagicMock, patch

from smart_app.backend.routes.mongodb import test_mongodb_connection


@patch("smart_app.backend.routes.mongodb.mongo")
def test_mongodb_route(mock_mongo):
    app = Flask(__name__)

    mock_mongo.db.list_collection_names.return_value = ["users"]
    mock_mongo.db.command.return_value = {
        "collections": 1,
        "objects": 10,
        "dataSize": 100,
    }
    mock_mongo.db.name = "testdb"

    with app.app_context():
        response = test_mongodb_connection()

    assert response.status_code == 200
