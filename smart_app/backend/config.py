import os
from datetime import timedelta
from dotenv import load_dotenv
from urllib.parse import quote_plus

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.getenv(
        "APP_SECRET", "eb153fcfa5a755ae94a949f86fbbaa5c53cd2b7faf5c848ba09307d2f7acdce1"
    )

    MONGO_USERNAME = os.getenv("MONGO_USERNAME", "admin")
    MONGO_PASSWORD = quote_plus(os.getenv("MONGO_PASSWORD", "Admin123"))
    MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
    MONGO_PORT = os.getenv("MONGO_PORT", "27017")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "smart_voting_system")

    MONGO_URI = os.getenv(
        "MONGO_URI",
        f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB_NAME}?authSource=admin&retryWrites=true&w=majority",
    )

    REDIS_HOST = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT = os.getenv("REDIS_PORT", 6379)
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
    REDIS_DB_SESSION = int(os.getenv("REDIS_DB_SESSION", 0))
    REDIS_DB_CACHE = int(os.getenv("REDIS_DB_CACHE", 1))

    SESSION_TYPE = "redis"
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = "session:"
    SESSION_REDIS = None

    # Cache configuration
    CACHE_TYPE = "RedisCache"
    CACHE_REDIS_HOST = REDIS_HOST
    CACHE_REDIS_PORT = REDIS_PORT
    CACHE_REDIS_PASSWORD = REDIS_PASSWORD
    CACHE_REDIS_DB = REDIS_DB_CACHE
    CACHE_DEFAULT_TIMEOUT = 300
    CACHE_KEY_PREFIX = "cache:"

    JWT_SECRET_KEY = (
        os.environ.get("JWT_SECRET_KEY")
        or "sUJbaMMUAKYojj0dFe94jO-ld2oc028u3qw2KU71Ui0"
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)

    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file size
    UPLOAD_FOLDER = "uploads"
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

    FACE_RECOGNITION_TOLERANCE = float(os.getenv("FACE_MATCH_THRESHOLD", 0.6))
    FACE_ENCODING_MODEL = "hog"  # 'hog' for CPU, 'cnn' for GPU

    DASHBOARD_CACHE_TIMEOUT = 300  # 5 minutes
    MAX_DASHBOARD_RECORDS = 1000


class DevelopmentConfig(Config):
    DEBUG = True

    MONGO_URI = os.getenv(
        "MONGO_URI",
        f"mongodb://{Config.MONGO_USERNAME}:{Config.MONGO_PASSWORD}@{Config.MONGO_HOST}:{Config.MONGO_PORT}/smart_voting_dev?authSource=admin&retryWrites=true&w=majority",
    )


class ProductionConfig(Config):
    DEBUG = False
    MONGO_URI = os.getenv(
        "MONGO_URI",
        f"mongodb://{Config.MONGO_USERNAME}:{Config.MONGO_PASSWORD}@{Config.MONGO_HOST}:{Config.MONGO_PORT}/smart_voting_system?authSource=admin&retryWrites=true&w=majority",
    )


class TestingConfig(Config):
    TESTING = True
    MONGO_URI = f"mongodb://{Config.MONGO_USERNAME}:{Config.MONGO_PASSWORD}@{Config.MONGO_HOST}:{Config.MONGO_PORT}/smart_voting_test?authSource=admin&retryWrites=true&w=majority"


config_map = {
    "DEVELOPMENT": DevelopmentConfig,
    "PRODUCTION": ProductionConfig,
    "TESTING": TestingConfig,
    "default": DevelopmentConfig,
}
