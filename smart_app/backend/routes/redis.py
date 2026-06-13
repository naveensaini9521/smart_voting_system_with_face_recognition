import os
import logging
from flask import Blueprint, jsonify
import redis

logger = logging.getLogger(__name__)

redis_bp = Blueprint("redis", __name__)


@redis_bp.route("/test-connection", methods=["GET"])
def test_redis_connection():
    """Test Redis connection."""
    try:
        r = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True,
        )
        r.set("test", "ok")
        value = r.get("test")

        return jsonify(
            {
                "status": "success",
                "message": "Redis connection successful",
                "test_key": "test",
                "test_value": value,
            }
        )
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Redis connection failed: {str(e)}",
                }
            ),
            500,
        )
