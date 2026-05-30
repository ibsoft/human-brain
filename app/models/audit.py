from datetime import datetime

from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    actor_type = db.Column(db.String(32), nullable=False)
    actor_id = db.Column(db.String(64))
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), index=True)
    action = db.Column(db.String(120), nullable=False, index=True)
    target_type = db.Column(db.String(80))
    target_id = db.Column(db.String(80))
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    meta = db.Column("metadata", db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
