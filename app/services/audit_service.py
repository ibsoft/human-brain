from flask import has_request_context, request

from app.extensions import db
from app.models import AuditLog


class AuditService:
    @staticmethod
    def log(action, actor_type="system", actor_id=None, workspace_id=None, target_type=None, target_id=None, metadata=None):
        safe_metadata = metadata or {}
        for secret_key in ("password", "token", "api_key", "secret"):
            safe_metadata.pop(secret_key, None)
        ip_address = request.remote_addr if has_request_context() else None
        user_agent = request.headers.get("User-Agent")[:255] if has_request_context() and request.headers.get("User-Agent") else None
        db.session.add(
            AuditLog(
                actor_type=actor_type,
                actor_id=str(actor_id) if actor_id is not None else None,
                workspace_id=workspace_id,
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                ip_address=ip_address,
                user_agent=user_agent,
                meta=safe_metadata,
            )
        )
