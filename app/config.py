import os
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def database_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        return f"sqlite:///{BASE_DIR / 'human_brain_dev.sqlite3'}"
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////") and url != "sqlite:///:memory:":
        relative_path = url.removeprefix("sqlite:///")
        return f"sqlite:///{BASE_DIR / relative_path}"
    return url


class Config:
    APP_NAME = "Human-Brain"
    HUMAN_BRAIN_URL = os.getenv("HUMAN_BRAIN_URL", "").rstrip("/")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = None
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/2")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    REMEMBER_COOKIE_DURATION = timedelta(hours=12)
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    CORS_ENABLED = os.getenv("CORS_ENABLED", "false").lower() == "true"
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    FAISS_INDEX_DIR = os.getenv("FAISS_INDEX_DIR", str(BASE_DIR / "faiss_indexes"))
    SNAPSHOT_STORAGE_ENABLED = os.getenv("SNAPSHOT_STORAGE_ENABLED", "false").lower() == "true"
    SNAPSHOT_DIR = os.getenv("SNAPSHOT_DIR", str(BASE_DIR / "uploads" / "snapshots"))
    MEMORY_UPLOAD_DIR = os.getenv("MEMORY_UPLOAD_DIR", str(BASE_DIR / "uploads" / "memory_uploads"))
    YOLO_MODEL = os.getenv("YOLO_MODEL", "models/yolov8n.pt")
    AUTO_STORE_CONSOLIDATED_MEMORY = os.getenv("AUTO_STORE_CONSOLIDATED_MEMORY", "false").lower() == "true"
    LOCAL_FIRST_PRIVACY_MODE = os.getenv("LOCAL_FIRST_PRIVACY_MODE", "true").lower() == "true"
    RUN_JOBS_INLINE_ON_BROKER_FAILURE = os.getenv("RUN_JOBS_INLINE_ON_BROKER_FAILURE", "false").lower() == "true"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    VECTOR_STARTUP_WARMUP = os.getenv("VECTOR_STARTUP_WARMUP", "true").lower() == "true"
    VECTOR_AUTO_REPAIR_ON_WARMUP = os.getenv("VECTOR_AUTO_REPAIR_ON_WARMUP", "true").lower() == "true"


class DevelopmentConfig(Config):
    DEBUG = True
    AUTO_CREATE_DEV_DB = True
    RUN_JOBS_INLINE_ON_BROKER_FAILURE = True


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    CELERY_TASK_ALWAYS_EAGER = True
    RATELIMIT_ENABLED = False
    AUTO_CREATE_DEV_DB = True
    RUN_JOBS_INLINE_ON_BROKER_FAILURE = True
    EMBEDDING_MODEL = "hash"
    VECTOR_STARTUP_WARMUP = False
    VECTOR_AUTO_REPAIR_ON_WARMUP = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    AUTO_CREATE_DEV_DB = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
