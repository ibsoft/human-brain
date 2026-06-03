from datetime import datetime

from app.extensions import db


class HealthCheckRun(db.Model):
    __tablename__ = "health_check_runs"

    id = db.Column(db.Integer, primary_key=True)
    trigger = db.Column(db.String(32), nullable=False, default="manual", index=True)
    status = db.Column(db.String(32), nullable=False, default="queued", index=True)
    severity = db.Column(db.String(32), nullable=False, default="info", index=True)
    auto_repair = db.Column(db.Boolean, nullable=False, default=False)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    completed_at = db.Column(db.DateTime)
    duration_ms = db.Column(db.Float)
    summary = db.Column(db.String(500))
    checks = db.Column(db.JSON, nullable=False, default=list)
    repairs = db.Column(db.JSON, nullable=False, default=list)
    metrics = db.Column(db.JSON, nullable=False, default=dict)
    error = db.Column(db.Text)
