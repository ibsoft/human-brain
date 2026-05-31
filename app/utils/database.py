from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from app.extensions import db


REQUIRED_RUNTIME_TABLES = ("app_settings", "workspaces")


def missing_tables(required_tables=REQUIRED_RUNTIME_TABLES):
    inspector = inspect(db.engine)
    existing = set(inspector.get_table_names())
    return [table for table in required_tables if table not in existing]


def has_required_tables(required_tables=REQUIRED_RUNTIME_TABLES):
    return not missing_tables(required_tables)


def safe_database_uri(uri):
    try:
        return make_url(uri).render_as_string(hide_password=True)
    except Exception:
        return uri
