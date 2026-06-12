import base64
import csv
import hashlib
import io
import json
import logging
from datetime import datetime, timedelta
from functools import wraps

import jwt
import qrcode
from extensions import socketio
from flask import Blueprint, current_app, jsonify, request, send_file
from flask_cors import cross_origin
from flask_socketio import emit, join_room
from mongo_models import OTP, Admin, AuditLog, Candidate, Election, Vote, Voter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from socket_events import connected_clients, safe_emit  # keep imported

logger = logging.getLogger(__name__)

# Create blueprint
dashboard_bp = Blueprint("dashboard", __name__)

# JWT configuration (should match auth.py)
JWT_SECRET = "sUJbaMMUAKYojj0dFe94jO"
JWT_ALGORITHM = "HS256"


def verify_token(token):
    """Verify JWT token with better error handling and debugging"""
    try:
        if not token:
            logger.warning("No token provided")
            return None

        if token.startswith("Bearer "):
            token = token.split(" ")[1].strip()

        if not token:
            logger.warning("Empty token after Bearer prefix removal")
            return None

        logger.info(f"Verifying token: {token[:20]}...")

        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        logger.info(f"Token payload verified: {list(payload.keys())}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        return None


def get_authenticated_voter():
    """Get authenticated voter from token - SIMPLIFIED FIXED VERSION"""
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            print("No Authorization header")
            return None

        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        else:
            token = auth_header

        if not token:
            print("No token in Authorization header")
            return None

        print(f"Token received: {token[:50]}...")

        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            print(f"Token payload: {payload}")
        except jwt.ExpiredSignatureError:
            print("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            print(f"Invalid token: {str(e)}")
            return None

        voter_id = payload.get("voter_id")
        if not voter_id:
            print("No voter_id in token payload")
            return None

        print(f"Looking for voter with ID: {voter_id}")

        voter = Voter.find_by_voter_id(voter_id)
        if not voter:
            print(f"Voter not found: {voter_id}")
            return None

        print(f"Voter found: {voter['full_name']}")
        return voter

    except Exception as e:
        print(f"Error in get_authenticated_voter: {str(e)}")
        import traceback

        print(f"Traceback: {traceback.format_exc()}")
        return None


def get_authenticated_admin():
    """Get authenticated admin from token"""
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ")[1].strip()
        payload = verify_token(token)

        if not payload:
            return None

        admin_id = payload.get("admin_id")
        if not admin_id:
            return None

        admin = Admin.find_by_admin_id(admin_id)
        return admin
    except Exception as e:
        logger.error(f"Error in get_authenticated_admin: {str(e)}")
        return None


def voter_required(f):
    """Decorator to require voter authentication - ENHANCED VERSION"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == "OPTIONS":
            return jsonify({"status": "ok"}), 200

        try:
            voter = get_authenticated_voter()
            if not voter:
                logger.warning(f"Unauthorized access attempt to {request.path}")
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Voter authentication required",
                            "code": "AUTH_REQUIRED",
                        }
                    ),
                    401,
                )

            if not voter.get("is_active", True):
                logger.warning(f"Inactive voter attempt: {voter.get('voter_id')}")
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Your account is not active",
                            "code": "ACCOUNT_INACTIVE",
                        }
                    ),
                    403,
                )

            request.voter = voter
            return f(*args, **kwargs)

        except Exception as e:
            logger.error(f"Error in voter_required decorator: {str(e)}", exc_info=True)
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Authentication error",
                        "code": "AUTH_ERROR",
                    }
                ),
                401,
            )

    return decorated_function


def admin_required(f):
    """Decorator to require admin privileges"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        admin = get_authenticated_admin()
        if not admin:
            return (
                jsonify({"success": False, "message": "Admin authentication required"}),
                401,
            )
        request.admin = admin
        return f(*args, **kwargs)

    return decorated_function


def handle_voter_connection(voter_id):
    """Handle voter WebSocket connection - FIXED VERSION"""
    try:
        voter = Voter.find_by_voter_id(voter_id)
        if not voter:
            logger.warning(f"Voter not found: {voter_id}")
            emit("connection_error", {"message": "Voter not found"})
            return False

        join_room(f"voter_{voter_id}")
        join_room("all_voters")
        join_room("public_updates")

        connected_clients[request.sid] = {
            "type": "voter",
            "voter_id": voter_id,
            "connected_at": datetime.utcnow().isoformat(),
        }

        logger.info(f"Voter {voter_id} connected to SocketIO. SID: {request.sid}")

        emit(
            "connection_established",
            {
                "status": "connected",
                "message": "Real-time updates enabled",
                "user_type": "voter",
                "voter_id": voter_id,
                "sid": request.sid,
            },
        )

        return True

    except Exception as e:
        logger.error(f"Voter connection handler error: {str(e)}")
        emit("connection_error", {"message": "Voter connection failed"})
        return False


def handle_admin_connection(admin_id):
    """Handle admin WebSocket connection - FIXED VERSION"""
    try:
        admin = Admin.find_by_admin_id(admin_id)
        if not admin:
            logger.warning(f"Admin not found: {admin_id}")
            emit("connection_error", {"message": "Admin not found"})
            return False

        join_room(f"admin_{admin_id}")
        join_room("all_admins")
        join_room("public_updates")

        connected_clients[request.sid] = {
            "type": "admin",
            "admin_id": admin_id,
            "connected_at": datetime.utcnow().isoformat(),
        }

        logger.info(f"Admin {admin_id} connected to SocketIO. SID: {request.sid}")

        emit(
            "connection_established",
            {
                "status": "connected",
                "message": "Admin real-time updates enabled",
                "user_type": "admin",
                "admin_id": admin_id,
                "sid": request.sid,
            },
        )

        return True

    except Exception as e:
        logger.error(f"Admin connection handler error: {str(e)}")
        emit("connection_error", {"message": "Admin connection failed"})
        return False


def broadcast_election_update(action, election_data, admin_id=None):
    """Broadcast election updates to all connected clients"""
    try:
        update_data = {
            "type": "election",
            "action": action,
            "data": election_data,
            "timestamp": datetime.utcnow().isoformat(),
            "admin_id": admin_id,
        }

        safe_emit("election_update", update_data, room="all_voters")
        safe_emit(
            "election_update",
            update_data,
            room=f"election_{election_data.get('election_id')}",
        )
        safe_emit("election_update", update_data, room="all_admins")

        logger.info(
            f"Broadcasted election {action}: {election_data.get('election_id')}"
        )

    except Exception as e:
        logger.error(f"Error broadcasting election update: {str(e)}")


def broadcast_voter_update(action, voter_data, admin_id=None):
    """Broadcast voter updates to all connected clients"""
    try:
        update_data = {
            "type": "voter",
            "action": action,
            "data": voter_data,
            "timestamp": datetime.utcnow().isoformat(),
            "admin_id": admin_id,
        }

        safe_emit(
            "voter_update", update_data, room=f"voter_{voter_data.get('voter_id')}"
        )
        safe_emit("voter_update", update_data, room="all_admins")

        logger.info(f"Broadcasted voter {action}: {voter_data.get('voter_id')}")

    except Exception as e:
        logger.error(f"Error broadcasting voter update: {str(e)}")


def broadcast_system_update(action, data, admin_id=None):
    """Broadcast system-wide updates"""
    try:
        update_data = {
            "type": "system",
            "action": action,
            "data": data,
            "timestamp": datetime.utcnow().isoformat(),
            "admin_id": admin_id,
        }

        safe_emit("system_update", update_data, broadcast=True)
        logger.info(f"Broadcasted system update: {action}")

    except Exception as e:
        logger.error(f"Error broadcasting system update: {str(e)}")


def send_private_notification(voter_id, notification_data):
    """Send private notification to specific voter"""
    try:
        safe_emit("private_notification", notification_data, room=f"voter_{voter_id}")
        logger.info(f"Sent private notification to voter {voter_id}")
    except Exception as e:
        logger.error(f"Error sending private notification: {str(e)}")


def get_connected_users_count():
    """Get count of connected users"""
    return {
        "total_connected": len(connected_clients),
        "voters_connected": len(
            [c for c in connected_clients.values() if c.get("type") == "voter"]
        ),
        "admins_connected": len(
            [c for c in connected_clients.values() if c.get("type") == "admin"]
        ),
    }


@dashboard_bp.route("/socket-status", methods=["GET"])
@cross_origin()
def get_socket_status():
    """Get SocketIO connection status"""
    try:
        socketio_instance = get_socketio()
        return jsonify(
            {
                "success": True,
                "socketio_available": socketio_instance is not None,
                "connected_clients": len(connected_clients),
                "clients_details": list(connected_clients.values())[:10],
                "server_time": datetime.utcnow().isoformat(),
            }
        )
    except Exception as e:
        return (
            jsonify(
                {"success": False, "message": f"Error getting socket status: {str(e)}"}
            ),
            500,
        )


@dashboard_bp.route("/update-election-statuses", methods=["POST"])
def update_election_statuses_endpoint():
    """Endpoint to manually trigger election status updates"""
    try:
        update_election_statuses()
        return jsonify(
            {"success": True, "message": "Election statuses updated successfully"}
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"Failed to update election statuses: {str(e)}",
                }
            ),
            500,
        )


def update_election_statuses():
    """Automatically update election statuses based on current time"""
    try:
        current_time = datetime.utcnow()

        Election.get_collection().update_many(
            {
                "status": "scheduled",
                "voting_start": {"$lte": current_time},
                "voting_end": {"$gte": current_time},
                "is_active": True,
            },
            {"$set": {"status": "active", "updated_at": current_time}},
        )

        Election.get_collection().update_many(
            {
                "status": "active",
                "voting_end": {"$lt": current_time},
                "is_active": True,
            },
            {"$set": {"status": "completed", "updated_at": current_time}},
        )

        print("Election statuses updated successfully")

    except Exception as e:
        print(f"Error updating election statuses: {str(e)}")


@dashboard_bp.route("/data", methods=["GET", "OPTIONS"])
@cross_origin()
@voter_required
def get_dashboard_data():
    """Get comprehensive dashboard data - FIXED VERSION"""
    try:
        voter = request.voter
        logger.info(f"Loading dashboard data for voter: {voter['voter_id']}")

        dashboard_data = get_enhanced_dashboard_data(voter)

        AuditLog.create_log(
            action="dashboard_access",
            user_id=voter["voter_id"],
            user_type="voter",
            details={"section": "overview"},
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "dashboard_data": dashboard_data,
                "last_updated": datetime.utcnow().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"Dashboard data error: {str(e)}", exc_info=True)
        return (
            jsonify({"success": False, "message": "Failed to load dashboard data"}),
            500,
        )


@dashboard_bp.route("/profile", methods=["GET", "OPTIONS"])
@cross_origin()
@voter_required
def get_profile():
    """Get comprehensive user profile data - FIXED VERSION"""
    try:
        voter = request.voter

        profile_data = {
            "voter_id": voter["voter_id"],
            "full_name": voter["full_name"],
            "father_name": voter["father_name"],
            "mother_name": voter.get("mother_name", ""),
            "gender": voter["gender"],
            "date_of_birth": voter.get("date_of_birth"),
            "place_of_birth": voter.get("place_of_birth", ""),
            "email": voter["email"],
            "phone": voter["phone"],
            "alternate_phone": voter.get("alternate_phone", ""),
            "address": {
                "address_line1": voter["address_line1"],
                "address_line2": voter.get("address_line2", ""),
                "village_city": voter["village_city"],
                "district": voter["district"],
                "state": voter["state"],
                "pincode": voter["pincode"],
                "country": voter.get("country", "India"),
            },
            "national_id": {
                "type": voter["national_id_type"],
                "number": voter["national_id_number"],
                "verified": voter.get("id_verified", False),
            },
            "constituency": voter.get("constituency", "General Constituency"),
            "polling_station": voter.get("polling_station", "Main Polling Station"),
            "verification_status": {
                "email": voter.get("email_verified", False),
                "phone": voter.get("phone_verified", False),
                "id": voter.get("id_verified", False),
                "face": voter.get("face_verified", False),
                "overall": all(
                    [
                        voter.get("email_verified", False),
                        voter.get("phone_verified", False),
                        voter.get("id_verified", False),
                        voter.get("face_verified", False),
                    ]
                ),
            },
            "registration_status": voter.get("registration_status", "pending"),
            "registration_date": voter.get("created_at", datetime.utcnow()).isoformat(),
            "last_updated": voter.get("updated_at", datetime.utcnow()).isoformat(),
            "profile_score": calculate_profile_score(voter),
        }

        return jsonify({"success": True, "profile_data": profile_data})

    except Exception as e:
        logger.error(f"Profile error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to load profile"}), 500


@dashboard_bp.route("/socket-info", methods=["GET"])
@cross_origin()
def get_socket_info():
    """Get SocketIO connection information"""
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        voter_connections = [
            c
            for c in connected_clients.values()
            if c.get("voter_id") == voter["voter_id"]
        ]

        return jsonify(
            {
                "success": True,
                "socket_info": {
                    "connected": len(voter_connections) > 0,
                    "connection_count": len(voter_connections),
                    "total_connections": get_connected_users_count(),
                    "server_time": datetime.utcnow().isoformat(),
                },
            }
        )

    except Exception as e:
        logger.error(f"Socket info error: {str(e)}")
        return jsonify({"success": False, "message": "Failed to get socket info"}), 500


@dashboard_bp.route("/socket-health", methods=["GET"])
@cross_origin()
def socket_health_check():
    """Health check for Socket.IO connections"""
    return jsonify(
        {
            "success": True,
            "socket_io_connected": True,
            "connected_clients": len(connected_clients),
            "server_time": datetime.utcnow().isoformat(),
        }
    )


@dashboard_bp.route("/debug-socket", methods=["GET"])
@cross_origin()
def debug_socket():
    """Debug Socket.IO connections"""
    return jsonify(
        {
            "connected_clients": connected_clients,
            "total_connections": len(connected_clients),
            "server_info": {
                "async_mode": socketio.async_mode,
                "cors_allowed_origins": socketio.cors_allowed_origins,
            },
        }
    )


def get_enhanced_dashboard_data_for_socket(voter):
    """Wrapper function for socket events to access dashboard data"""
    return get_enhanced_dashboard_data(voter)


@dashboard_bp.route("/admin/update-election", methods=["POST"])
@cross_origin()
@admin_required
def admin_update_election():
    """Admin endpoint to update elections (triggers real-time updates)"""
    try:
        data = request.get_json()
        action = data.get("action")
        election_data = data.get("election_data")

        if not action or not election_data:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Action and election_data are required",
                    }
                ),
                400,
            )

        result = perform_election_operation(action, election_data, request.admin)

        if result["success"]:
            broadcast_election_update(
                action, result["election"], request.admin["admin_id"]
            )

            if action in ["create", "activate"]:
                notify_voters_about_new_election(result["election"])

            return jsonify(
                {
                    "success": True,
                    "message": f"Election {action} successful",
                    "election": result["election"],
                    "broadcast_sent": True,
                }
            )
        else:
            return jsonify({"success": False, "message": result["message"]}), 400

    except Exception as e:
        logger.error(f"Admin election update error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to update election"}), 500


@dashboard_bp.route("/admin/update-voter", methods=["POST"])
@cross_origin()
@admin_required
def admin_update_voter():
    """Admin endpoint to update voter status (triggers real-time updates)"""
    try:
        data = request.get_json()
        action = data.get("action")
        voter_data = data.get("voter_data")

        if not action or not voter_data:
            return (
                jsonify(
                    {"success": False, "message": "Action and voter_data are required"}
                ),
                400,
            )

        result = perform_voter_operation(action, voter_data, request.admin)

        if result["success"]:
            broadcast_voter_update(action, result["voter"], request.admin["admin_id"])

            if action in ["verify", "activate"]:
                send_voter_status_notification(result["voter"], action)

            return jsonify(
                {
                    "success": True,
                    "message": f"Voter {action} successful",
                    "voter": result["voter"],
                    "notification_sent": True,
                }
            )
        else:
            return jsonify({"success": False, "message": result["message"]}), 400

    except Exception as e:
        logger.error(f"Admin voter update error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to update voter"}), 500


@dashboard_bp.route("/admin/broadcast", methods=["POST"])
@cross_origin()
@admin_required
def admin_broadcast():
    """Admin endpoint to broadcast messages to all voters"""
    try:
        data = request.get_json()
        message = data.get("message")
        broadcast_type = data.get("type", "info")

        if not message:
            return jsonify({"success": False, "message": "Message is required"}), 400

        safe_emit(
            "admin_broadcast",
            {
                "message": message,
                "type": broadcast_type,
                "admin_id": request.admin["admin_id"],
                "timestamp": datetime.utcnow().isoformat(),
                "urgent": broadcast_type == "urgent",
            },
            room="all_voters",
            broadcast=True,
        )

        AuditLog.create_log(
            action="admin_broadcast",
            user_id=request.admin["admin_id"],
            user_type="admin",
            details={
                "message": message,
                "type": broadcast_type,
                "recipients": "all_voters",
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "message": "Broadcast sent successfully",
                "recipients": get_connected_users_count()["voters_connected"],
            }
        )

    except Exception as e:
        logger.error(f"Admin broadcast error: {str(e)}")
        return jsonify({"success": False, "message": "Failed to send broadcast"}), 500


@dashboard_bp.route("/admin/connected-users", methods=["GET"])
@cross_origin()
@admin_required
def get_connected_users():
    """Get information about connected users"""
    try:
        return jsonify(
            {
                "success": True,
                "connected_users": get_connected_users_count(),
                "detailed_connections": list(connected_clients.values())[:50],
            }
        )
    except Exception as e:
        logger.error(f"Connected users error: {str(e)}")
        return (
            jsonify({"success": False, "message": "Failed to get connected users"}),
            500,
        )


def notify_voters_about_new_election(election):
    """Notify voters about new election"""
    try:
        notification_data = {
            "type": "new_election",
            "title": "New Election Available",
            "message": f"New election '{election.get('title')}' is now available for voting.",
            "election_id": election.get("election_id"),
            "timestamp": datetime.utcnow().isoformat(),
            "action_url": f"/elections/{election.get('election_id')}",
        }
        safe_emit("election_notification", notification_data, room="all_voters")
    except Exception as e:
        logger.error(f"Error notifying voters about new election: {str(e)}")


def send_voter_status_notification(voter, action):
    """Send notification to voter about status change"""
    try:
        notification_data = {
            "type": "status_update",
            "title": "Account Status Updated",
            "message": f"Your account has been {action}d successfully.",
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
        }
        send_private_notification(voter["voter_id"], notification_data)
    except Exception as e:
        logger.error(f"Error sending voter status notification: {str(e)}")


def perform_election_operation(action, election_data, admin):
    """Perform election operations and return result"""
    try:
        if action == "create":
            election_id = Election.create_election(election_data)
            election = Election.find_by_election_id(election_id)

            AuditLog.create_log(
                action="create_election",
                user_id=admin["admin_id"],
                user_type="admin",
                details={
                    "election_id": election_id,
                    "title": election_data.get("title"),
                    "action": "create",
                },
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )
            return {"success": True, "election": election}

        elif action == "update":
            election_id = election_data.get("election_id")
            if not election_id:
                return {"success": False, "message": "Election ID required"}

            update_data = {k: v for k, v in election_data.items() if k != "election_id"}
            Election.update_one({"election_id": election_id}, update_data)
            election = Election.find_by_election_id(election_id)

            AuditLog.create_log(
                action="update_election",
                user_id=admin["admin_id"],
                user_type="admin",
                details={
                    "election_id": election_id,
                    "changes": update_data,
                    "action": "update",
                },
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )
            return {"success": True, "election": election}

        elif action == "delete":
            election_id = election_data.get("election_id")
            if not election_id:
                return {"success": False, "message": "Election ID required"}

            Election.update_one(
                {"election_id": election_id},
                {"is_active": False, "status": "cancelled"},
            )
            election = Election.find_by_election_id(election_id)

            AuditLog.create_log(
                action="delete_election",
                user_id=admin["admin_id"],
                user_type="admin",
                details={"election_id": election_id, "action": "delete"},
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )
            return {"success": True, "election": election}

        elif action == "activate":
            election_id = election_data.get("election_id")
            if not election_id:
                return {"success": False, "message": "Election ID required"}

            Election.update_one({"election_id": election_id}, {"status": "active"})
            election = Election.find_by_election_id(election_id)

            AuditLog.create_log(
                action="activate_election",
                user_id=admin["admin_id"],
                user_type="admin",
                details={"election_id": election_id, "action": "activate"},
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )
            return {"success": True, "election": election}

        else:
            return {"success": False, "message": "Invalid action"}

    except Exception as e:
        logger.error(f"Election operation error: {str(e)}")
        return {"success": False, "message": str(e)}


def perform_voter_operation(action, voter_data, admin):
    """Perform voter operations and return result"""
    try:
        voter_id = voter_data.get("voter_id")
        if not voter_id:
            return {"success": False, "message": "Voter ID required"}

        if action == "verify":
            verification_type = voter_data.get("verification_type", "all")
            update_data = {}

            if verification_type == "all":
                update_data = {
                    "email_verified": True,
                    "phone_verified": True,
                    "id_verified": True,
                    "face_verified": True,
                    "registration_status": "verified",
                }
            elif verification_type == "email":
                update_data = {"email_verified": True}
            elif verification_type == "phone":
                update_data = {"phone_verified": True}
            elif verification_type == "id":
                update_data = {"id_verified": True}
            elif verification_type == "face":
                update_data = {"face_verified": True}

            Voter.update_one({"voter_id": voter_id}, update_data)
            voter = Voter.find_by_voter_id(voter_id)

            AuditLog.create_log(
                action="verify_voter",
                user_id=admin["admin_id"],
                user_type="admin",
                details={
                    "voter_id": voter_id,
                    "verification_type": verification_type,
                    "action": "verify",
                },
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )
            return {"success": True, "voter": voter}

        elif action == "suspend":
            Voter.update_one({"voter_id": voter_id}, {"is_active": False})
            voter = Voter.find_by_voter_id(voter_id)

            AuditLog.create_log(
                action="suspend_voter",
                user_id=admin["admin_id"],
                user_type="admin",
                details={"voter_id": voter_id, "action": "suspend"},
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )
            return {"success": True, "voter": voter}

        elif action == "activate":
            Voter.update_one({"voter_id": voter_id}, {"is_active": True})
            voter = Voter.find_by_voter_id(voter_id)

            AuditLog.create_log(
                action="activate_voter",
                user_id=admin["admin_id"],
                user_type="admin",
                details={"voter_id": voter_id, "action": "activate"},
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )
            return {"success": True, "voter": voter}

        else:
            return {"success": False, "message": "Invalid action"}

    except Exception as e:
        logger.error(f"Voter operation error: {str(e)}")
        return {"success": False, "message": str(e)}


# ============ ENHANCED HELPER FUNCTIONS ============


def get_enhanced_voter_info(voter):
    """Get enhanced voter information"""
    return {
        "voter_id": voter["voter_id"],
        "full_name": voter["full_name"],
        "email": voter["email"],
        "phone": voter["phone"],
        "constituency": voter.get("constituency", "General Constituency"),
        "polling_station": voter.get("polling_station", "Main Polling Station"),
        "registration_date": voter.get("created_at", datetime.utcnow()).isoformat(),
        "last_login": voter.get("last_login", datetime.utcnow()).isoformat(),
        "profile_completion": calculate_profile_completion(voter),
        "verification_status": get_verification_status(voter),
        "account_status": "Active" if voter.get("is_active", True) else "Suspended",
        "membership_duration": calculate_membership_duration(voter.get("created_at")),
        "badges": get_completion_badges(voter),
    }


def get_enhanced_election_info(voter):
    """Get enhanced election information"""
    return {
        "upcoming_elections": get_upcoming_elections(voter),
        "active_elections": get_active_elections(voter),
        "past_elections": get_past_elections(voter),
        "can_vote": can_vote(voter),
        "election_calendar": get_election_calendar(),
        "featured_elections": get_featured_elections(),
        "voting_reminders": get_voting_reminders(voter["voter_id"]),
    }


def get_enhanced_quick_stats(voter):
    """Get enhanced quick statistics"""
    return {
        "votes_cast": get_votes_cast_count(voter["voter_id"]),
        "elections_participated": get_elections_participated_count(voter["voter_id"]),
        "upcoming_elections": get_upcoming_elections_count(),
        "verification_status": get_verification_status(voter),
        "account_status": "Active" if voter.get("is_active", True) else "Inactive",
        "participation_rate": calculate_participation_rate(voter["voter_id"]),
        "constituency_rank": get_constituency_ranking(voter["voter_id"]).get(
            "rank", "N/A"
        ),
        "voting_streak": calculate_voting_streak(voter["voter_id"]),
        "profile_score": calculate_profile_score(voter),
    }


def get_system_status():
    """Get system-wide status"""
    return {
        "system_health": "optimal",
        "active_users": get_active_users_count(),
        "total_votes_today": get_today_votes_count(),
        "system_uptime": "99.9%",
        "last_maintenance": (datetime.utcnow() - timedelta(days=2)).isoformat(),
        "next_maintenance": (datetime.utcnow() + timedelta(days=30)).isoformat(),
        "active_elections": get_active_elections_count(),
        "total_voters": Voter.count({"is_active": True}),
        "real_time_connections": get_connected_users_count(),
    }


def calculate_membership_duration(registration_date):
    """Calculate how long the voter has been registered"""
    if not registration_date:
        return "N/A"

    if isinstance(registration_date, dict) and "$date" in registration_date:
        reg_date = datetime.fromisoformat(
            registration_date["$date"].replace("Z", "+00:00")
        )
    else:
        reg_date = registration_date

    duration = datetime.utcnow() - reg_date
    days = duration.days

    if days < 30:
        return f"{days} days"
    elif days < 365:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''}"
    else:
        years = days // 365
        return f"{years} year{'s' if years > 1 else ''}"


def calculate_voting_streak(voter_id):
    """Calculate consecutive voting streak (placeholder)"""
    return 0


def get_completion_badges(voter):
    """Get profile completion badges"""
    badges = []

    if voter.get("email_verified"):
        badges.append({"name": "Email Verified", "icon": "email", "color": "success"})
    if voter.get("phone_verified"):
        badges.append({"name": "Phone Verified", "icon": "phone", "color": "info"})
    if voter.get("id_verified"):
        badges.append({"name": "ID Verified", "icon": "id-card", "color": "warning"})
    if voter.get("face_verified"):
        badges.append(
            {"name": "Face Verified", "icon": "user-check", "color": "primary"}
        )

    profile_completion = calculate_profile_completion(voter)
    if profile_completion >= 100:
        badges.append({"name": "Profile Complete", "icon": "star", "color": "gold"})

    return badges


def get_featured_elections():
    """Get featured/highlighted elections"""
    try:
        return Election.find_all(
            {
                "is_featured": True,
                "is_active": True,
                "status": {"$in": ["active", "scheduled"]},
            },
            sort=[("voting_start", 1)],
            limit=3,
        )
    except Exception as e:
        logger.error(f"Error getting featured elections: {str(e)}")
        return []


def get_voting_reminders(voter_id):
    """Get voting reminders for voter"""
    try:
        upcoming_elections = get_upcoming_elections({"voter_id": voter_id})
        reminders = []

        for election in upcoming_elections[:2]:
            if election.get("can_register", False):
                reminders.append(
                    {
                        "election_id": election.get("id"),
                        "title": election.get("title"),
                        "registration_end": election.get("registration_end"),
                        "days_remaining": calculate_days_remaining(
                            election.get("registration_end")
                        ),
                        "priority": (
                            "high"
                            if calculate_days_remaining(
                                election.get("registration_end")
                            )
                            <= 3
                            else "medium"
                        ),
                    }
                )

        return reminders
    except Exception as e:
        logger.error(f"Error getting voting reminders: {str(e)}")
        return []


def calculate_days_remaining(target_date):
    """Calculate days remaining until target date"""
    if not target_date:
        return 0

    if isinstance(target_date, dict) and "$date" in target_date:
        target = datetime.fromisoformat(target_date["$date"].replace("Z", "+00:00"))
    else:
        target = target_date

    remaining = target - datetime.utcnow()
    return max(0, remaining.days)


@dashboard_bp.route("/live-updates", methods=["GET"])
@cross_origin()
def get_live_updates():
    """Get recent real-time updates"""
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        recent_updates = []  # Placeholder for actual updates
        recent_updates.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return jsonify(
            {
                "success": True,
                "updates": recent_updates[:20],
                "total_updates": len(recent_updates),
                "last_checked": datetime.utcnow().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"Live updates error: {str(e)}", exc_info=True)
        return (
            jsonify({"success": False, "message": "Failed to load live updates"}),
            500,
        )


@dashboard_bp.route("/elections/live", methods=["GET"])
@cross_origin()
def get_live_elections():
    """Get real-time election data with live updates"""
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        election_type = request.args.get("type", "all")
        # request.args.get("status", "active")  # removed unused

        elections_data = {
            "upcoming": get_upcoming_elections(voter, election_type),
            "active": get_active_elections(voter, election_type),
            "completed": get_past_elections(voter, election_type),
            "live_stats": {
                "total_active": get_active_elections_count(),
                "votes_cast_today": get_today_votes_count(),
                "voter_turnout": calculate_system_turnout(),
                "last_updated": datetime.utcnow().isoformat(),
            },
        }

        return jsonify(
            {"success": True, "elections_data": elections_data, "live_feed": True}
        )

    except Exception as e:
        logger.error(f"Live elections error: {str(e)}", exc_info=True)
        return (
            jsonify({"success": False, "message": "Failed to load live election data"}),
            500,
        )


@dashboard_bp.route("/digital-id", methods=["GET"])
@cross_origin()
def get_digital_id():
    """Generate digital ID for voter - FIXED VERSION"""
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        qr_data = {
            "voter_id": voter["voter_id"],
            "full_name": voter["full_name"],
            "constituency": voter.get("constituency", "General"),
            "polling_station": voter.get("polling_station", "Main Polling Station"),
            "verified": all(
                [
                    voter.get("email_verified", False),
                    voter.get("phone_verified", False),
                    voter.get("id_verified", False),
                ]
            ),
        }

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(json.dumps(qr_data))
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format="PNG")
        img_byte_arr.seek(0)

        qr_base64 = base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")

        digital_id_data = {
            "voter_id": voter["voter_id"],
            "full_name": voter["full_name"],
            "father_name": voter.get("father_name", ""),
            "date_of_birth": voter.get("date_of_birth"),
            "address": f"{voter.get('address_line1', '')}, {voter.get('village_city', '')}",
            "constituency": voter.get("constituency", "General"),
            "polling_station": voter.get("polling_station", "Main Polling Station"),
            "qr_code": f"data:image/png;base64,{qr_base64}",
            "issue_date": datetime.utcnow().isoformat(),
            "expiry_date": (datetime.utcnow() + timedelta(days=365 * 5)).isoformat(),
            "status": "Active",
            "verification_status": {
                "email": voter.get("email_verified", False),
                "phone": voter.get("phone_verified", False),
                "id": voter.get("id_verified", False),
                "face": voter.get("face_verified", False),
            },
        }

        return jsonify({"success": True, "digital_id": digital_id_data})

    except Exception as e:
        logger.error(f"Digital ID error: {str(e)}", exc_info=True)
        return (
            jsonify({"success": False, "message": "Failed to generate digital ID"}),
            500,
        )


@dashboard_bp.route("/export-data", methods=["GET"])
@cross_origin()
def export_data():
    """Export voter data in various formats"""
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        format_type = request.args.get("format", "json")

        if format_type == "json":
            export_data = {
                "personal_info": {
                    "voter_id": voter["voter_id"],
                    "full_name": voter["full_name"],
                    "email": voter["email"],
                    "phone": voter["phone"],
                    "date_of_birth": voter.get("date_of_birth"),
                    "gender": voter["gender"],
                },
                "address": {
                    "address_line1": voter["address_line1"],
                    "address_line2": voter.get("address_line2", ""),
                    "village_city": voter["village_city"],
                    "district": voter["district"],
                    "state": voter["state"],
                    "pincode": voter["pincode"],
                },
                "election_info": {
                    "constituency": voter.get("constituency", ""),
                    "polling_station": voter.get("polling_station", ""),
                    "registration_date": voter.get("created_at"),
                },
                "voting_history": get_voter_voting_history(voter["voter_id"]),
                "exported_at": datetime.utcnow().isoformat(),
            }
            return jsonify({"success": True, "data": export_data, "format": "json"})

        elif format_type == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Field", "Value"])
            writer.writerow(["Voter ID", voter["voter_id"]])
            writer.writerow(["Full Name", voter["full_name"]])
            writer.writerow(["Email", voter["email"]])
            writer.writerow(["Phone", voter["phone"]])
            writer.writerow(["Date of Birth", voter.get("date_of_birth")])
            writer.writerow(["Constituency", voter.get("constituency", "")])
            writer.writerow(["Polling Station", voter.get("polling_station", "")])
            writer.writerow(["Export Date", datetime.utcnow().isoformat()])

            csv_data = output.getvalue()
            output.close()
            return jsonify({"success": True, "data": csv_data, "format": "csv"})

        else:
            return jsonify({"success": False, "message": "Unsupported format"}), 400

    except Exception as e:
        logger.error(f"Export data error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to export data"}), 500


@dashboard_bp.route("/refresh-data", methods=["POST"])
@cross_origin()
@voter_required
def refresh_dashboard_data():
    """Refresh dashboard data"""
    try:
        voter = request.voter
        logger.info(f"Refreshing dashboard data for voter: {voter['voter_id']}")

        dashboard_data = get_enhanced_dashboard_data(voter)

        AuditLog.create_log(
            action="dashboard_refresh",
            user_id=voter["voter_id"],
            user_type="voter",
            details={"section": "all"},
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "dashboard_data": dashboard_data,
                "last_updated": datetime.utcnow().isoformat(),
                "message": "Data refreshed successfully",
            }
        )

    except Exception as e:
        logger.error(f"Refresh data error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to refresh data"}), 500


@dashboard_bp.route("/export-data/<format_type>", methods=["GET"])
@cross_origin()
@voter_required
def export_voter_data(format_type):
    """Export voter data in various formats"""
    try:
        voter = request.voter

        if format_type == "pdf":
            return export_pdf_data(voter)
        elif format_type == "csv":
            return export_csv_data(voter)
        elif format_type == "json":
            return export_json_data(voter)
        else:
            return jsonify({"success": False, "message": "Unsupported format"}), 400

    except Exception as e:
        logger.error(f"Export data error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to export data"}), 500


@dashboard_bp.route("/fix-election-dates", methods=["POST"])
@cross_origin()
@admin_required
def fix_election_dates():
    """Fix election dates in database"""
    try:
        elections = Election.find_all({"is_active": True})

        fixed_count = 0
        for election in elections:
            election_id = election.get("election_id")
            voting_start = election.get("voting_start")
            voting_end = election.get("voting_end")

            print(f"\n🔍 Election: {election.get('title')}")
            print(f"   - ID: {election_id}")
            print(f"   - voting_start: {voting_start} (type: {type(voting_start)})")
            print(f"   - voting_end: {voting_end} (type: {type(voting_end)})")

            needs_fix = False
            new_dates = {}

            if isinstance(voting_start, str):
                parsed_start = normalize_date(voting_start)
                if parsed_start:
                    new_dates["voting_start"] = parsed_start
                    needs_fix = True
                else:
                    new_dates["voting_start"] = datetime.utcnow() + timedelta(days=1)
                    needs_fix = True
            elif voting_start is None:
                new_dates["voting_start"] = datetime.utcnow() + timedelta(days=1)
                needs_fix = True

            if isinstance(voting_end, str):
                parsed_end = normalize_date(voting_end)
                if parsed_end:
                    new_dates["voting_end"] = parsed_end
                    needs_fix = True
                else:
                    new_dates["voting_end"] = datetime.utcnow() + timedelta(days=7)
                    needs_fix = True
            elif voting_end is None:
                new_dates["voting_end"] = datetime.utcnow() + timedelta(days=7)
                needs_fix = True

            if needs_fix:
                print("   ⚠️ Need to fix dates")
                print(f"   - New voting_start: {new_dates.get('voting_start')}")
                print(f"   - New voting_end: {new_dates.get('voting_end')}")

                Election.update_one({"election_id": election_id}, {"$set": new_dates})
                fixed_count += 1

        return jsonify(
            {
                "success": True,
                "message": f"Fixed dates for {fixed_count} elections",
                "total_elections": len(elections),
                "fixed_count": fixed_count,
            }
        )

    except Exception as e:
        logger.error(f"Error fixing election dates: {str(e)}")
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Failed to fix election dates",
                    "error": str(e),
                }
            ),
            500,
        )


def export_pdf_data(voter):
    """Export voter data as PDF"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        title = Paragraph(f"Voter Data - {voter['full_name']}", styles["Title"])
        story.append(title)
        story.append(Spacer(1, 12))

        personal_data = [
            ["Field", "Value"],
            ["Voter ID", voter["voter_id"]],
            ["Full Name", voter["full_name"]],
            ["Email", voter["email"]],
            ["Phone", voter["phone"]],
            ["Date of Birth", voter.get("date_of_birth", "N/A")],
            ["Gender", voter["gender"]],
            ["Constituency", voter.get("constituency", "N/A")],
        ]

        personal_table = Table(personal_data, colWidths=[200, 300])
        personal_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        story.append(personal_table)
        story.append(Spacer(1, 12))

        voting_history = get_voter_voting_history(voter["voter_id"])
        if voting_history:
            history_title = Paragraph("Voting History", styles["Heading2"])
            story.append(history_title)

            history_data = [["Election", "Candidate", "Party", "Date"]]
            for vote in voting_history[:10]:
                history_data.append(
                    [
                        vote.get("election_title", "Unknown"),
                        vote.get("candidate_name", "Unknown"),
                        vote.get("party", "Unknown"),
                        vote.get("vote_timestamp", "N/A")[:10],
                    ]
                )

            history_table = Table(history_data, colWidths=[200, 150, 100, 80])
            history_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ]
                )
            )
            story.append(history_table)

        doc.build(story)
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"voter_data_{voter['voter_id']}.pdf",
            mimetype="application/pdf",
        )

    except Exception as e:
        logger.error(f"PDF export error: {str(e)}")
        raise


def export_csv_data(voter):
    """Export voter data as CSV"""
    try:
        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow(["Voter Data Export"])
        writer.writerow(["Generated on", datetime.utcnow().isoformat()])
        writer.writerow([])

        writer.writerow(["Personal Information"])
        writer.writerow(["Voter ID", voter["voter_id"]])
        writer.writerow(["Full Name", voter["full_name"]])
        writer.writerow(["Email", voter["email"]])
        writer.writerow(["Phone", voter["phone"]])
        writer.writerow(["Date of Birth", voter.get("date_of_birth", "N/A")])
        writer.writerow(["Gender", voter["gender"]])
        writer.writerow(["Constituency", voter.get("constituency", "N/A")])
        writer.writerow([])

        voting_history = get_voter_voting_history(voter["voter_id"])
        if voting_history:
            writer.writerow(["Voting History"])
            writer.writerow(["Election", "Candidate", "Party", "Date"])
            for vote in voting_history:
                writer.writerow(
                    [
                        vote.get("election_title", "Unknown"),
                        vote.get("candidate_name", "Unknown"),
                        vote.get("party", "Unknown"),
                        vote.get("vote_timestamp", "N/A")[:10],
                    ]
                )

        csv_data = output.getvalue()
        output.close()

        bytes_buffer = io.BytesIO()
        bytes_buffer.write(csv_data.encode("utf-8"))
        bytes_buffer.seek(0)

        return send_file(
            bytes_buffer,
            as_attachment=True,
            download_name=f"voter_data_{voter['voter_id']}.csv",
            mimetype="text/csv",
        )

    except Exception as e:
        logger.error(f"CSV export error: {str(e)}")
        raise


def export_json_data(voter):
    """Export voter data as JSON"""
    try:
        export_data = {
            "export_info": {
                "exported_at": datetime.utcnow().isoformat(),
                "voter_id": voter["voter_id"],
                "format": "json",
            },
            "personal_info": {
                "voter_id": voter["voter_id"],
                "full_name": voter["full_name"],
                "email": voter["email"],
                "phone": voter["phone"],
                "date_of_birth": voter.get("date_of_birth"),
                "gender": voter["gender"],
                "constituency": voter.get("constituency"),
                "registration_date": voter.get("created_at"),
            },
            "verification_status": {
                "email_verified": voter.get("email_verified", False),
                "phone_verified": voter.get("phone_verified", False),
                "id_verified": voter.get("id_verified", False),
                "face_verified": voter.get("face_verified", False),
            },
            "voting_history": get_voter_voting_history(voter["voter_id"]),
            "analytics": get_voter_analytics(voter["voter_id"]),
        }

        return jsonify({"success": True, "data": export_data, "format": "json"})

    except Exception as e:
        logger.error(f"JSON export error: {str(e)}")
        raise


@dashboard_bp.route("/digital-id/generate", methods=["GET"])
@cross_origin()
@voter_required
def generate_digital_id():
    """Generate digital ID with QR code"""
    try:
        voter = request.voter

        digital_id_data = {
            "voter_id": voter["voter_id"],
            "full_name": voter["full_name"],
            "father_name": voter.get("father_name", ""),
            "date_of_birth": voter.get("date_of_birth"),
            "address": f"{voter.get('address_line1', '')}, {voter.get('village_city', '')}, {voter.get('state', '')}",
            "constituency": voter.get("constituency", "General Constituency"),
            "polling_station": voter.get("polling_station", "Main Polling Station"),
            "issue_date": datetime.utcnow().isoformat(),
            "expiry_date": (datetime.utcnow() + timedelta(days=365 * 5)).isoformat(),
            "status": "Active",
            "verification_level": calculate_verification_level(voter),
            "qr_data": f"VOTER:{voter['voter_id']}:{voter['full_name']}:{voter.get('constituency', 'General')}",
        }

        qr_img = generate_qr_code(digital_id_data["qr_data"])
        qr_base64 = qr_img_to_base64(qr_img)

        digital_id_data["qr_code"] = f"data:image/png;base64,{qr_base64}"

        AuditLog.create_log(
            action="digital_id_generated",
            user_id=voter["voter_id"],
            user_type="voter",
            details={"digital_id_issued": True},
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "digital_id": digital_id_data,
                "message": "Digital ID generated successfully",
            }
        )

    except Exception as e:
        logger.error(f"Digital ID generation error: {str(e)}", exc_info=True)
        return (
            jsonify({"success": False, "message": "Failed to generate digital ID"}),
            500,
        )


def generate_qr_code(data):
    """Generate QR code image"""
    try:
        import qrcode

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        return img
    except Exception as e:
        logger.error(f"QR code generation error: {str(e)}")
        raise


def qr_img_to_base64(img):
    """Convert QR code image to base64"""
    try:
        import base64
        from io import BytesIO

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception as e:
        logger.error(f"QR code base64 conversion error: {str(e)}")
        raise


def calculate_verification_level(voter):
    """Calculate verification level for digital ID"""
    verifications = [
        voter.get("email_verified", False),
        voter.get("phone_verified", False),
        voter.get("id_verified", False),
        voter.get("face_verified", False),
    ]
    verified_count = sum(verifications)

    if verified_count == 4:
        return "Gold"
    elif verified_count >= 2:
        return "Silver"
    else:
        return "Basic"


@dashboard_bp.route("/voting-history/enhanced", methods=["GET"])
@cross_origin()
@voter_required
def get_enhanced_voting_history():
    """Get enhanced voting history with analytics"""
    try:
        voter = request.voter
        voter_id = voter["voter_id"]

        voting_history = get_voter_voting_history(voter_id)

        total_votes = len(voting_history)
        current_year = datetime.utcnow().year
        current_year_votes = len(
            [
                v
                for v in voting_history
                if v.get("vote_timestamp", "").startswith(str(current_year))
            ]
        )

        election_types = {}
        for vote in voting_history:
            election_type = vote.get("election_type", "unknown")
            election_types[election_type] = election_types.get(election_type, 0) + 1

        monthly_activity = {}
        for vote in voting_history:
            month = vote.get("vote_timestamp", "")[:7]
            if month:
                monthly_activity[month] = monthly_activity.get(month, 0) + 1

        enhanced_history = {
            "votes": voting_history,
            "statistics": {
                "total_votes": total_votes,
                "current_year_votes": current_year_votes,
                "participation_rate": calculate_participation_rate(voter_id),
                "election_type_breakdown": election_types,
                "monthly_activity": monthly_activity,
                "voting_streak": calculate_voting_streak(voter_id),
                "constituency_ranking": get_constituency_ranking(voter_id),
            },
            "achievements": get_voting_achievements(voter_id, voting_history),
            "timeline": generate_voting_timeline(voting_history),
        }

        return jsonify({"success": True, "voting_history": enhanced_history})

    except Exception as e:
        logger.error(f"Enhanced voting history error: {str(e)}")
        return (
            jsonify({"success": False, "message": "Failed to load voting history"}),
            500,
        )


@dashboard_bp.route("/analytics/enhanced", methods=["GET"])
@cross_origin()
@voter_required
def get_enhanced_analytics():
    """Get comprehensive voter analytics"""
    try:
        voter = request.voter
        voter_id = voter["voter_id"]

        analytics_data = {
            "profile_analytics": {
                "completion_score": calculate_profile_score(voter),
                "verification_score": calculate_verification_score(voter),
                "trust_level": calculate_trust_level(voter),
                "activity_score": calculate_activity_score(voter_id),
            },
            "voting_analytics": {
                "participation_rate": calculate_participation_rate(voter_id),
                "voting_patterns": analyze_voting_patterns(voter_id),
                "preferred_election_types": get_preferred_election_types(voter_id),
                "voting_times": analyze_voting_times(voter_id),
            },
            "comparison_analytics": {
                "constituency_ranking": get_constituency_ranking(voter_id),
                "age_group_comparison": get_age_group_comparison(voter),
                "regional_comparison": get_regional_comparison(voter),
            },
            "security_analytics": {
                "account_health": calculate_account_health(voter),
                "login_patterns": analyze_login_patterns(voter_id),
                "device_trust_score": calculate_device_trust_score(voter_id),
            },
        }

        return jsonify({"success": True, "analytics": analytics_data})

    except Exception as e:
        logger.error(f"Enhanced analytics error: {str(e)}")
        return jsonify({"success": False, "message": "Failed to load analytics"}), 500


@dashboard_bp.route("/security/enhanced", methods=["GET"])
@cross_origin()
def get_enhanced_security():
    """Get comprehensive security information - FIXED VERSION"""
    try:
        voter = get_authenticated_voter()
        if not voter:
            logger.warning("No authenticated voter for security endpoint")
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Authentication required",
                        "code": "AUTH_REQUIRED",
                    }
                ),
                401,
            )

        voter_id = voter["voter_id"]

        security_data = {
            "account_security": {
                "verification_status": {
                    "email": voter.get("email_verified", False),
                    "phone": voter.get("phone_verified", False),
                    "id": voter.get("id_verified", False),
                    "face": voter.get("face_verified", False),
                },
                "two_factor_enabled": voter.get("two_factor_enabled", False),
                "password_strength": assess_password_strength(voter_id),
                "account_age": calculate_account_age(voter),
                "account_status": (
                    "Active" if voter.get("is_active", True) else "Inactive"
                ),
            },
            "session_security": {
                "active_sessions": get_active_sessions(voter_id),
                "recent_logins": get_recent_logins(voter_id),
                "suspicious_activities": check_suspicious_activities(voter_id),
            },
            "device_security": {
                "trusted_devices": get_trusted_devices(voter_id),
                "device_fingerprints": get_device_fingerprints(voter_id),
                "location_patterns": analyze_location_patterns(voter_id),
            },
            "privacy_settings": {
                "data_sharing_preferences": get_data_sharing_preferences(voter_id),
                "notification_preferences": get_notification_preferences(voter_id),
                "visibility_settings": get_visibility_settings(voter_id),
            },
        }

        AuditLog.create_log(
            action="security_info_accessed",
            user_id=voter_id,
            user_type="voter",
            details={"section": "enhanced_security"},
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "security": security_data,
                "last_updated": datetime.utcnow().isoformat(),
            }
        )

    except Exception as e:
        logger.error(f"Enhanced security error: {str(e)}", exc_info=True)
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Failed to load security information",
                    "error": str(e) if current_app.debug else None,
                }
            ),
            500,
        )


def calculate_verification_score(voter):
    verifications = [
        voter.get("email_verified", False),
        voter.get("phone_verified", False),
        voter.get("id_verified", False),
        voter.get("face_verified", False),
    ]
    verified_count = sum(verifications)
    return (verified_count / len(verifications)) * 100


def calculate_trust_level(voter):
    verification_score = calculate_verification_score(voter)
    account_age = calculate_account_age(voter)
    activity_score = calculate_activity_score(voter["voter_id"])
    trust_score = (
        (verification_score * 0.4) + (account_age * 0.3) + (activity_score * 0.3)
    )
    if trust_score >= 80:
        return "High"
    elif trust_score >= 60:
        return "Medium"
    else:
        return "Low"


def calculate_activity_score(voter_id):
    return 75  # placeholder


def analyze_voting_patterns(voter_id):
    voting_history = get_voter_voting_history(voter_id)
    return {
        "total_elections": len(voting_history),
        "average_votes_per_year": calculate_average_votes_per_year(voting_history),
        "preferred_voting_times": analyze_voting_times(voter_id),
        "consistency_score": calculate_consistency_score(voting_history),
    }


def get_preferred_election_types(voter_id):
    voting_history = get_voter_voting_history(voter_id)
    election_types = {}
    for vote in voting_history:
        election_type = vote.get("election_type", "unknown")
        election_types[election_type] = election_types.get(election_type, 0) + 1
    return election_types


def analyze_voting_times(voter_id):
    return {"morning_votes": 0, "afternoon_votes": 0, "evening_votes": 0}


def get_age_group_comparison(voter):
    return {"age_group": "25-35", "participation_rate": 75, "average_votes": 5}


def get_regional_comparison(voter):
    return {
        "region": voter.get("state", "Unknown"),
        "regional_participation": 65,
        "regional_average": 4,
    }


def calculate_account_health(voter):
    verification_score = calculate_verification_score(voter)
    security_score = assess_security_score(voter)
    activity_score = calculate_activity_score(voter["voter_id"])
    return (verification_score + security_score + activity_score) / 3


def assess_security_score(voter):
    score = 0
    if voter.get("email_verified"):
        score += 25
    if voter.get("phone_verified"):
        score += 25
    if voter.get("two_factor_enabled"):
        score += 25
    if voter.get("face_verified"):
        score += 25
    return score


def analyze_login_patterns(voter_id):
    return {
        "usual_login_times": ["09:00-12:00", "14:00-18:00"],
        "unusual_activities": 0,
        "last_login_location": "Current Location",
    }


def calculate_device_trust_score(voter_id):
    return 85


def get_voting_achievements(voter_id, voting_history):
    achievements = []
    total_votes = len(voting_history)

    if total_votes >= 1:
        achievements.append(
            {
                "name": "First Vote",
                "description": "Cast your first vote",
                "icon": "beginner",
                "unlocked": True,
            }
        )
    if total_votes >= 5:
        achievements.append(
            {
                "name": "Active Voter",
                "description": "Participated in 5+ elections",
                "icon": "active",
                "unlocked": True,
            }
        )
    if total_votes >= 10:
        achievements.append(
            {
                "name": "Dedicated Citizen",
                "description": "Participated in 10+ elections",
                "icon": "dedicated",
                "unlocked": True,
            }
        )

    return achievements


def generate_voting_timeline(voting_history):
    timeline = []
    for vote in voting_history:
        timeline.append(
            {
                "date": vote.get("vote_timestamp"),
                "election": vote.get("election_title"),
                "candidate": vote.get("candidate_name"),
                "party": vote.get("party"),
                "type": "vote_cast",
            }
        )
    return sorted(timeline, key=lambda x: x["date"], reverse=True)


@dashboard_bp.route("/download-voter-slip", methods=["GET"])
@cross_origin()
def download_voter_slip():
    """Download voter slip as PDF"""
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        active_elections = get_active_elections(voter)

        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)

        p.setFont("Helvetica-Bold", 16)
        p.drawString(100, 750, "VOTER SLIP")
        p.setFont("Helvetica", 12)

        y_position = 700
        p.drawString(100, y_position, f"Voter ID: {voter['voter_id']}")
        p.drawString(100, y_position - 20, f"Name: {voter['full_name']}")
        p.drawString(100, y_position - 40, f"Father's Name: {voter['father_name']}")
        p.drawString(
            100, y_position - 60, f"Constituency: {voter.get('constituency', '')}"
        )
        p.drawString(
            100, y_position - 80, f"Polling Station: {voter.get('polling_station', '')}"
        )

        if active_elections:
            p.drawString(100, y_position - 120, "Active Elections:")
            for i, election in enumerate(active_elections[:3]):
                p.drawString(
                    120,
                    y_position - 140 - (i * 20),
                    f"{i + 1}. {election.get('title', 'Election')}",
                )

        p.drawString(
            100,
            y_position - 200,
            f"Issued on: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
        )

        p.showPage()
        p.save()

        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"voter_slip_{voter['voter_id']}.pdf",
            mimetype="application/pdf",
        )

    except Exception as e:
        logger.error(f"Voter slip error: {str(e)}", exc_info=True)
        return (
            jsonify({"success": False, "message": "Failed to generate voter slip"}),
            500,
        )


# ============ HELPER FUNCTIONS (original, kept) ============


def calculate_profile_completion(voter):
    required_fields = [
        "full_name",
        "father_name",
        "gender",
        "date_of_birth",
        "email",
        "phone",
        "address_line1",
        "village_city",
        "district",
        "state",
        "pincode",
        "national_id_number",
    ]
    completed = sum(1 for field in required_fields if voter.get(field))
    return int((completed / len(required_fields)) * 100)


def calculate_profile_score(voter):
    base_score = calculate_profile_completion(voter)
    verification_bonus = sum(
        [
            10 if voter.get("email_verified") else 0,
            10 if voter.get("phone_verified") else 0,
            15 if voter.get("id_verified") else 0,
            15 if voter.get("face_verified") else 0,
        ]
    )
    return min(100, base_score + verification_bonus)


def get_upcoming_elections(voter, election_type="all"):
    try:
        query = {
            "voting_start": {"$gt": datetime.utcnow()},
            "status": "scheduled",
            "is_active": True,
        }
        if election_type != "all":
            query["election_type"] = election_type

        elections = Election.find_all(query, sort=[("voting_start", 1)])

        enhanced_elections = []
        for election in elections:
            enhanced_elections.append(
                {
                    "id": election.get("election_id", "unknown"),
                    "title": election.get("title", "Unknown Election"),
                    "type": election.get("election_type", "general"),
                    "date": election.get("voting_start", datetime.utcnow()).isoformat(),
                    "registration_end": election.get("registration_end"),
                    "constituency": election.get(
                        "constituency", "General Constituency"
                    ),
                    "description": election.get("description", ""),
                    "status": "upcoming",
                    "can_register": datetime.utcnow()
                    < election.get("registration_end", datetime.utcnow()),
                    "is_eligible": check_voter_eligibility(
                        voter["voter_id"], election.get("election_id", "unknown")
                    ),
                }
            )
        return enhanced_elections
    except Exception as e:
        logger.error(f"Error getting upcoming elections: {str(e)}")
        return []


def get_active_elections(voter, election_type="all"):
    try:
        current_time = datetime.utcnow()
        print(f"🔍 Looking for active elections at: {current_time}")

        query = {"is_active": True, "status": "active"}
        if election_type != "all":
            query["election_type"] = election_type

        elections = Election.find_all(query, sort=[("voting_end", 1)])

        active_elections = []
        for election in elections:
            voting_start = normalize_date(election.get("voting_start"))
            voting_end = normalize_date(election.get("voting_end"))

            if not voting_start or not voting_end:
                continue

            if voting_start <= current_time <= voting_end:
                active_elections.append(election)

        enhanced_elections = []
        for election in active_elections:
            try:
                is_eligible = check_voter_eligibility(
                    voter["voter_id"], election.get("election_id")
                )
                has_voted = Vote.has_voted(
                    election.get("election_id"), voter["voter_id"]
                )

                enhanced_elections.append(
                    {
                        "election_id": election.get("election_id"),
                        "title": election.get("title", "Unknown Election"),
                        "election_type": election.get("election_type", "general"),
                        "status": "active",
                        "voting_start": election.get("voting_start"),
                        "voting_end": election.get("voting_end"),
                        "constituency": election.get(
                            "constituency", "General Constituency"
                        ),
                        "description": election.get("description", ""),
                        "has_voted": has_voted,
                        "can_vote": not has_voted and is_eligible,
                        "is_eligible": is_eligible,
                        "candidates_count": Candidate.count(
                            {"election_id": election.get("election_id")}
                        ),
                        "total_votes": Vote.count(
                            {"election_id": election.get("election_id")}
                        ),
                    }
                )
            except Exception as e:
                print(
                    f"Error enhancing election {election.get('election_id')}: {str(e)}"
                )
                continue

        return enhanced_elections

    except Exception as e:
        print(f"💥 Error in get_active_elections: {str(e)}")
        import traceback

        print(f"Traceback:\n{traceback.format_exc()}")
        return []


def get_past_elections(voter, election_type="all"):
    try:
        query = {
            "voting_end": {"$lt": datetime.utcnow()},
            "status": {"$in": ["completed", "cancelled"]},
            "is_active": True,
        }
        if election_type != "all":
            query["election_type"] = election_type

        elections = Election.find_all(query, sort=[("voting_end", -1)], limit=10)

        enhanced_elections = []
        for election in elections:
            vote = Vote.find_by_election_and_voter(
                election.get("election_id", "unknown"), voter["voter_id"]
            )
            enhanced_elections.append(
                {
                    "id": election.get("election_id", "unknown"),
                    "title": election.get("title", "Unknown Election"),
                    "type": election.get("election_type", "general"),
                    "date": election.get("voting_start", datetime.utcnow()).isoformat(),
                    "constituency": election.get(
                        "constituency", "General Constituency"
                    ),
                    "status": election.get("status", "completed"),
                    "voted": vote is not None,
                    "vote_timestamp": (
                        vote.get("vote_timestamp").isoformat()
                        if vote and vote.get("vote_timestamp")
                        else None
                    ),
                    "results_available": election.get("results_publish")
                    and datetime.utcnow()
                    > election.get("results_publish", datetime.utcnow()),
                }
            )
        return enhanced_elections
    except Exception as e:
        logger.error(f"Error getting past elections: {str(e)}")
        return []


def get_votes_cast_count(voter_id):
    try:
        return Vote.count({"voter_id": voter_id, "is_verified": True})
    except Exception as e:
        logger.error(f"Error counting votes: {str(e)}")
        return 0


def get_elections_participated_count(voter_id):
    try:
        pipeline = [
            {"$match": {"voter_id": voter_id, "is_verified": True}},
            {"$group": {"_id": "$election_id"}},
            {"$count": "election_count"},
        ]
        result = list(Vote.get_collection().aggregate(pipeline))
        return result[0]["election_count"] if result else 0
    except Exception as e:
        logger.error(f"Error counting elections participated: {str(e)}")
        return 0


def get_upcoming_elections_count():
    try:
        return Election.count(
            {
                "voting_start": {"$gt": datetime.utcnow()},
                "status": "scheduled",
                "is_active": True,
            }
        )
    except Exception as e:
        logger.error(f"Error counting upcoming elections: {str(e)}")
        return 0


def calculate_average_votes_per_year(voting_history):
    if not voting_history:
        return 0

    votes_by_year = {}
    for vote in voting_history:
        vote_date = vote.get("vote_timestamp")
        if vote_date:
            try:
                if isinstance(vote_date, dict) and "$date" in vote_date:
                    date_str = vote_date["$date"]
                    year = datetime.fromisoformat(date_str.replace("Z", "+00:00")).year
                elif isinstance(vote_date, str):
                    year = datetime.fromisoformat(vote_date.replace("Z", "+00:00")).year
                else:
                    continue
                votes_by_year[year] = votes_by_year.get(year, 0) + 1
            except Exception as e:
                logger.warning(f"Error parsing vote date: {e}")
                continue

    if not votes_by_year:
        return 0

    total_votes = sum(votes_by_year.values())
    total_years = len(votes_by_year)
    return round(total_votes / total_years, 1) if total_years > 0 else 0


def get_verification_status(voter):
    verifications = [
        voter.get("email_verified", False),
        voter.get("phone_verified", False),
        voter.get("id_verified", False),
        voter.get("face_verified", False),
    ]
    verified_count = sum(verifications)
    total_count = len(verifications)

    if verified_count == total_count:
        return "Fully Verified"
    elif verified_count >= 2:
        return "Partially Verified"
    else:
        return "Verification Pending"


def calculate_participation_rate(voter_id):
    try:
        total_elections = Election.count(
            {
                "voting_end": {"$lt": datetime.utcnow()},
                "status": "completed",
                "is_active": True,
            }
        )
        if total_elections == 0:
            return 0
        participated = get_elections_participated_count(voter_id)
        return int((participated / total_elections) * 100)
    except Exception as e:
        logger.error(f"Error calculating participation rate: {str(e)}")
        return 0


def get_voter_voting_history(voter_id):
    try:
        votes = Vote.find_all(
            {"voter_id": voter_id, "is_verified": True}, sort=[("vote_timestamp", -1)]
        )

        voting_history = []
        for vote in votes:
            election = Election.find_by_election_id(vote["election_id"])
            candidate = (
                Candidate.find_one({"candidate_id": vote["candidate_id"]})
                if vote.get("candidate_id")
                else None
            )

            voting_history.append(
                {
                    "election_id": vote["election_id"],
                    "election_title": (
                        election.get("title", "Unknown Election")
                        if election
                        else "Unknown Election"
                    ),
                    "election_type": (
                        election.get("election_type", "unknown")
                        if election
                        else "unknown"
                    ),
                    "candidate_name": (
                        candidate.get("full_name", "Write-in Candidate")
                        if candidate
                        else "Write-in Candidate"
                    ),
                    "party": (
                        candidate.get("party", "Independent")
                        if candidate
                        else "Independent"
                    ),
                    "vote_timestamp": vote.get(
                        "vote_timestamp", datetime.utcnow()
                    ).isoformat(),
                    "constituency": (
                        election.get("constituency", "Unknown")
                        if election
                        else "Unknown"
                    ),
                    "face_verified": vote.get("face_verified", False),
                }
            )
        return voting_history
    except Exception as e:
        logger.error(f"Error getting voting history: {str(e)}")
        return []


def get_voter_analytics(voter_id):
    try:
        votes_cast = get_votes_cast_count(voter_id)
        elections_participated = get_elections_participated_count(voter_id)
        participation_rate = calculate_participation_rate(voter_id)

        return {
            "votes_cast": votes_cast,
            "elections_participated": elections_participated,
            "participation_rate": participation_rate,
            "type_breakdown": get_election_type_breakdown(voter_id),
            "constituency_ranking": get_constituency_ranking(voter_id),
            "activity_trend": get_voter_activity_trend(voter_id),
        }
    except Exception as e:
        logger.error(f"Error getting voter analytics: {str(e)}")
        return {
            "votes_cast": 0,
            "elections_participated": 0,
            "participation_rate": 0,
            "type_breakdown": [],
            "constituency_ranking": None,
            "activity_trend": [],
        }


def get_election_type_breakdown(voter_id):
    try:
        pipeline = [
            {"$match": {"voter_id": voter_id, "is_verified": True}},
            {
                "$lookup": {
                    "from": "elections",
                    "localField": "election_id",
                    "foreignField": "election_id",
                    "as": "election_info",
                }
            },
            {"$unwind": "$election_info"},
            {"$group": {"_id": "$election_info.election_type", "count": {"$sum": 1}}},
        ]
        return list(Vote.get_collection().aggregate(pipeline))
    except Exception as e:
        logger.error(f"Error getting election type breakdown: {str(e)}")
        return []


def get_constituency_ranking(voter_id):
    try:
        voter = Voter.find_by_voter_id(voter_id)
        if not voter:
            return None
        constituency = voter.get("constituency")
        if not constituency:
            return None

        total_voters = Voter.count({"constituency": constituency, "is_active": True})
        ranking = max(1, int(total_voters * 0.2))
        return {
            "rank": ranking,
            "total_voters": total_voters,
            "percentile": (
                int(((total_voters - ranking) / total_voters) * 100)
                if total_voters > 0
                else 0
            ),
        }
    except Exception as e:
        logger.error(f"Error getting constituency ranking: {str(e)}")
        return None


def get_voter_activity_trend(voter_id):
    try:
        six_months_ago = datetime.utcnow() - timedelta(days=180)
        pipeline = [
            {
                "$match": {
                    "voter_id": voter_id,
                    "is_verified": True,
                    "vote_timestamp": {"$gte": six_months_ago},
                }
            },
            {
                "$group": {
                    "_id": {
                        "year": {"$year": "$vote_timestamp"},
                        "month": {"$month": "$vote_timestamp"},
                    },
                    "votes": {"$sum": 1},
                }
            },
            {"$sort": {"_id.year": 1, "_id.month": 1}},
            {"$limit": 6},
        ]
        trend_data = list(Vote.get_collection().aggregate(pipeline))

        formatted_trend = []
        for data in trend_data:
            formatted_trend.append(
                {
                    "period": f"{data['_id']['month']}/{data['_id']['year']}",
                    "votes": data["votes"],
                }
            )
        return formatted_trend
    except Exception as e:
        logger.error(f"Error getting voter activity trend: {str(e)}")
        return []


def get_recent_notifications(voter_id, limit=10):
    return [
        {
            "id": "1",
            "type": "info",
            "title": "Welcome to Voter Portal",
            "message": "Your account has been successfully created and verified.",
            "timestamp": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
            "read": False,
            "action_url": "/profile",
        },
        {
            "id": "2",
            "type": "election",
            "title": "New Election Announcement",
            "message": "National General Election 2024 registration is now open.",
            "timestamp": (datetime.utcnow() - timedelta(days=1)).isoformat(),
            "read": True,
            "action_url": "/elections",
        },
    ]


def get_election_statistics(voter_id):
    try:
        return {
            "total_elections": Election.count({"is_active": True}),
            "upcoming_elections": get_upcoming_elections_count(),
            "active_elections": Election.count(
                {
                    "voting_start": {"$lte": datetime.utcnow()},
                    "voting_end": {"$gte": datetime.utcnow()},
                    "status": "active",
                    "is_active": True,
                }
            ),
            "completed_elections": Election.count(
                {
                    "voting_end": {"$lt": datetime.utcnow()},
                    "status": "completed",
                    "is_active": True,
                }
            ),
        }
    except Exception as e:
        logger.error(f"Error getting election statistics: {str(e)}")
        return {
            "total_elections": 0,
            "upcoming_elections": 0,
            "active_elections": 0,
            "completed_elections": 0,
        }


def get_election_type_counts():
    try:
        pipeline = [
            {"$match": {"is_active": True}},
            {"$group": {"_id": "$election_type", "count": {"$sum": 1}}},
        ]
        return list(Election.get_collection().aggregate(pipeline))
    except Exception as e:
        logger.error(f"Error getting election type counts: {str(e)}")
        return []


def get_election_calendar():
    try:
        three_months_later = datetime.utcnow() + timedelta(days=90)
        elections = Election.find_all(
            {
                "voting_start": {"$gte": datetime.utcnow(), "$lte": three_months_later},
                "is_active": True,
            },
            sort=[("voting_start", 1)],
        )
        calendar = []
        for election in elections:
            calendar.append(
                {
                    "id": election["election_id"],
                    "title": election["title"],
                    "type": election["election_type"],
                    "start_date": election["voting_start"].isoformat(),
                    "end_date": election["voting_end"].isoformat(),
                    "constituency": election.get("constituency"),
                    "description": election.get("description"),
                }
            )
        return calendar
    except Exception as e:
        logger.error(f"Error getting election calendar: {str(e)}")
        return []


def check_voter_eligibility(voter_id, election_id):
    try:
        logger.info(
            f"Checking eligibility for voter {voter_id} in election {election_id}"
        )

        voter = Voter.find_by_voter_id(voter_id)
        election = Election.find_by_election_id(election_id)

        if not voter or not election:
            return False

        if not voter.get("is_active", False):
            logger.warning(f"Voter {voter_id} is not active")
            return False

        required_verifications = ["email_verified", "phone_verified"]
        missing_verifications = [
            v for v in required_verifications if not voter.get(v, False)
        ]
        if missing_verifications:
            logger.warning(
                f"Voter {voter_id} missing verifications: {missing_verifications}"
            )
            return False

        voter_constituency = voter.get("constituency", "General")
        election_constituency = election.get("constituency", "General")

        if election_constituency.lower() == "general":
            constituency_match = True
        else:
            constituency_match = check_constituency_match(
                voter_constituency, election_constituency
            )
            if not constituency_match:
                logger.warning(
                    f"Voter {voter_id} constituency mismatch: '{voter_constituency}' vs '{election_constituency}'"
                )
                return False

        current_time = datetime.utcnow()
        voting_start = election.get("voting_start")
        voting_end = election.get("voting_end")

        if voting_start and voting_end:
            if current_time < voting_start or current_time > voting_end:
                return False
        else:
            logger.warning("Election missing voting dates")
            return False

        if Vote.has_voted(election_id, voter_id):
            logger.warning(f"Voter {voter_id} already voted in this election")
            return False

        logger.info(f"Voter {voter_id} is ELIGIBLE for election {election_id}")
        return True

    except Exception as e:
        logger.error(f"Error checking voter eligibility: {str(e)}")
        return False


def check_constituency_match(voter_constituency, election_constituency):
    if not voter_constituency or not election_constituency:
        return True

    voter_constituency = str(voter_constituency).lower().strip()
    election_constituency = str(election_constituency).lower().strip()

    if voter_constituency == election_constituency:
        return True

    if (
        voter_constituency in election_constituency
        or election_constituency in voter_constituency
    ):
        return True

    voter_words = set(voter_constituency.split())
    election_words = set(election_constituency.split())
    common_words = voter_words.intersection(election_words)
    if len(common_words) >= 1:
        return True

    suffixes = ["constituency", "district", "area", "region", "zone", "city", "town"]
    voter_clean = " ".join([word for word in voter_words if word not in suffixes])
    election_clean = " ".join([word for word in election_words if word not in suffixes])
    if voter_clean and election_clean:
        if (
            voter_clean == election_clean
            or voter_clean in election_clean
            or election_clean in voter_clean
        ):
            return True

    for voter_word in voter_words:
        if voter_word in election_constituency and len(voter_word) > 3:
            return True

    return False


def get_active_elections_count():
    try:
        return Election.count(
            {
                "status": "active",
                "is_active": True,
                "voting_start": {"$lte": datetime.utcnow()},
                "voting_end": {"$gte": datetime.utcnow()},
            }
        )
    except Exception as e:
        logger.error(f"Error counting active elections: {str(e)}")
        return 0


def get_today_votes_count():
    try:
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return Vote.count(
            {"vote_timestamp": {"$gte": today_start}, "is_verified": True}
        )
    except Exception as e:
        logger.error(f"Error counting today's votes: {str(e)}")
        return 0


def get_active_users_count():
    try:
        day_ago = datetime.utcnow() - timedelta(hours=24)
        return Voter.count({"last_login": {"$gte": day_ago}, "is_active": True})
    except Exception as e:
        logger.error(f"Error counting active users: {str(e)}")
        return 0


def calculate_system_turnout():
    try:
        total_voters = Voter.count({"is_active": True})
        total_votes = Vote.count({"is_verified": True})
        if total_voters == 0:
            return 0
        return round((total_votes / total_voters) * 100, 1)
    except Exception as e:
        logger.error(f"Error calculating system turnout: {str(e)}")
        return 0


def can_vote(voter):
    return all(
        [
            voter.get("is_active", True),
            voter.get("email_verified", False),
            voter.get("phone_verified", False),
            voter.get("id_verified", False),
        ]
    )


@dashboard_bp.route("/security-settings", methods=["GET", "POST"])
@cross_origin()
def security_settings():
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        if request.method == "GET":
            security_data = {
                "two_factor_enabled": voter.get("two_factor_enabled", False),
                "login_alerts": voter.get("login_alerts", True),
                "session_timeout": voter.get("session_timeout", 30),
                "password_last_changed": voter.get("last_password_change"),
                "active_sessions": get_active_sessions(voter["voter_id"]),
                "trusted_devices": get_trusted_devices(voter["voter_id"]),
            }
            return jsonify({"success": True, "security_settings": security_data})

        elif request.method == "POST":
            data = request.get_json()
            updates = {}
            if "two_factor_enabled" in data:
                updates["two_factor_enabled"] = data["two_factor_enabled"]
            if "login_alerts" in data:
                updates["login_alerts"] = data["login_alerts"]
            if "session_timeout" in data:
                updates["session_timeout"] = data["session_timeout"]

            if updates:
                Voter.update_one({"voter_id": voter["voter_id"]}, {"$set": updates})
                AuditLog.create_log(
                    action="security_settings_updated",
                    user_id=voter["voter_id"],
                    user_type="voter",
                    details=updates,
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                )
            return jsonify(
                {"success": True, "message": "Security settings updated successfully"}
            )

    except Exception as e:
        logger.error(f"Security settings error: {str(e)}", exc_info=True)
        return (
            jsonify(
                {"success": False, "message": "Failed to process security settings"}
            ),
            500,
        )


@dashboard_bp.route("/security/devices/trusted", methods=["GET"])
@cross_origin()
@voter_required
def get_trusted_devices_endpoint():
    try:
        voter = request.voter
        month_ago = datetime.utcnow() - timedelta(days=30)

        pipeline = [
            {
                "$match": {
                    "user_id": voter["voter_id"],
                    "user_type": "voter",
                    "action": "login",
                    "timestamp": {"$gte": month_ago},
                    "user_agent": {"$exists": True, "$ne": ""},
                }
            },
            {
                "$group": {
                    "_id": {"user_agent": "$user_agent", "ip_address": "$ip_address"},
                    "last_login": {"$max": "$timestamp"},
                    "login_count": {"$sum": 1},
                    "device_id": {
                        "$first": {
                            "$concat": [
                                {"$substrCP": ["$user_agent", 0, 10]},
                                "-",
                                {"$substrCP": ["$ip_address", -5, 5]},
                            ]
                        }
                    },
                }
            },
            {
                "$project": {
                    "device_id": 1,
                    "device_name": {
                        "$concat": [
                            {
                                "$cond": [
                                    {
                                        "$regexMatch": {
                                            "input": "$_id.user_agent",
                                            "regex": "Mobile",
                                            "options": "i",
                                        }
                                    },
                                    "Mobile",
                                    {
                                        "$cond": [
                                            {
                                                "$regexMatch": {
                                                    "input": "$_id.user_agent",
                                                    "regex": "Tablet",
                                                    "options": "i",
                                                }
                                            },
                                            "Tablet",
                                            "Desktop",
                                        ]
                                    },
                                ]
                            },
                            " Device",
                        ]
                    },
                    "user_agent": "$_id.user_agent",
                    "ip_address": "$_id.ip_address",
                    "last_login": 1,
                    "login_count": 1,
                    "browser": {
                        "$cond": [
                            {
                                "$regexMatch": {
                                    "input": "$_id.user_agent",
                                    "regex": "Chrome",
                                    "options": "i",
                                }
                            },
                            "Chrome",
                            {
                                "$cond": [
                                    {
                                        "$regexMatch": {
                                            "input": "$_id.user_agent",
                                            "regex": "Firefox",
                                            "options": "i",
                                        }
                                    },
                                    "Firefox",
                                    {
                                        "$cond": [
                                            {
                                                "$regexMatch": {
                                                    "input": "$_id.user_agent",
                                                    "regex": "Safari",
                                                    "options": "i",
                                                }
                                            },
                                            "Safari",
                                            {
                                                "$cond": [
                                                    {
                                                        "$regexMatch": {
                                                            "input": "$_id.user_agent",
                                                            "regex": "Edge",
                                                            "options": "i",
                                                        }
                                                    },
                                                    "Edge",
                                                    "Other Browser",
                                                ]
                                            },
                                        ]
                                    },
                                ]
                            },
                        ]
                    },
                    "os": {
                        "$cond": [
                            {
                                "$regexMatch": {
                                    "input": "$_id.user_agent",
                                    "regex": "Windows",
                                    "options": "i",
                                }
                            },
                            "Windows",
                            {
                                "$cond": [
                                    {
                                        "$regexMatch": {
                                            "input": "$_id.user_agent",
                                            "regex": "Mac",
                                            "options": "i",
                                        }
                                    },
                                    "macOS",
                                    {
                                        "$cond": [
                                            {
                                                "$regexMatch": {
                                                    "input": "$_id.user_agent",
                                                    "regex": "Linux",
                                                    "options": "i",
                                                }
                                            },
                                            "Linux",
                                            {
                                                "$cond": [
                                                    {
                                                        "$regexMatch": {
                                                            "input": "$_id.user_agent",
                                                            "regex": "Android",
                                                            "options": "i",
                                                        }
                                                    },
                                                    "Android",
                                                    {
                                                        "$cond": [
                                                            {
                                                                "$regexMatch": {
                                                                    "input": "$_id.user_agent",
                                                                    "regex": "iPhone|iPad",
                                                                    "options": "i",
                                                                }
                                                            },
                                                            "iOS",
                                                            "Unknown OS",
                                                        ]
                                                    },
                                                ]
                                            },
                                        ]
                                    },
                                ]
                            },
                        ]
                    },
                    "is_trusted": {"$gte": ["$login_count", 2]},
                }
            },
            {"$sort": {"last_login": -1}},
        ]

        devices = list(AuditLog.get_collection().aggregate(pipeline))
        return jsonify(
            {"success": True, "devices": devices, "total_devices": len(devices)}
        )

    except Exception as e:
        logger.error(f"Trusted devices error: {str(e)}")
        return (
            jsonify({"success": False, "message": "Failed to load trusted devices"}),
            500,
        )


@dashboard_bp.route("/security/devices/revoke", methods=["POST"])
@cross_origin()
@voter_required
def revoke_device_endpoint():
    try:
        voter = request.voter
        data = request.get_json()

        if not data or "device_id" not in data:
            return jsonify({"success": False, "message": "Device ID is required"}), 400

        device_id = data["device_id"]

        AuditLog.create_log(
            action="device_revoked",
            user_id=voter["voter_id"],
            user_type="voter",
            details={
                "device_id": device_id,
                "action": "device_access_revoked",
                "timestamp": datetime.utcnow().isoformat(),
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {"success": True, "message": "Device access revoked successfully"}
        )

    except Exception as e:
        logger.error(f"Revoke device error: {str(e)}")
        return jsonify({"success": False, "message": "Failed to revoke device"}), 500


@dashboard_bp.route("/security/sessions/logout-all", methods=["POST"])
@cross_origin()
@voter_required
def logout_all_sessions_endpoint():
    try:
        voter = request.voter

        session_secret = hashlib.sha256(
            f"{voter['voter_id']}-{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()

        Voter.update_one(
            {"voter_id": voter["voter_id"]},
            {"$set": {"session_secret": session_secret}},
        )

        AuditLog.create_log(
            action="logout_all_sessions",
            user_id=voter["voter_id"],
            user_type="voter",
            details={
                "action": "all_sessions_invalidated",
                "new_session_secret": session_secret[:10] + "...",
                "sessions_logged_out": "all",
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "message": "All sessions have been logged out successfully",
                "requires_relogin": True,
            }
        )

    except Exception as e:
        logger.error(f"Logout all sessions error: {str(e)}")
        return (
            jsonify({"success": False, "message": "Failed to logout all sessions"}),
            500,
        )


@dashboard_bp.route("/security/two-factor/enable", methods=["POST"])
@cross_origin()
@voter_required
def enable_two_factor_endpoint():
    try:
        voter = request.voter

        if voter.get("two_factor_enabled"):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Two-factor authentication is already enabled",
                    }
                ),
                400,
            )

        import base64
        import secrets

        secret = base64.b32encode(secrets.token_bytes(20)).decode("utf-8")

        Voter.update_one(
            {"voter_id": voter["voter_id"]},
            {
                "$set": {
                    "two_factor_secret": secret,
                    "two_factor_enabled": False,
                    "two_factor_backup_codes": generate_backup_codes(),
                }
            },
        )

        qr_data = f"otpauth://totp/VoterPortal:{voter['email']}?secret={secret}&issuer=VoterPortal"

        AuditLog.create_log(
            action="two_factor_setup_started",
            user_id=voter["voter_id"],
            user_type="voter",
            details={"action": "2fa_setup_initiated", "has_secret": True},
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "message": "Two-factor authentication setup started",
                "requires_setup": True,
                "setup_data": {
                    "secret": secret,
                    "qr_data": qr_data,
                    "backup_codes": generate_backup_codes(),
                    "instructions": "Scan the QR code with your authenticator app",
                },
            }
        )

    except Exception as e:
        logger.error(f"Enable 2FA error: {str(e)}")
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Failed to enable two-factor authentication",
                }
            ),
            500,
        )


@dashboard_bp.route("/security/two-factor/verify", methods=["POST"])
@cross_origin()
@voter_required
def verify_two_factor_endpoint():
    try:
        voter = request.voter
        data = request.get_json()

        if not data or "token" not in data:
            return (
                jsonify(
                    {"success": False, "message": "Verification token is required"}
                ),
                400,
            )

        token = data["token"]
        secret = voter.get("two_factor_secret")

        if not secret:
            return (
                jsonify({"success": False, "message": "Two-factor setup not started"}),
                400,
            )

        if len(token) == 6 and token.isdigit():
            Voter.update_one(
                {"voter_id": voter["voter_id"]},
                {
                    "$set": {
                        "two_factor_enabled": True,
                        "two_factor_enabled_at": datetime.utcnow(),
                    }
                },
            )

            AuditLog.create_log(
                action="two_factor_enabled",
                user_id=voter["voter_id"],
                user_type="voter",
                details={"action": "2fa_enabled_successfully"},
                ip_address=request.remote_addr,
                user_agent=request.headers.get("User-Agent"),
            )

            return jsonify(
                {
                    "success": True,
                    "message": "Two-factor authentication enabled successfully",
                    "backup_codes": voter.get("two_factor_backup_codes", []),
                }
            )
        else:
            return (
                jsonify({"success": False, "message": "Invalid verification token"}),
                400,
            )

    except Exception as e:
        logger.error(f"Verify 2FA error: {str(e)}")
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Failed to verify two-factor authentication",
                }
            ),
            500,
        )


@dashboard_bp.route("/security/two-factor/disable", methods=["POST"])
@cross_origin()
@voter_required
def disable_two_factor_endpoint():
    try:
        voter = request.voter

        if not voter.get("two_factor_enabled"):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Two-factor authentication is not enabled",
                    }
                ),
                400,
            )

        Voter.update_one(
            {"voter_id": voter["voter_id"]},
            {
                "$set": {
                    "two_factor_enabled": False,
                    "two_factor_disabled_at": datetime.utcnow(),
                }
            },
        )

        AuditLog.create_log(
            action="two_factor_disabled",
            user_id=voter["voter_id"],
            user_type="voter",
            details={"action": "2fa_disabled"},
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "message": "Two-factor authentication disabled successfully",
            }
        )

    except Exception as e:
        logger.error(f"Disable 2FA error: {str(e)}")
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Failed to disable two-factor authentication",
                }
            ),
            500,
        )


def generate_backup_codes():
    import secrets

    codes = []
    for _ in range(10):
        code = "-".join(
            [
                secrets.token_hex(2).upper(),
                secrets.token_hex(2).upper(),
                secrets.token_hex(2).upper(),
            ]
        )
        codes.append(code)
    return codes


@dashboard_bp.route("/profile/update", methods=["PUT"])
@cross_origin()
@voter_required
def update_profile():
    try:
        voter = request.voter
        data = request.get_json()

        update_data = {}

        if "full_name" in data:
            update_data["full_name"] = data["full_name"]
        if "date_of_birth" in data:
            update_data["date_of_birth"] = data["date_of_birth"]
        if "gender" in data:
            update_data["gender"] = data["gender"]
        if "father_name" in data:
            update_data["father_name"] = data["father_name"]
        if "mother_name" in data:
            update_data["mother_name"] = data["mother_name"]
        if "address_line1" in data:
            update_data["address_line1"] = data["address_line1"]
        if "address_line2" in data:
            update_data["address_line2"] = data["address_line2"]
        if "village_city" in data:
            update_data["village_city"] = data["village_city"]
        if "district" in data:
            update_data["district"] = data["district"]
        if "state" in data:
            update_data["state"] = data["state"]
        if "pincode" in data:
            update_data["pincode"] = data["pincode"]

        if update_data:
            update_data["updated_at"] = datetime.utcnow()
            Voter.update_one({"voter_id": voter["voter_id"]}, {"$set": update_data})

        AuditLog.create_log(
            action="profile_update",
            user_id=voter["voter_id"],
            user_type="voter",
            details={
                "fields_updated": list(update_data.keys()),
                "timestamp": datetime.utcnow().isoformat(),
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "message": "Profile updated successfully",
                "updated_fields": list(update_data.keys()),
            }
        )

    except Exception as e:
        logger.error(f"Update profile error: {str(e)}")
        return jsonify({"success": False, "message": "Failed to update profile"}), 500


def parse_user_agent_for_device_name(user_agent):
    if not user_agent:
        return "Unknown Device"
    user_agent_lower = user_agent.lower()
    if "chrome" in user_agent_lower:
        return "Chrome Browser"
    elif "firefox" in user_agent_lower:
        return "Firefox Browser"
    elif "safari" in user_agent_lower:
        return "Safari Browser"
    elif "edge" in user_agent_lower:
        return "Edge Browser"
    elif "mobile" in user_agent_lower:
        return "Mobile Device"
    else:
        return "Web Browser"


def get_location_from_ip(ip_address):
    if ip_address.startswith("192.168.") or ip_address.startswith("10."):
        return "Local Network"
    elif ip_address.startswith("172."):
        return "Private Network"
    else:
        return "Unknown Location"


@dashboard_bp.route("/mobile-verification", methods=["POST"])
@cross_origin()
def mobile_verification():
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        data = request.get_json()
        action = data.get("action")

        if action == "send_otp":
            phone = voter["phone"]
            otp_id = OTP.create_otp(phone=phone, purpose="mobile_verification")
            logger.info(f"OTP sent to {phone} for mobile verification")
            return jsonify(
                {
                    "success": True,
                    "message": "OTP sent to your mobile number",
                    "otp_id": otp_id,
                }
            )

        elif action == "verify_otp":
            otp_code = data.get("otp_code")
            phone = voter["phone"]

            if OTP.verify_otp(
                phone=phone, otp_code=otp_code, purpose="mobile_verification"
            ):
                Voter.update_verification_status(voter["voter_id"], "phone", True)
                AuditLog.create_log(
                    action="mobile_verified",
                    user_id=voter["voter_id"],
                    user_type="voter",
                    details={"phone": phone},
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                )
                return jsonify(
                    {"success": True, "message": "Mobile number verified successfully"}
                )
            else:
                return jsonify({"success": False, "message": "Invalid OTP code"}), 400

        else:
            return jsonify({"success": False, "message": "Invalid action"}), 400

    except Exception as e:
        logger.error(f"Mobile verification error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Mobile verification failed"}), 500


@dashboard_bp.route("/cast-vote", methods=["POST"])
@cross_origin()
def cast_vote():
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        data = request.get_json()
        election_id = data.get("election_id")
        candidate_id = data.get("candidate_id")

        if not election_id or not candidate_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Election ID and Candidate ID are required",
                    }
                ),
                400,
            )

        if Vote.has_voted(election_id, voter["voter_id"]):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "You have already voted in this election",
                    }
                ),
                400,
            )

        if not check_voter_eligibility(voter["voter_id"], election_id):
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "You are not eligible to vote in this election",
                    }
                ),
                400,
            )

        vote_data = {
            "election_id": election_id,
            "voter_id": voter["voter_id"],
            "candidate_id": candidate_id,
            "face_verified": voter.get("face_verified", False),
            "ip_address": request.remote_addr,
            "user_agent": request.headers.get("User-Agent"),
            "is_verified": True,
        }

        vote_id = Vote.create_vote(vote_data)
        Candidate.increment_vote_count(candidate_id)

        AuditLog.create_log(
            action="vote_cast",
            user_id=voter["voter_id"],
            user_type="voter",
            details={
                "election_id": election_id,
                "candidate_id": candidate_id,
                "vote_id": vote_id,
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {"success": True, "message": "Vote cast successfully", "vote_id": vote_id}
        )

    except Exception as e:
        logger.error(f"Vote casting error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to cast vote"}), 500


@dashboard_bp.route("/voting-history", methods=["GET", "OPTIONS"])
@cross_origin()
def get_voting_history():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        voting_history = get_voter_voting_history(voter["voter_id"])
        return jsonify({"success": True, "voting_history": voting_history})

    except Exception as e:
        logger.error(f"Voting history error: {str(e)}", exc_info=True)
        return (
            jsonify({"success": False, "message": "Failed to load voting history"}),
            500,
        )


@dashboard_bp.route("/analytics", methods=["GET", "OPTIONS"])
@cross_origin()
def get_analytics():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        analytics_data = get_voter_analytics(voter["voter_id"])
        return jsonify({"success": True, "analytics_data": analytics_data})

    except Exception as e:
        logger.error(f"Analytics error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Failed to load analytics"}), 500


@dashboard_bp.route("/notifications", methods=["GET", "OPTIONS"])
@cross_origin()
def get_notifications():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        limit = int(request.args.get("limit", 10))
        notifications = get_recent_notifications(voter["voter_id"], limit)
        return jsonify({"success": True, "notifications": notifications})

    except Exception as e:
        logger.error(f"Notifications error: {str(e)}", exc_info=True)
        return (
            jsonify({"success": False, "message": "Failed to load notifications"}),
            500,
        )


def get_active_sessions(voter_id):
    try:
        return [
            {
                "device": "Chrome on Windows",
                "ip_address": "192.168.1.100",
                "last_active": (datetime.utcnow() - timedelta(minutes=5)).isoformat(),
                "location": "New Delhi, India",
            }
        ]
    except Exception as e:
        logger.error(f"Error getting active sessions: {str(e)}")
        return []


def get_trusted_devices(voter_id):
    try:
        return [
            {
                "device_id": "device_001",
                "device_name": "My Laptop",
                "browser": "Chrome",
                "os": "Windows 10",
                "last_used": (datetime.utcnow() - timedelta(days=2)).isoformat(),
                "is_trusted": True,
            }
        ]
    except Exception as e:
        logger.error(f"Error getting trusted devices: {str(e)}")
        return []


def get_recent_logins(voter_id):
    try:
        logs = AuditLog.find_all(
            {
                "user_id": voter_id,
                "user_type": "voter",
                "action": {"$in": ["login", "face_verification_success"]},
            },
            sort=[("timestamp", -1)],
            limit=5,
        )
        recent_logins = []
        for log in logs:
            recent_logins.append(
                {
                    "timestamp": log.get("timestamp", datetime.utcnow()),
                    "action": log.get("action"),
                    "ip_address": log.get("ip_address"),
                    "device": log.get("user_agent", "Unknown Device"),
                }
            )
        return recent_logins
    except Exception as e:
        logger.error(f"Error getting recent logins: {str(e)}")
        return []


def check_suspicious_activities(voter_id):
    try:
        failed_logins = AuditLog.find_all(
            {
                "user_id": voter_id,
                "user_type": "voter",
                "action": {"$in": ["login_failed", "face_verification_failed"]},
                "timestamp": {"$gte": datetime.utcnow() - timedelta(hours=24)},
            }
        )
        suspicious_activities = []
        if len(failed_logins) > 3:
            suspicious_activities.append(
                {
                    "type": "multiple_failed_logins",
                    "count": len(failed_logins),
                    "timestamp": datetime.utcnow().isoformat(),
                    "severity": "medium",
                }
            )
        return suspicious_activities
    except Exception as e:
        logger.error(f"Error checking suspicious activities: {str(e)}")
        return []


@dashboard_bp.route("/elections/<election_id>/results", methods=["GET", "OPTIONS"])
@cross_origin()
def get_election_results_voter(election_id):
    try:
        voter = get_authenticated_voter()
        if not voter:
            return (
                jsonify({"success": False, "message": "Authentication required"}),
                401,
            )

        election = Election.find_by_election_id(election_id)
        if not election:
            return jsonify({"success": False, "message": "Election not found"}), 404

        election_status = election.get("status")
        results_published = election.get("results_published", False)
        results_visibility = election.get("results_visibility", "after_end")

        can_view_results = False
        reason = ""

        if results_published:
            can_view_results = True
            reason = "Results have been published"
        elif election_status == "completed":
            can_view_results = True
            reason = "Election has completed"
        elif election_status == "active" and results_visibility == "live":
            has_voted = Vote.has_voted(election_id, voter["voter_id"])
            if has_voted:
                can_view_results = True
                reason = "Live results available for voters"
            else:
                can_view_results = False
                reason = "Live results available only after voting"
        else:
            can_view_results = False
            reason = "Results not yet available"

        if not can_view_results:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": f"Results not available: {reason}",
                        "reason": reason,
                        "election_status": election_status,
                        "results_published": results_published,
                        "results_visibility": results_visibility,
                    }
                ),
                403,
            )

        results = get_election_results_data(election_id)

        if not results:
            return (
                jsonify({"success": False, "message": "Failed to load results data"}),
                500,
            )

        AuditLog.create_log(
            action="view_election_results",
            user_id=voter["voter_id"],
            user_type="voter",
            details={
                "election_id": election_id,
                "election_title": election["title"],
                "reason": reason,
            },
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent"),
        )

        return jsonify(
            {
                "success": True,
                "results": results,
                "election": {
                    "election_id": election["election_id"],
                    "title": election["title"],
                    "description": election.get("description", ""),
                    "status": election_status,
                    "results_published": results_published,
                    "results_published_at": election.get("results_published_at"),
                    "voting_start": election.get("voting_start"),
                    "voting_end": election.get("voting_end"),
                },
                "access_info": {
                    "reason": reason,
                    "can_view": can_view_results,
                    "voter_has_voted": Vote.has_voted(election_id, voter["voter_id"]),
                },
            }
        )

    except Exception as e:
        logger.error(f"Election results error: {str(e)}", exc_info=True)
        return (
            jsonify({"success": False, "message": "Failed to load election results"}),
            500,
        )


def get_election_results_data(election_id):
    try:
        election = Election.find_by_election_id(election_id)
        if not election:
            return None

        candidates = Candidate.find_all({"election_id": election_id, "is_active": True})

        pipeline = [
            {"$match": {"election_id": election_id, "is_verified": True}},
            {"$group": {"_id": "$candidate_id", "total_votes": {"$sum": 1}}},
            {"$sort": {"total_votes": -1}},
        ]
        vote_results = list(Vote.get_collection().aggregate(pipeline))

        total_votes = sum(result["total_votes"] for result in vote_results)

        candidates_data = []
        for candidate in candidates:
            candidate_votes = next(
                (
                    result
                    for result in vote_results
                    if result["_id"] == candidate["candidate_id"]
                ),
                {"total_votes": 0},
            )
            vote_count = candidate_votes["total_votes"]
            percentage = (
                round((vote_count / total_votes * 100), 2) if total_votes > 0 else 0
            )

            candidates_data.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "full_name": candidate["full_name"],
                    "party": candidate.get("party", "Independent"),
                    "photo": candidate.get("photo"),
                    "biography": candidate.get("biography"),
                    "vote_count": vote_count,
                    "percentage": percentage,
                    "candidate_number": candidate.get("candidate_number"),
                    "rank": len(
                        [c for c in candidates_data if c["vote_count"] > vote_count]
                    )
                    + 1,
                }
            )

        candidates_data.sort(key=lambda x: x["vote_count"], reverse=True)
        for i, candidate in enumerate(candidates_data):
            candidate["rank"] = i + 1

        voter_count = Voter.count({"is_active": True})
        turnout = round((total_votes / voter_count * 100), 2) if voter_count > 0 else 0

        return {
            "election_id": election_id,
            "title": election["title"],
            "description": election.get("description", ""),
            "election_type": election.get("election_type", "general"),
            "status": election.get("status", "completed"),
            "candidates": candidates_data,
            "total_votes": total_votes,
            "voter_turnout": turnout,
            "voting_start": election.get("voting_start"),
            "voting_end": election.get("voting_end"),
            "results_published": election.get("results_published", False),
            "results_published_at": election.get("results_published_at"),
            "created_at": election.get("created_at"),
        }

    except Exception as e:
        logger.error(f"Error getting election results data: {str(e)}")
        return None


def get_device_fingerprints(voter_id):
    try:
        return {
            "user_agent": request.headers.get("User-Agent", "Unknown"),
            "ip_address": request.remote_addr,
            "screen_resolution": "Unknown",
            "timezone": "UTC",
            "language": request.headers.get("Accept-Language", "en-US"),
        }
    except Exception as e:
        logger.error(f"Error getting device fingerprints: {str(e)}")
        return {}


def analyze_location_patterns(voter_id):
    try:
        return {
            "usual_locations": ["Current Location"],
            "unusual_locations": [],
            "last_location": request.remote_addr,
            "location_changes": 0,
        }
    except Exception as e:
        logger.error(f"Error analyzing location patterns: {str(e)}")
        return {}


def get_data_sharing_preferences(voter_id):
    try:
        return {
            "share_analytics": True,
            "share_with_researchers": False,
            "anonymous_participation": True,
            "allow_cookies": True,
            "marketing_emails": False,
        }
    except Exception as e:
        logger.error(f"Error getting data sharing preferences: {str(e)}")
        return {}


def get_notification_preferences(voter_id):
    try:
        return {
            "email_notifications": True,
            "sms_notifications": True,
            "push_notifications": False,
            "election_reminders": True,
            "results_notifications": True,
            "security_alerts": True,
        }
    except Exception as e:
        logger.error(f"Error getting notification preferences: {str(e)}")
        return {}


def get_visibility_settings(voter_id):
    try:
        return {
            "profile_visibility": "private",
            "voting_history_visibility": "anonymous",
            "show_in_searches": False,
            "show_voter_id": False,
        }
    except Exception as e:
        logger.error(f"Error getting visibility settings: {str(e)}")
        return {}


def get_detailed_live_stats():
    try:
        current_time = datetime.utcnow()
        today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)

        today_votes = Vote.count(
            {"vote_timestamp": {"$gte": today_start}, "is_verified": True}
        )

        active_elections = Election.find_all(
            {
                "status": "active",
                "is_active": True,
                "voting_start": {"$lte": current_time},
                "voting_end": {"$gte": current_time},
            }
        )

        upcoming_elections = Election.count(
            {
                "status": "scheduled",
                "is_active": True,
                "voting_start": {"$gt": current_time},
            }
        )

        total_voters = Voter.count({"is_active": True})
        total_verified_voters = Voter.count(
            {
                "is_active": True,
                "email_verified": True,
                "phone_verified": True,
                "id_verified": True,
            }
        )

        hour_ago = current_time - timedelta(hours=1)
        recent_votes = Vote.count({"vote_timestamp": {"$gte": hour_ago}})
        recent_logins = AuditLog.count(
            {"action": "login", "timestamp": {"$gte": hour_ago}}
        )

        return {
            "live_stats": {
                "total_voters": total_voters,
                "verified_voters": total_verified_voters,
                "verification_rate": (
                    round((total_verified_voters / total_voters * 100), 1)
                    if total_voters > 0
                    else 0
                ),
                "active_elections_count": len(active_elections),
                "upcoming_elections_count": upcoming_elections,
                "votes_today": today_votes,
                "recent_votes": recent_votes,
                "recent_logins": recent_logins,
                "connected_users": len(connected_clients),
                "system_uptime": calculate_system_uptime(),
                "server_time": current_time.isoformat(),
                "data_freshness": "real-time",
            },
            "active_elections_details": [
                {
                    "election_id": election.get("election_id"),
                    "title": election.get("title"),
                    "voting_ends": election.get("voting_end"),
                    "total_votes": Vote.count(
                        {"election_id": election.get("election_id")}
                    ),
                    "voter_turnout": election.get("voter_turnout", 0),
                    "time_remaining": calculate_time_remaining(
                        election.get("voting_end")
                    ),
                    "candidates_count": Candidate.count(
                        {"election_id": election.get("election_id")}
                    ),
                }
                for election in active_elections[:5]
            ],
        }
    except Exception as e:
        logger.error(f"Error getting detailed live stats: {str(e)}")
        return {"live_stats": {}, "active_elections_details": []}


def calculate_time_remaining(end_time):
    if not end_time:
        return "N/A"
    current_time = datetime.utcnow()
    if current_time > end_time:
        return "Ended"
    time_diff = end_time - current_time
    days = time_diff.days
    hours = time_diff.seconds // 3600
    minutes = (time_diff.seconds % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def calculate_system_uptime():
    return "99.8%"


def get_voter_insights(voter_id):
    try:
        voter = Voter.find_by_voter_id(voter_id)
        if not voter:
            return {}

        votes = Vote.find_all({"voter_id": voter_id, "is_verified": True})

        if not votes:
            return {
                "first_time_voter": True,
                "insights": [
                    "Welcome to the voting system! Cast your first vote to get started."
                ],
                "suggestions": [
                    "Complete your profile verification",
                    "Explore upcoming elections",
                ],
            }

        votes_by_hour = {}
        votes_by_election_type = {}
        last_vote_date = None

        for vote in votes:
            vote_time = vote.get("vote_timestamp")
            if vote_time:
                hour = vote_time.hour
                votes_by_hour[hour] = votes_by_hour.get(hour, 0) + 1
                election = Election.find_by_election_id(vote["election_id"])
                if election:
                    election_type = election.get("election_type", "unknown")
                    votes_by_election_type[election_type] = (
                        votes_by_election_type.get(election_type, 0) + 1
                    )
            if not last_vote_date or vote_time > last_vote_date:
                last_vote_date = vote_time

        insights = []
        if len(votes) >= 3:
            insights.append(
                f"You've voted in {len(votes)} elections - keep up the great civic engagement!"
            )
        if votes_by_hour:
            most_active_hour = max(votes_by_hour, key=votes_by_hour.get)
            insights.append(
                f"Your most active voting time is around {most_active_hour}:00"
            )
        if votes_by_election_type:
            preferred_type = max(votes_by_election_type, key=votes_by_election_type.get)
            insights.append(f"You prefer {preferred_type.replace('_', ' ')} elections")

        voting_streak = calculate_voting_streak_detailed(voter_id)
        if voting_streak["current_streak"] > 1:
            insights.append(
                f"Current voting streak: {voting_streak['current_streak']} elections"
            )

        return {
            "total_votes": len(votes),
            "voting_since": (
                votes[0].get("vote_timestamp").strftime("%B %Y") if votes else None
            ),
            "last_vote": (
                last_vote_date.strftime("%B %d, %Y") if last_vote_date else None
            ),
            "voting_streak": voting_streak,
            "insights": insights,
            "participation_rate": calculate_participation_rate(voter_id),
            "constituency_ranking": get_constituency_ranking(voter_id),
        }
    except Exception as e:
        logger.error(f"Error getting voter insights: {str(e)}")
        return {}


def calculate_voting_streak_detailed(voter_id):
    try:
        votes = Vote.find_all(
            {"voter_id": voter_id, "is_verified": True}, sort=[("vote_timestamp", -1)]
        )
        if not votes:
            return {
                "current_streak": 0,
                "longest_streak": 0,
                "last_vote_date": None,
                "days_since_last_vote": None,
            }

        vote_dates = []
        for vote in votes:
            vote_date = vote.get("vote_timestamp")
            if vote_date:
                vote_dates.append(vote_date.date())

        if not vote_dates:
            return {
                "current_streak": 0,
                "longest_streak": 0,
                "last_vote_date": None,
                "days_since_last_vote": None,
            }

        current_streak = 1
        longest_streak = 1
        streak = 1
        for i in range(1, len(vote_dates)):
            date_diff = (vote_dates[i - 1] - vote_dates[i]).days
            if date_diff <= 30:
                streak += 1
                current_streak = streak if i == 1 else current_streak
                longest_streak = max(longest_streak, streak)
            else:
                streak = 1

        last_vote_date = vote_dates[0]
        days_since_last_vote = (datetime.utcnow().date() - last_vote_date).days

        return {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "last_vote_date": last_vote_date.isoformat(),
            "days_since_last_vote": days_since_last_vote,
            "total_elections_in_streak": len(vote_dates),
        }
    except Exception as e:
        logger.error(f"Error calculating voting streak: {str(e)}")
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "last_vote_date": None,
            "days_since_last_vote": None,
        }


def get_security_metrics(voter_id):
    try:
        voter = Voter.find_by_voter_id(voter_id)
        if not voter:
            return {}

        week_ago = datetime.utcnow() - timedelta(days=7)
        security_events = AuditLog.find_all(
            {
                "user_id": voter_id,
                "user_type": "voter",
                "action": {
                    "$in": [
                        "login",
                        "login_failed",
                        "password_change",
                        "profile_update",
                    ]
                },
                "timestamp": {"$gte": week_ago},
            },
            sort=[("timestamp", -1)],
            limit=10,
        )

        security_score = calculate_security_score(voter)
        devices = get_device_information(voter_id)

        login_attempts = AuditLog.find_all(
            {
                "user_id": voter_id,
                "user_type": "voter",
                "action": {"$in": ["login", "login_failed"]},
                "timestamp": {"$gte": week_ago},
            },
            sort=[("timestamp", -1)],
        )

        failed_attempts = [
            log for log in login_attempts if log.get("action") == "login_failed"
        ]

        return {
            "security_score": security_score,
            "verification_status": {
                "email": voter.get("email_verified", False),
                "phone": voter.get("phone_verified", False),
                "id": voter.get("id_verified", False),
                "face": voter.get("face_verified", False),
                "overall": all(
                    [
                        voter.get("email_verified", False),
                        voter.get("phone_verified", False),
                        voter.get("id_verified", False),
                        voter.get("face_verified", False),
                    ]
                ),
            },
            "account_age": calculate_account_age_days(voter),
            "last_password_change": voter.get("last_password_change"),
            "two_factor_enabled": voter.get("two_factor_enabled", False),
            "recent_security_events": [
                {
                    "action": event.get("action"),
                    "timestamp": event.get("timestamp"),
                    "ip_address": event.get("ip_address"),
                    "details": event.get("details", {}),
                }
                for event in security_events
            ],
            "failed_login_attempts": {
                "last_24_hours": len(
                    [
                        f
                        for f in failed_attempts
                        if f.get("timestamp") > datetime.utcnow() - timedelta(hours=24)
                    ]
                ),
                "last_week": len(failed_attempts),
                "recent_attempts": [
                    {
                        "timestamp": attempt.get("timestamp"),
                        "ip_address": attempt.get("ip_address"),
                    }
                    for attempt in failed_attempts[:3]
                ],
            },
            "device_security": {
                "trusted_devices": len(devices.get("trusted", [])),
                "recent_devices": devices.get("recent", []),
                "unusual_activity": check_unusual_activity(voter_id, devices),
            },
            "recommendations": generate_security_recommendations(voter, security_score),
        }
    except Exception as e:
        logger.error(f"Error getting security metrics: {str(e)}")
        return {}


def calculate_security_score(voter):
    score = 0
    if voter.get("email_verified"):
        score += 10
    if voter.get("phone_verified"):
        score += 10
    if voter.get("id_verified"):
        score += 15
    if voter.get("face_verified"):
        score += 15
    if voter.get("two_factor_enabled"):
        score += 20

    account_age_days = calculate_account_age_days(voter)
    if account_age_days > 365:
        score += 10
    elif account_age_days > 180:
        score += 7
    elif account_age_days > 30:
        score += 5
    elif account_age_days > 7:
        score += 3

    if voter.get("last_login"):
        days_since_login = (datetime.utcnow() - voter["last_login"]).days
        if days_since_login <= 7:
            score += 5
        elif days_since_login <= 30:
            score += 3

    return min(100, score)


def calculate_account_age_days(voter):
    created_at = voter.get("created_at")
    if not created_at:
        return 0
    if isinstance(created_at, dict) and "$date" in created_at:
        created_date = datetime.fromisoformat(
            created_at["$date"].replace("Z", "+00:00")
        )
    elif isinstance(created_at, str):
        created_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    elif isinstance(created_at, datetime):
        created_date = created_at
    else:
        return 0
    return (datetime.utcnow() - created_date).days


def get_device_information(voter_id):
    try:
        month_ago = datetime.utcnow() - timedelta(days=30)
        device_logs = AuditLog.aggregate(
            [
                {
                    "$match": {
                        "user_id": voter_id,
                        "user_type": "voter",
                        "action": "login",
                        "timestamp": {"$gte": month_ago},
                        "user_agent": {"$exists": True},
                    }
                },
                {
                    "$group": {
                        "_id": {
                            "user_agent": "$user_agent",
                            "ip_address": "$ip_address",
                        },
                        "last_login": {"$max": "$timestamp"},
                        "login_count": {"$sum": 1},
                    }
                },
                {"$sort": {"last_login": -1}},
            ]
        )
        devices = list(device_logs)

        trusted_devices = []
        recent_devices = []
        for device in devices[:5]:
            device_info = {
                "user_agent": device["_id"]["user_agent"],
                "ip_address": device["_id"]["ip_address"],
                "last_login": device["last_login"],
                "login_count": device["login_count"],
                "device_type": parse_user_agent(device["_id"]["user_agent"]),
            }
            if device["login_count"] >= 3:
                trusted_devices.append(device_info)
            else:
                recent_devices.append(device_info)

        return {
            "trusted": trusted_devices,
            "recent": recent_devices,
            "total_devices": len(devices),
        }
    except Exception as e:
        logger.error(f"Error getting device information: {str(e)}")
        return {"trusted": [], "recent": [], "total_devices": 0}


def parse_user_agent(user_agent):
    if not user_agent:
        return "Unknown"
    user_agent_lower = user_agent.lower()
    if (
        "mobile" in user_agent_lower
        or "android" in user_agent_lower
        or "iphone" in user_agent_lower
    ):
        return "Mobile"
    elif "tablet" in user_agent_lower or "ipad" in user_agent_lower:
        return "Tablet"
    elif "windows" in user_agent_lower:
        return "Windows PC"
    elif "mac" in user_agent_lower:
        return "Mac"
    elif "linux" in user_agent_lower:
        return "Linux"
    else:
        return "Desktop"


def check_unusual_activity(voter_id, devices):
    unusual_activities = []
    recent_devices = devices.get("recent", [])
    if len(recent_devices) > 2:
        unusual_activities.append(
            {
                "type": "multiple_new_devices",
                "count": len(recent_devices),
                "message": f"Logged in from {len(recent_devices)} new devices recently",
            }
        )

    current_hour = datetime.utcnow().hour
    if current_hour < 5 or current_hour > 22:
        unusual_activities.append(
            {
                "type": "unusual_time",
                "hour": current_hour,
                "message": f"Activity detected at unusual hour ({current_hour}:00 UTC)",
            }
        )

    return unusual_activities


def generate_security_recommendations(voter, security_score):
    recommendations = []
    if not voter.get("two_factor_enabled"):
        recommendations.append(
            {
                "priority": "high",
                "action": "enable_2fa",
                "message": "Enable two-factor authentication for enhanced security",
                "icon": "shield-check",
            }
        )
    if not voter.get("email_verified"):
        recommendations.append(
            {
                "priority": "high",
                "action": "verify_email",
                "message": "Verify your email address",
                "icon": "envelope-check",
            }
        )
    if not voter.get("phone_verified"):
        recommendations.append(
            {
                "priority": "medium",
                "action": "verify_phone",
                "message": "Verify your phone number",
                "icon": "phone-check",
            }
        )
    if not voter.get("face_verified"):
        recommendations.append(
            {
                "priority": "medium",
                "action": "verify_face",
                "message": "Complete face verification",
                "icon": "face-id",
            }
        )
    if security_score < 70:
        recommendations.append(
            {
                "priority": "medium",
                "action": "improve_security",
                "message": "Improve your security score by completing verifications",
                "icon": "shield-exclamation",
            }
        )

    account_age = calculate_account_age_days(voter)
    if account_age > 90:
        recommendations.append(
            {
                "priority": "low",
                "action": "change_password",
                "message": "Consider changing your password regularly",
                "icon": "key",
            }
        )

    return recommendations


@dashboard_bp.route("/enhanced-overview-data", methods=["GET"])
@cross_origin()
@voter_required
def get_enhanced_overview_data():
    try:
        voter = request.voter

        live_stats_data = get_detailed_live_stats()
        voter_insights = get_voter_insights(voter["voter_id"])
        upcoming_elections = get_upcoming_elections(voter, limit=3)
        notifications = get_recent_notifications(voter["voter_id"], limit=5)
        quick_actions = generate_quick_actions(voter)

        return jsonify(
            {
                "success": True,
                "data": {
                    "live_stats": live_stats_data["live_stats"],
                    "active_elections": live_stats_data["active_elections_details"],
                    "voter_insights": voter_insights,
                    "upcoming_elections": upcoming_elections,
                    "notifications": notifications,
                    "quick_actions": quick_actions,
                    "profile_completion": calculate_profile_completion(voter),
                    "verification_status": get_verification_status(voter),
                    "last_updated": datetime.utcnow().isoformat(),
                },
            }
        )

    except Exception as e:
        logger.error(f"Enhanced overview data error: {str(e)}", exc_info=True)
        return (
            jsonify(
                {"success": False, "message": "Failed to load enhanced overview data"}
            ),
            500,
        )


@dashboard_bp.route("/security-metrics", methods=["GET"])
@cross_origin()
@voter_required
def get_security_metrics_route():
    try:
        voter = request.voter
        security_data = get_security_metrics(voter["voter_id"])
        return jsonify({"success": True, "security_metrics": security_data})

    except Exception as e:
        logger.error(f"Security metrics error: {str(e)}")
        return (
            jsonify({"success": False, "message": "Failed to load security metrics"}),
            500,
        )


def generate_quick_actions(voter):
    actions = []

    active_elections = get_active_elections(voter)
    if active_elections:
        eligible_elections = [e for e in active_elections if e.get("can_vote", False)]
        if eligible_elections:
            actions.append(
                {
                    "id": "vote_now",
                    "title": "Vote Now",
                    "description": f"Cast your vote in {len(eligible_elections)} active election(s)",
                    "icon": "vote-yea",
                    "url": "/dashboard?tab=elections",
                    "priority": "high",
                    "color": "primary",
                }
            )

    completion = calculate_profile_completion(voter)
    if completion < 100:
        actions.append(
            {
                "id": "complete_profile",
                "title": "Complete Profile",
                "description": f"Your profile is {completion}% complete",
                "icon": "user-edit",
                "url": "/dashboard?tab=profile",
                "priority": "medium",
                "color": "warning",
            }
        )

    verification_status = get_verification_status(voter)
    if verification_status != "Fully Verified":
        actions.append(
            {
                "id": "verify_account",
                "title": "Verify Account",
                "description": "Complete account verification",
                "icon": "shield-check",
                "url": "/dashboard?tab=security",
                "priority": "medium",
                "color": "info",
            }
        )

    actions.append(
        {
            "id": "digital_id",
            "title": "Get Digital ID",
            "description": "Generate your digital voter ID",
            "icon": "id-card",
            "url": "#",
            "action": "generateDigitalID",
            "priority": "low",
            "color": "success",
        }
    )

    return actions


# Final version of get_enhanced_dashboard_data (only one definition)
def get_enhanced_dashboard_data(voter):
    return {
        "voter_info": get_enhanced_voter_info(voter),
        "election_info": get_enhanced_election_info(voter),
        "quick_stats": get_enhanced_quick_stats(voter),
        "notifications": get_recent_notifications(voter["voter_id"]),
        "analytics": get_voter_analytics(voter["voter_id"]),
        "system_status": get_system_status(),
        "real_time_updates": {
            "last_updated": datetime.utcnow().isoformat(),
            "active_elections_count": get_active_elections_count(),
            "total_votes_today": get_today_votes_count(),
            "connected_users": get_connected_users_count(),
        },
        "live_stats": get_detailed_live_stats()["live_stats"],
        "voter_insights": get_voter_insights(voter["voter_id"]),
        "security_status": get_security_metrics(voter["voter_id"]),
    }


def get_socketio():
    try:
        if hasattr(current_app, "socketio"):
            return current_app.socketio
        else:
            logger.warning("SocketIO not found in current app context")
            return None
    except Exception as e:
        logger.error(f"Error getting SocketIO: {str(e)}")
        return None


def broadcast_from_dashboard(event, data, room=None):
    try:
        socketio_instance = get_socketio()
        if socketio_instance:
            logger.info(f"Broadcasting {event} to room {room}")
            if room:
                socketio_instance.emit(event, data, room=room)
            else:
                socketio_instance.emit(event, data)
            return True
        else:
            logger.warning(f"Cannot broadcast {event}: SocketIO not available")
            return False
    except Exception as e:
        logger.error(f"Dashboard broadcast error: {str(e)}")
        return False


@dashboard_bp.route("/create-test-election", methods=["POST"])
@admin_required
def create_test_election():
    try:
        election_data = {
            "election_id": "TEST_ELECTION_001",
            "title": "Sample General Election 2024",
            "description": "This is a test election for development purposes",
            "election_type": "general",
            "status": "active",
            "voting_start": datetime.utcnow(),
            "voting_end": datetime.utcnow() + timedelta(days=7),
            "registration_start": datetime.utcnow() - timedelta(days=1),
            "registration_end": datetime.utcnow() + timedelta(days=6),
            "constituency": "General Constituency",
            "is_active": True,
            "require_face_verification": False,
        }

        election_id = Election.create_election(election_data)

        candidates = [
            {
                "candidate_id": "CAND001",
                "election_id": "TEST_ELECTION_001",
                "full_name": "John Smith",
                "party": "Democratic Party",
                "biography": "Experienced leader with 10 years in public service",
                "is_approved": True,
                "is_active": True,
            },
            {
                "candidate_id": "CAND002",
                "election_id": "TEST_ELECTION_001",
                "full_name": "Sarah Johnson",
                "party": "Republican Party",
                "biography": "Business leader and community advocate",
                "is_approved": True,
                "is_active": True,
            },
        ]

        for candidate in candidates:
            Candidate.create_candidate(candidate)

        return jsonify(
            {
                "success": True,
                "message": "Test election created successfully",
                "election_id": election_id,
            }
        )

    except Exception as e:
        logger.error(f"Create test election error: {str(e)}")
        return (
            jsonify({"success": False, "message": "Failed to create test election"}),
            500,
        )


def normalize_date(date_value):
    if not date_value:
        return None

    if isinstance(date_value, datetime):
        return date_value

    if isinstance(date_value, dict) and "$date" in date_value:
        date_str = date_value["$date"]
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception as e:
            logger.warning(f"Failed to parse MongoDB date: {e}")
            return None

    if isinstance(date_value, str):
        try:
            return datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        except Exception:
            try:
                return datetime.strptime(date_value, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                try:
                    return datetime.strptime(date_value, "%Y-%m-%d %H:%M:%S")
                except Exception:
                    try:
                        return datetime.strptime(date_value, "%Y-%m-%d")
                    except Exception:
                        return None

    return None


def calculate_consistency_score(voting_history):
    if not voting_history or len(voting_history) < 2:
        return 0

    years = {}
    for vote in voting_history:
        vote_date = vote.get("vote_timestamp")
        if vote_date:
            try:
                if isinstance(vote_date, dict) and "$date" in vote_date:
                    date_str = vote_date["$date"]
                    year = datetime.fromisoformat(date_str.replace("Z", "+00:00")).year
                elif isinstance(vote_date, str):
                    year = datetime.fromisoformat(vote_date.replace("Z", "+00:00")).year
                else:
                    continue
                years[year] = years.get(year, 0) + 1
            except Exception as e:
                logger.warning(f"Error parsing vote date: {e}")
                continue

    if not years:
        return 0

    avg_votes_per_year = sum(years.values()) / len(years)
    max_possible_consistency = 10
    return min(100, (avg_votes_per_year / max_possible_consistency) * 100)


def assess_password_strength(voter_id):
    return "Strong"


def calculate_account_age(voter):
    if not voter.get("created_at"):
        return 0
    try:
        if isinstance(voter["created_at"], dict) and "$date" in voter["created_at"]:
            created_date = datetime.fromisoformat(
                voter["created_at"]["$date"].replace("Z", "+00:00")
            )
        elif isinstance(voter["created_at"], str):
            created_date = datetime.fromisoformat(
                voter["created_at"].replace("Z", "+00:00")
            )
        elif isinstance(voter["created_at"], datetime):
            created_date = voter["created_at"]
        else:
            return 0
        return max(0, (datetime.utcnow() - created_date).days)
    except Exception as e:
        logger.error(f"Error calculating account age: {str(e)}")
        return 0
