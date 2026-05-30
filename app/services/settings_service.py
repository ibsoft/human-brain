from flask import current_app, has_app_context

from app.extensions import db
from app.models import AppSetting


DEFAULT_SETTINGS = {
    "local_first_privacy_mode": {
        "value": True,
        "description": "Keep data local and disable external sharing by default.",
    },
    "auto_store_consolidated_memory": {
        "value": False,
        "description": "Automatically store consolidated session findings without manual approval.",
    },
    "sensitivity_firewall": {
        "value": {
            "block_high": True,
            "block_secret": True,
            "allow_sensitive_context_for_admin": False,
        },
        "description": "Controls which sensitive memories can enter agent context.",
    },
    "camera_enabled": {
        "value": False,
        "description": "Allow the local YOLO vision subsystem to access a webcam.",
    },
    "snapshot_storage_enabled": {
        "value": False,
        "description": "Persist optional camera snapshots. Metadata is stored by default.",
    },
    "vision_auto_save": {
        "value": False,
        "description": "Automatically save detected objects as vision memories.",
    },
    "retention_days": {
        "value": 365,
        "description": "Default memory retention window for expiration jobs.",
    },
    "embedding_model": {
        "value": "sentence-transformers/all-MiniLM-L6-v2",
        "description": "Active embedding model. Use ollama:<model-name> for local Ollama embeddings.",
    },
    "embedding_models": {
        "value": [
            "sentence-transformers/all-MiniLM-L6-v2",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            "ollama:paraphrase-multilingual",
            "ollama:nomic-embed-text",
            "hash",
        ],
        "description": "Allowed embedding model choices shown in Settings.",
    },
    "ollama_base_url": {
        "value": "http://localhost:11434",
        "description": "Local Ollama server URL used when embedding_model starts with ollama:.",
    },
    "backup_schedule": {
        "value": {"enabled": False, "frequency": "daily", "time": "02:00", "keep_last": 7},
        "description": "Local scheduled backup policy for celery beat or external scheduler.",
    },
    "yolo_model": {
        "value": "yolo26x.pt",
        "description": "Active Ultralytics YOLO model used for local object detection.",
    },
    "vision_models": {
        "value": ["yolo26x.pt", "yolov8n.pt", "yolov8s.pt", "yolov8m.pt", "yolov8l.pt", "yolov8x.pt"],
        "description": "Allowed local or downloadable vision model names/paths.",
    },
    "vision_backend": {
        "value": "ultralytics",
        "description": "Vision inference backend. The first release supports Ultralytics YOLO.",
    },
    "camera_index": {
        "value": 0,
        "description": "OpenCV camera device index.",
    },
    "camera_api": {
        "value": "auto",
        "description": "OpenCV capture API: auto, v4l2, dshow, avfoundation.",
    },
}


class SettingsService:
    @staticmethod
    def ensure_defaults():
        for key, payload in DEFAULT_SETTINGS.items():
            value = payload["value"]
            if key == "embedding_model" and has_app_context():
                value = current_app.config.get("EMBEDDING_MODEL", value)
            if not AppSetting.query.filter_by(key=key).first():
                db.session.add(AppSetting(key=key, value=value, description=payload["description"]))
        db.session.commit()

    @staticmethod
    def get(key, default=None):
        setting = AppSetting.query.filter_by(key=key).first()
        if setting is None:
            if key == "embedding_model" and has_app_context():
                return current_app.config.get("EMBEDDING_MODEL", default)
            return DEFAULT_SETTINGS.get(key, {}).get("value", default)
        return setting.value

    @staticmethod
    def all():
        SettingsService.ensure_defaults()
        return AppSetting.query.order_by(AppSetting.key.asc()).all()

    @staticmethod
    def update(values):
        SettingsService.ensure_defaults()
        for key, value in values.items():
            setting = AppSetting.query.filter_by(key=key).first()
            if setting:
                setting.value = value
        db.session.commit()
