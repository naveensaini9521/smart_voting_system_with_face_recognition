import sys
import os
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from flask import Flask

# ----------------------------------------------------------------------
# Path setup (must happen before importing project modules)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "smart_app", "backend")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, BACKEND_DIR)

# Mock modules that auth.py tries to import but are not in the right location
mock_mongo_models = MagicMock()
mock_face_recognition_service = MagicMock()
sys.modules["mongo_models"] = mock_mongo_models
sys.modules["services.face_recognition_service"] = mock_face_recognition_service

# Now it's safe to import auth
from smart_app.backend.routes.auth import (
    auth_bp,
    JWT_SECRET,
    JWT_ALGORITHM,
)  # noqa: E402

# ----------------------------------------------------------------------


@pytest.fixture
def app():
    """Create a Flask app with the auth blueprint registered."""
    app = Flask(__name__)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def mock_voter():
    """Return a mock voter document."""
    return {
        "voter_id": "V12345",
        "full_name": "Test Voter",
        "email": "voter@example.com",
        "phone": "1234567890",
        "password_hash": "hashed_password",
        "gender": "Male",
        "date_of_birth": "1990-01-01",
        "address_line1": "123 Main St",
        "village_city": "Test City",
        "district": "Test District",
        "state": "Test State",
        "pincode": "123456",
        "national_id_type": "Aadhaar",
        "national_id_number": "1234-5678-9012",
        "constituency": "Test Constituency",
        "polling_station": "Test School",
        "registration_status": "completed",
        "is_active": True,
        "email_verified": True,
        "phone_verified": True,
        "id_verified": True,
        "face_verified": True,
        "face_encoding_id": "enc_123",
        "created_at": datetime.utcnow(),
        "last_login": None,
    }


@pytest.fixture
def mock_admin():
    """Return a mock admin document."""
    return {
        "admin_id": "A100",
        "username": "admin_user",
        "full_name": "Admin User",
        "email": "admin@example.com",
        "password_hash": "hashed_admin_pass",
        "role": "admin",
        "permissions": {"manage_voters": True},
        "department": "Election",
        "access_level": 2,
        "is_active": True,
        "last_login": None,
    }


@pytest.fixture
def valid_voter_token(mock_voter):
    """Generate a valid JWT token for a voter."""
    payload = {
        "user_id": mock_voter["voter_id"],
        "voter_id": mock_voter["voter_id"],
        "email": mock_voter["email"],
        "user_type": "voter",
        "exp": datetime.utcnow() + timedelta(hours=1),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


@pytest.fixture
def valid_admin_token(mock_admin):
    """Generate a valid JWT token for an admin."""
    payload = {
        "user_id": mock_admin["admin_id"],
        "admin_id": mock_admin["admin_id"],
        "username": mock_admin["username"],
        "email": mock_admin["email"],
        "user_type": "admin",
        "role": mock_admin["role"],
        "exp": datetime.utcnow() + timedelta(hours=1),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# -------------------- Tests for /api/auth/login --------------------
class TestLogin:
    def test_login_success(self, client, mock_voter):
        with patch("smart_app.backend.routes.auth.Voter") as MockVoter:
            MockVoter.find_by_voter_id.return_value = mock_voter
            MockVoter.verify_password.return_value = True
            MockVoter.update_one = MagicMock()

            response = client.post(
                "/api/auth/login",
                json={"voter_id": "V12345", "password": "correct_password"},
            )
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            assert data["requires_face_verification"] is True
            assert "temp_token" in data
            assert data["voter_data"]["voter_id"] == "V12345"

    def test_login_missing_fields(self, client):
        response = client.post("/api/auth/login", json={"voter_id": "V12345"})
        data = json.loads(response.data)

        assert response.status_code == 400
        assert data["success"] is False
        assert "password are required" in data["message"]

    def test_login_invalid_credentials(self, client, mock_voter):
        with patch("smart_app.backend.routes.auth.Voter") as MockVoter:
            MockVoter.find_by_voter_id.return_value = mock_voter
            MockVoter.verify_password.return_value = False

            response = client.post(
                "/api/auth/login", json={"voter_id": "V12345", "password": "wrong"}
            )
            data = json.loads(response.data)

            assert response.status_code == 401
            assert data["success"] is False
            assert "Invalid Voter ID or password" in data["message"]

    def test_login_inactive_voter(self, client, mock_voter):
        mock_voter["is_active"] = False
        with patch("smart_app.backend.routes.auth.Voter") as MockVoter:
            MockVoter.find_by_voter_id.return_value = mock_voter
            MockVoter.verify_password.return_value = True

            response = client.post(
                "/api/auth/login", json={"voter_id": "V12345", "password": "pass"}
            )
            data = json.loads(response.data)

            assert response.status_code == 401
            assert "deactivated" in data["message"]


# -------------------- Tests for /api/auth/verify-face-hybrid --------------------
class TestVerifyFaceHybrid:
    def test_face_verification_success(self, client, mock_voter):
        with patch("smart_app.backend.routes.auth.Voter") as MockVoter, patch(
            "smart_app.backend.routes.auth.FaceRecognitionResult"
        ) as MockResult, patch(
            "smart_app.backend.routes.auth.AuditLog"
        ) as MockAuditLog:
            MockVoter.find_by_voter_id.return_value = mock_voter
            MockVoter.update_one = MagicMock()

            mock_result = MagicMock()
            mock_result.is_match = True
            mock_result.confidence = 0.95
            mock_result.method = "temporary_bypass"
            mock_result.processing_time = 0.1
            mock_result.quality_score = 0.9
            mock_result.details = {}
            MockResult.return_value = mock_result

            response = client.post(
                "/api/auth/verify-face-hybrid",
                json={"voter_id": "V12345", "image_data": "base64_encoded_image"},
            )
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            assert data["confidence"] == 0.95
            assert "token" in data
            assert "auth_token" in data
            MockAuditLog.create_log.assert_called_once()

    def test_face_verification_voter_not_found(self, client):
        with patch("smart_app.backend.routes.auth.Voter") as MockVoter:
            MockVoter.find_by_voter_id.return_value = None

            response = client.post(
                "/api/auth/verify-face-hybrid",
                json={"voter_id": "V99999", "image_data": "data"},
            )
            data = json.loads(response.data)

            assert response.status_code == 404
            assert data["success"] is False
            assert "Voter not found" in data["message"]

    def test_face_verification_no_face_registered(self, client, mock_voter):
        mock_voter["face_verified"] = False
        mock_voter["face_encoding_id"] = None
        with patch("smart_app.backend.routes.auth.Voter") as MockVoter:
            MockVoter.find_by_voter_id.return_value = mock_voter

            response = client.post(
                "/api/auth/verify-face-hybrid",
                json={"voter_id": "V12345", "image_data": "data"},
            )
            data = json.loads(response.data)

            assert response.status_code == 400
            assert "Face biometrics not registered" in data["message"]

    def test_face_verification_missing_data(self, client):
        response = client.post("/api/auth/verify-face-hybrid", json={"voter_id": "V1"})
        data = json.loads(response.data)

        assert response.status_code == 400
        assert "Voter ID and image data are required" in data["message"]


# -------------------- Tests for admin endpoints --------------------
class TestAdminLogin:
    def test_admin_login_success(self, client, mock_admin):
        with patch("smart_app.backend.routes.auth.Admin") as MockAdmin, patch(
            "smart_app.backend.routes.auth.AuditLog"
        ) as MockAuditLog:
            MockAdmin.find_by_username.return_value = mock_admin
            MockAdmin.verify_password.return_value = True
            MockAdmin.update_one = MagicMock()

            response = client.post(
                "/api/auth/admin/login",
                json={"username": "admin_user", "password": "admin_pass"},
            )
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            assert "token" in data
            assert data["admin_data"]["username"] == "admin_user"
            MockAuditLog.create_log.assert_called_once()

    def test_admin_login_invalid_credentials(self, client, mock_admin):
        with patch("smart_app.backend.routes.auth.Admin") as MockAdmin:
            MockAdmin.find_by_username.return_value = mock_admin
            MockAdmin.verify_password.return_value = False

            response = client.post(
                "/api/auth/admin/login",
                json={"username": "admin_user", "password": "wrong"},
            )
            data = json.loads(response.data)

            assert response.status_code == 401
            assert data["success"] is False

    def test_admin_login_inactive(self, client, mock_admin):
        mock_admin["is_active"] = False
        with patch("smart_app.backend.routes.auth.Admin") as MockAdmin:
            MockAdmin.find_by_username.return_value = mock_admin
            MockAdmin.verify_password.return_value = True

            response = client.post(
                "/api/auth/admin/login",
                json={"username": "admin_user", "password": "pass"},
            )
            data = json.loads(response.data)

            assert response.status_code == 401
            assert "deactivated" in data["message"]


class TestAdminVerifyToken:
    def test_admin_verify_token_valid(self, client, valid_admin_token):
        with patch("smart_app.backend.routes.auth.Admin") as MockAdmin, patch(
            "smart_app.backend.routes.auth.verify_token"
        ) as mock_verify:
            mock_verify.return_value = {
                "user_type": "admin",
                "admin_id": "A100",
                "username": "admin_user",
            }
            mock_admin_instance = {
                "admin_id": "A100",
                "username": "admin_user",
                "full_name": "Admin User",
                "email": "admin@example.com",
                "role": "admin",
                "permissions": {},
                "department": None,
                "access_level": 1,
            }
            MockAdmin.find_by_admin_id.return_value = mock_admin_instance

            response = client.get(
                "/api/auth/admin/verify-token",
                headers={"Authorization": f"Bearer {valid_admin_token}"},
            )
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            assert data["admin_data"]["admin_id"] == "A100"

    def test_admin_verify_token_missing(self, client):
        response = client.get("/api/auth/admin/verify-token")
        data = json.loads(response.data)

        assert response.status_code == 401
        assert "No token provided" in data["message"]


class TestAdminLogout:
    def test_admin_logout(self, client, valid_admin_token):
        with patch("smart_app.backend.routes.auth.verify_token") as mock_verify, patch(
            "smart_app.backend.routes.auth.AuditLog"
        ) as MockAuditLog:
            mock_verify.return_value = {"admin_id": "A100", "username": "admin_user"}
            response = client.post(
                "/api/auth/admin/logout",
                headers={"Authorization": f"Bearer {valid_admin_token}"},
            )
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            MockAuditLog.create_log.assert_called_once()


# -------------------- Tests for generic auth helpers --------------------
class TestCheckAuth:
    def test_check_auth_voter_valid(self, client, valid_voter_token, mock_voter):
        with patch("smart_app.backend.routes.auth.verify_token") as mock_verify, patch(
            "smart_app.backend.routes.auth.Voter"
        ) as MockVoter:
            mock_verify.return_value = {
                "user_type": "voter",
                "voter_id": "V12345",
                "user_id": "V12345",
            }
            MockVoter.find_by_voter_id.return_value = mock_voter

            response = client.get(
                "/api/auth/check-auth",
                headers={"Authorization": f"Bearer {valid_voter_token}"},
            )
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            assert data["user_type"] == "voter"

    def test_check_auth_no_token(self, client):
        response = client.get("/api/auth/check-auth")
        data = json.loads(response.data)

        assert response.status_code == 401
        assert "No token provided" in data["message"]


class TestVerifyTokenRoute:
    def test_verify_token_route_valid(self, client, valid_voter_token):
        with patch("smart_app.backend.routes.auth.verify_token") as mock_verify:
            mock_verify.return_value = {
                "user_type": "voter",
                "voter_id": "V12345",
                "user_id": "V12345",
                "email": "voter@example.com",
            }
            response = client.get(
                "/api/auth/verify-token",
                headers={"Authorization": f"Bearer {valid_voter_token}"},
            )
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            assert data["voter_id"] == "V12345"


# -------------------- Debug endpoints --------------------
class TestDebugEndpoints:
    def test_debug_voters(self, client):
        with patch("smart_app.backend.mongo_models.Voter") as MockVoter:
            mock_voter_list = [
                {
                    "voter_id": "V1",
                    "full_name": "Test",
                    "email": "t@t.com",
                    "date_of_birth": "1990-01-01",
                    "password_hash": "hash",
                }
            ]
            MockVoter.find_all.return_value = mock_voter_list
            response = client.get("/api/auth/debug/voters")
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            assert data["total_voters"] == 1
            MockVoter.find_all.assert_called_once()

    def test_debug_face_status(self, client, mock_voter):
        with patch("smart_app.backend.routes.auth.Voter") as MockVoter, patch(
            "smart_app.backend.routes.auth.FaceEncoding"
        ) as MockFaceEncoding:
            MockVoter.find_by_voter_id.return_value = mock_voter
            MockFaceEncoding.find_by_id.return_value = {"encoding_type": "dlib"}
            response = client.get("/api/auth/debug/face-status/V12345")
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            assert data["face_verified"] is True
            assert data["has_face_encoding"] is True
            assert data["face_encoding_type"] == "dlib"

    def test_debug_simulate_login(self, client, mock_voter):
        with patch("smart_app.backend.routes.auth.Voter") as MockVoter:
            MockVoter.find_by_voter_id.return_value = mock_voter
            response = client.get("/api/auth/debug/simulate-login/V12345")
            data = json.loads(response.data)

            assert response.status_code == 200
            assert data["success"] is True
            assert "token" in data


# -------------------- Health and test routes --------------------
def test_health_check(client):
    response = client.get("/api/auth/health")
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data["success"] is True


def test_test_route(client):
    response = client.get("/api/auth/test")
    data = json.loads(response.data)
    assert response.status_code == 200
    assert data["success"] is True
