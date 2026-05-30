from datetime import datetime, timedelta
from functools import wraps

from flask import abort, g, request

from app.extensions import db
from app.models import Agent, ApiKey, WorkspaceAgent


def authenticate_api_key():
    raw = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not raw:
        abort(401, description="Missing API key")
    prefix = raw[:12]
    keys = ApiKey.query.filter_by(prefix=prefix, active=True).all()
    for key in keys:
        if key.verify(raw):
            key.last_used_at = datetime.utcnow()
            agent = db.session.get(Agent, key.agent_id)
            if not agent or not agent.active:
                abort(403, description="Agent inactive")
            g.agent = agent
            g.api_key = key
            db.session.commit()
            return agent
    abort(401, description="Invalid API key")


def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        authenticate_api_key()
        return fn(*args, **kwargs)

    return wrapper


def require_workspace_access(agent_id, workspace_id):
    allowed = WorkspaceAgent.query.filter_by(agent_id=agent_id, workspace_id=workspace_id).first()
    if not allowed:
        abort(403, description="Agent is not allowed to access this workspace")
    return allowed


def lockout_until(failed_count):
    if failed_count < 5:
        return None
    return datetime.utcnow() + timedelta(minutes=min(30, failed_count * 2))

