from datetime import datetime

from app.extensions import db


class VisionEvent(db.Model):
    __tablename__ = "vision_events"

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), index=True)
    label = db.Column(db.String(120), nullable=False)
    confidence = db.Column(db.Float, nullable=False)
    snapshot_path = db.Column(db.String(255))
    meta = db.Column("metadata", db.JSON, nullable=False, default=dict)
    saved_as_memory_id = db.Column(db.Integer, db.ForeignKey("memories.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
