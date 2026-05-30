import logging
import sys
from datetime import datetime
from logging.config import dictConfig

from flask import Flask

from app.config import config_by_name
from app.extensions import bcrypt, celery, csrf, db, limiter, login_manager, migrate


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
            value = datetime.fromtimestamp(value)
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        return value.strftime("%Y-%m-%d %H:%M")


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
    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        task_always_eager=app.config.get("CELERY_TASK_ALWAYS_EAGER", False),
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
            from app.services.embedding_service import EmbeddingService
            from app.services.faiss_service import FaissService
            from app.services.settings_service import SettingsService

            model_name = SettingsService.get("embedding_model", app.config["EMBEDDING_MODEL"])
            result = FaissService(app.config["FAISS_INDEX_DIR"]).warmup(EmbeddingService(model_name))
            app.logger.info("Vector startup warmup complete: %s", result)
    except Exception:
        app.logger.exception("Vector startup warmup failed")
