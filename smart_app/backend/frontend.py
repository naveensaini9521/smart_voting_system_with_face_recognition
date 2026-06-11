# smart_app/backend/routes/frontend.py
from flask import Blueprint, send_from_directory, jsonify, request
import os
import logging

logger = logging.getLogger(__name__)
frontend_bp = Blueprint("frontend", __name__)

REACT_BUILD = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
)


@frontend_bp.route("/", defaults={"path": ""})
@frontend_bp.route("/<path:path>")
def serve_react(path):

    if path.startswith("api/"):
        return jsonify({"error": "API endpoint not found"}), 404

    full_path = os.path.join(REACT_BUILD, path)
    if path and os.path.isfile(full_path):
        return send_from_directory(REACT_BUILD, path)

    try:
        return send_from_directory(REACT_BUILD, "index.html")
    except Exception as e:
        logger.error(f"Failed to serve index.html from {REACT_BUILD}: {e}")
        return jsonify({"error": "Frontend build not found"}), 500


@frontend_bp.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "API endpoint not found"}), 404
    return send_from_directory(REACT_BUILD, "index.html")
