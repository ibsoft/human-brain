import os

from flask import current_app, has_app_context

from app.extensions import db
from app.models import AppSetting


DEFAULT_SETTINGS = {
    "local_first_privacy_mode": {
        "value": True,
        "description": "Keep data local and disable external sharing by default.",
    },
    "public_base_url": {
        "value": "",
        "env": "HUMAN_BRAIN_URL",
        "value_type": "string",
        "description": "Public external URL used in generated asset links, for example https://human-brain.example.lan.",
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
    "vision_auto_save_interval_seconds": {
        "value": 30,
        "description": "Minimum seconds between automatic vision memory saves for the same detected object set.",
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
    "duplicate_consolidation": {
        "value": {"enabled": False, "frequency": "daily", "time": "03:00", "min_group_size": 2, "archive_duplicates": True},
        "description": "Scheduled duplicate memory consolidation policy.",
    },
    "agent_api_logging_enabled": {
        "value": True,
        "description": "Write agent API requests and responses to rotated JSONL logs.",
    },
    "agent_api_log_level": {
        "value": "info",
        "description": "Agent API JSONL log level: debug, info, or warning.",
    },
    "agent_api_log_max_mb": {
        "value": 10,
        "description": "Rotate agent API JSONL logs after this many megabytes.",
    },
    "agent_api_log_keep_files": {
        "value": 5,
        "description": "Number of rotated agent API JSONL log files to keep.",
    },
    "agent_auto_sessions": {
        "value": True,
        "description": "Encourage agents to use explicit API sessions and session_id fields.",
    },
    "yolo_model": {
        "value": "models/yolov8n.pt",
        "description": "Active Ultralytics YOLO model used for local object detection.",
    },
    "yolo_device": {
        "value": "cpu",
        "description": "Ultralytics YOLO inference device: cpu, cuda, cuda:0, cuda:1, or mps.",
    },
    "vision_models": {
        "value": ["models/yolov8n.pt", "models/yolov8s.pt", "models/yolov8m.pt", "models/yolov8l.pt", "models/yolov8x.pt"],
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
    "reranker_enabled": {
        "value": False,
        "env": "RERANKER_ENABLED",
        "value_type": "bool",
        "description": "Enable the optional reranking layer.",
    },
    "reranker_provider": {
        "value": "none",
        "env": "RERANKER_PROVIDER",
        "value_type": "string",
        "description": "Reranker provider: none, cross_encoder, or ollama.",
    },
    "reranker_default_mode": {
        "value": "conditional",
        "env": "RERANKER_DEFAULT_MODE",
        "value_type": "string",
        "description": "Reranking mode: off, always, or conditional.",
    },
    "reranker_cross_encoder_model": {
        "value": "BAAI/bge-reranker-base",
        "env": "RERANKER_CROSS_ENCODER_MODEL",
        "value_type": "string",
        "description": "Sentence Transformers CrossEncoder model name.",
    },
    "reranker_ollama_base_url": {
        "value": "http://localhost:11434",
        "env": "RERANKER_OLLAMA_BASE_URL",
        "value_type": "string",
        "description": "Ollama server URL for LLM reranking.",
    },
    "reranker_ollama_model": {
        "value": "qwen2.5:7b",
        "env": "RERANKER_OLLAMA_MODEL",
        "value_type": "string",
        "description": "Ollama model used for LLM reranking.",
    },
    "reranker_top_n": {
        "value": 5,
        "env": "RERANKER_TOP_N",
        "value_type": "int",
        "description": "Number of top candidates to rerank.",
    },
    "reranker_return_k": {
        "value": 5,
        "env": "RERANKER_RETURN_K",
        "value_type": "int",
        "description": "Maximum reranked candidates to return before final top_k.",
    },
    "reranker_timeout_ms": {
        "value": 5000,
        "env": "RERANKER_TIMEOUT_MS",
        "value_type": "int",
        "description": "Reranker timeout in milliseconds.",
    },
    "reranker_model_load_timeout_ms": {
        "value": 30000,
        "env": "RERANKER_MODEL_LOAD_TIMEOUT_MS",
        "value_type": "int",
        "description": "Maximum time to wait for a local reranker model to load.",
    },
    "reranker_weight": {
        "value": 0.70,
        "env": "RERANKER_WEIGHT",
        "value_type": "float",
        "description": "Final score weight for reranker score.",
    },
    "faiss_weight": {
        "value": 0.30,
        "env": "FAISS_WEIGHT",
        "value_type": "float",
        "description": "Final score weight for FAISS semantic score.",
    },
    "trust_weight": {
        "value": 0.05,
        "env": "TRUST_WEIGHT",
        "value_type": "float",
        "description": "Final score weight for memory trust.",
    },
    "importance_weight": {
        "value": 0.05,
        "env": "IMPORTANCE_WEIGHT",
        "value_type": "float",
        "description": "Final score weight for memory importance.",
    },
    "reranker_conditional_threshold": {
        "value": 0.08,
        "env": "RERANKER_CONDITIONAL_THRESHOLD",
        "value_type": "float",
        "description": "Top-score gap threshold for conditional reranking.",
    },
    "reranker_max_text_chars": {
        "value": 1500,
        "env": "RERANKER_MAX_TEXT_CHARS",
        "value_type": "int",
        "description": "Maximum candidate text length sent to the reranker.",
    },
    "reranker_device": {
        "value": "cpu",
        "env": "RERANKER_DEVICE",
        "value_type": "string",
        "description": "Cross-encoder device: cpu or cuda.",
    },
}


def _coerce_env_value(raw, value_type):
    if value_type == "bool":
        return str(raw).lower() in {"1", "true", "yes", "on"}
    if value_type == "int":
        return int(raw)
    if value_type == "float":
        return float(raw)
    return raw


def default_value(key):
    payload = DEFAULT_SETTINGS.get(key, {})
    value = payload.get("value")
    env_name = payload.get("env")
    if env_name and os.getenv(env_name) is not None:
        return _coerce_env_value(os.getenv(env_name), payload.get("value_type", "json"))
    return value


class SettingsService:
    @staticmethod
    def ensure_defaults():
        for key, payload in DEFAULT_SETTINGS.items():
            value = default_value(key)
            if key == "public_base_url" and has_app_context():
                value = current_app.config.get("HUMAN_BRAIN_URL", value)
            if key == "embedding_model" and has_app_context():
                value = current_app.config.get("EMBEDDING_MODEL", value)
            if not AppSetting.query.filter_by(key=key).first():
                db.session.add(
                    AppSetting(
                        key=key,
                        value=value,
                        value_type=payload.get("value_type", "json"),
                        description=payload["description"],
                    )
                )
        db.session.commit()

    @staticmethod
    def get(key, default=None):
        setting = AppSetting.query.filter_by(key=key).first()
        if setting is None:
            if key == "public_base_url" and has_app_context():
                return current_app.config.get("HUMAN_BRAIN_URL", default)
            if key == "embedding_model" and has_app_context():
                return current_app.config.get("EMBEDDING_MODEL", default)
            return default_value(key) if key in DEFAULT_SETTINGS else default
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
