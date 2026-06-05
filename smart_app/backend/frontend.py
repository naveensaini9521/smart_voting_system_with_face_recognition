from flask import Blueprint, send_from_directory, jsonify
import os

frontend_bp = Blueprint('frontend', __name__)

react_build_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
index_file = os.path.join(react_build_path, 'index.html')


@frontend_bp.route('/', defaults={'path': ''})
@frontend_bp.route('/<path:path>')
def serve_react_app(path):

    file_path = os.path.join(react_build_path, path)

    if path and os.path.exists(file_path):
        return send_from_directory(react_build_path, path)

    if os.path.exists(index_file):
        return send_from_directory(react_build_path, 'index.html')

    return jsonify({"error": "Frontend not built"}), 404


@frontend_bp.errorhandler(404)
def not_found(error):
    if os.path.exists(index_file):
        return send_from_directory(react_build_path, 'index.html')
    return jsonify({'message': 'Not found'}), 404


@frontend_bp.errorhandler(500)
def internal_error(error):
    return jsonify({'message': 'Internal server error'}), 500


@frontend_bp.route('/api/test-frontend')
def test_frontend():
    return jsonify({'message': 'Frontend route is working!', 'status': 'success'})