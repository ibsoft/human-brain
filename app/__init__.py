import json
import logging
import sys
from datetime import datetime, timezone
from logging.config import dictConfig
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

from app.config import config_by_name
from app.extensions import bcrypt, celery, csrf, db, limiter, login_manager, migrate
from app.utils.database import missing_tables


def create_app(config_name="development"):
    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name["development"]))

    configure_logging(app)
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.login_view = "auth.login"

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    register_blueprints(app)
    register_security_headers(app)
    register_template_filters(app)
    register_template_context(app)
    register_agent_api_logging(app)
    configure_celery(app)
    register_cli(app)
    warmup_vectors(app)
    return app


def register_template_filters(app):
    @app.template_filter("dt")
    def dt(value):
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            value = datetime.fromtimestamp(value, tz=timezone.utc)
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        try:
            from app.services.settings_service import SettingsService

            target_timezone = ZoneInfo(SettingsService.get("display_timezone", "UTC"))
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            target_timezone = timezone.utc
        return value.astimezone(target_timezone).strftime("%Y-%m-%d %H:%M")


def register_template_context(app):
    @app.context_processor
    def inject_version():
        from app.services.git_version_service import git_version

        return {"git_version": git_version()}


def register_agent_api_logging(app):
    @app.before_request
    def capture_agent_request():
        from flask import g, request

        if not request.path.startswith("/api/v1/"):
            return
        if request.path.startswith("/api/v1/vision/stream"):
            return
        if request.mimetype and request.mimetype.startswith("multipart/"):
            body = {
                "form": {key: request.form.get(key) for key in request.form.keys()},
                "files": [file.filename for files in request.files.lists() for file in files[1]],
            }
        else:
            body = _api_log_payload(request.get_data(cache=True, as_text=True)[:4000])
        g.agent_log_request = {
            "method": request.method,
            "path": request.path,
            "query": request.query_string.decode("utf-8", errors="replace"),
            "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr),
            "body": body,
            "content_type": request.content_type,
        }

    @app.after_request
    def write_agent_response(response):
        from flask import g, request

        record = getattr(g, "agent_log_request", None)
        if not record:
            return response
        try:
            from app.services.agent_log_service import AgentLogService

            level = "warning" if response.status_code >= 400 else "info"
            response_body = ""
            if response.content_type and ("json" in response.content_type or "text" in response.content_type):
                response_body = response.get_data(as_text=True)[:4000]
            record.update(
                {
                    "status": response.status_code,
                    "agent_id": getattr(getattr(g, "agent", None), "id", None),
                    "response": _api_log_payload(response_body),
                }
            )
            _capture_agent_session_exchange(record)
            AgentLogService().write(record, level=level)
        except Exception:
            app.logger.exception("Could not write agent API JSONL log")
        return response


def _redact_api_log_text(value):
    if not value:
        return value
    return str(value).replace("X-API-Key", "X-API-Key-REDACTED")


def _api_log_payload(value):
    if not value:
        return value
    text = _redact_api_log_text(value)
    try:
        return _redact_api_log_value(json.loads(text))
    except ValueError:
        return text


def _redact_api_log_value(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if str(key).lower() in {"api_key", "x-api-key", "password", "token", "secret"}:
                redacted[key] = "REDACTED"
            else:
                redacted[key] = _redact_api_log_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_api_log_value(item) for item in value]
    if isinstance(value, str):
        return _redact_api_log_text(value)
    return value


def _capture_agent_session_exchange(record):
    from app.extensions import db
    from app.models import Session, SessionMessage
    from app.services.settings_service import SettingsService

    if not SettingsService.get("agent_auto_sessions", True):
        return
    if str(record.get("path") or "").startswith("/api/v1/session/"):
        return
    session_id = _agent_log_session_id(record)
    if not session_id:
        return
    session = db.session.get(Session, session_id)
    if not session or session.agent_id != record.get("agent_id") or session.status == "ended":
        return
    request_content = _session_api_content(record, "request", record.get("body"))
    response_content = _session_api_content(record, "response", record.get("response"))
    db.session.add(
        SessionMessage(
            session_id=session.id,
            role="user",
            content=request_content,
            meta={"source": "agent_api_auto_capture", "path": record.get("path"), "method": record.get("method")},
        )
    )
    db.session.add(
        SessionMessage(
            session_id=session.id,
            role="assistant",
            content=response_content,
            meta={"source": "agent_api_auto_capture", "path": record.get("path"), "status": record.get("status")},
        )
    )
    db.session.commit()


def _agent_log_session_id(record):
    from urllib.parse import parse_qs

    body = record.get("body")
    candidates = []
    if isinstance(body, dict):
        candidates.append(body.get("session_id"))
        form = body.get("form")
        if isinstance(form, dict):
            candidates.append(form.get("session_id"))
    query = parse_qs(record.get("query") or "")
    candidates.extend(query.get("session_id", []))
    for candidate in candidates:
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _session_api_content(record, label, payload):
    body = json.dumps(payload, ensure_ascii=False, default=str, indent=2) if not isinstance(payload, str) else payload
    body = body[:4000]
    return f"API {label}: {record.get('method')} {record.get('path')}\n{body}"


def register_blueprints(app):
    from app.routes.api import api_bp
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.vision import vision_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(vision_bp)
    csrf.exempt(api_bp)
    csrf.exempt(vision_bp)


def register_security_headers(app):
    @app.after_request
    def add_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; script-src 'self' cdn.jsdelivr.net cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdnjs.cloudflare.com; font-src 'self' cdnjs.cloudflare.com",
        )
        return response


def configure_logging(app):
    dictConfig(
        {
            "version": 1,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                }
            },
            "handlers": {
                "wsgi": {"class": "logging.StreamHandler", "formatter": "default"}
            },
            "root": {"level": app.config.get("LOG_LEVEL", "INFO"), "handlers": ["wsgi"]},
        }
    )


def configure_celery(app):
    from celery.schedules import crontab

    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        task_always_eager=app.config.get("CELERY_TASK_ALWAYS_EAGER", False),
        beat_schedule={
            "duplicate-consolidation-settings-check": {
                "task": "consolidate_duplicate_memories",
                "schedule": crontab(minute=0, hour="*"),
            }
        },
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask


def register_cli(app):
    from app.cli import register_commands

    register_commands(app)


def warmup_vectors(app):
    if not app.config.get("VECTOR_STARTUP_WARMUP"):
        return
    if "db" in sys.argv:
        app.logger.debug("Skipping vector startup warmup during database command")
        return
    try:
        with app.app_context():
            missing = missing_tables()
            if missing:
                app.logger.info("Skipping vector startup warmup; database is not migrated yet. Missing tables: %s", ", ".join(missing))
                return
            from app.services.embedding_service import EmbeddingService
            from app.services.faiss_service import FaissService
            from app.services.settings_service import SettingsService

            model_name = SettingsService.get("embedding_model", app.config["EMBEDDING_MODEL"])
            result = FaissService(app.config["FAISS_INDEX_DIR"]).warmup(EmbeddingService(model_name))
            app.logger.info("Vector startup warmup complete: %s", result)
    except SQLAlchemyError as exc:
        app.logger.warning("Skipping vector startup warmup; database is not ready: %s", exc)
    except Exception:
        app.logger.exception("Vector startup warmup failed")
