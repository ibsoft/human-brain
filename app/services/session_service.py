from datetime import datetime

from flask import current_app

from app.extensions import db
from app.models import ConsolidationJob, Session, SessionMessage
from app.services.audit_service import AuditService


class SessionService:
    def start(self, payload):
        session = Session(
            agent_id=payload["agent_id"],
            workspace_id=payload["workspace_id"],
            title=payload.get("title") or "Agent session",
        )
        db.session.add(session)
        db.session.flush()
        AuditService.log("session.started", "agent", payload["agent_id"], payload["workspace_id"], "session", session.id)
        db.session.commit()
        return session

    def add_message(self, payload):
        message = SessionMessage(
            session_id=payload["session_id"],
            role=payload["role"],
            content=payload["content"],
            meta=payload.get("metadata") or {},
        )
        db.session.add(message)
        db.session.commit()
        return message

    def end(self, session_id):
        session = db.session.get(Session, session_id)
        if not session:
            return None
        session.status = "ended"
        session.ended_at = datetime.utcnow()
        db.session.commit()
        return session

    def queue_consolidation(self, session_id):
        session = db.session.get(Session, session_id)
        if not session:
            return None
        job = ConsolidationJob(session_id=session.id, workspace_id=session.workspace_id, agent_id=session.agent_id)
        db.session.add(job)
        db.session.commit()
        from app.workers.tasks import consolidate_session_task

        try:
            if current_app.config.get("CELERY_TASK_ALWAYS_EAGER"):
                consolidate_session_task.delay(job.id)
            else:
                consolidate_session_task.delay(job.id)
        except Exception as exc:
            current_app.logger.warning("Celery broker unavailable for consolidation job %s: %s", job.id, exc)
            if current_app.config.get("RUN_JOBS_INLINE_ON_BROKER_FAILURE", False):
                consolidate_session_task(job.id)
                db.session.refresh(job)
            else:
                job.status = "failed"
                job.error = f"Could not queue Celery task: {exc}"
                db.session.commit()
        return job

    def serialize_session(self, session):
        messages = SessionMessage.query.filter_by(session_id=session.id).order_by(SessionMessage.created_at.asc()).all()
        return {
            "id": session.id,
            "uuid": session.uuid,
            "agent_id": session.agent_id,
            "workspace_id": session.workspace_id,
            "title": session.title,
            "status": session.status,
            "started_at": session.started_at.isoformat(),
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "messages": [
                {"id": msg.id, "role": msg.role, "content": msg.content, "created_at": msg.created_at.isoformat()}
                for msg in messages
            ],
        }


def extract_consolidated_items(messages):
    buckets = {
        "facts": [],
        "decisions": [],
        "tasks": [],
        "preferences": [],
        "technical_notes": [],
        "project_context": [],
        "security_findings": [],
        "open_questions": [],
        "important_urls": [],
        "configuration_details": [],
    }
    for msg in messages:
        text = msg.content.strip()
        lower = text.lower()
        if not text:
            continue
        if "todo" in lower or "task" in lower:
            buckets["tasks"].append(text)
        elif "decided" in lower or "decision" in lower:
            buckets["decisions"].append(text)
        elif "prefer" in lower:
            buckets["preferences"].append(text)
        elif "security" in lower or "secret" in lower or "token" in lower:
            buckets["security_findings"].append(text)
        elif "http://" in lower or "https://" in lower:
            buckets["important_urls"].append(text)
        elif "config" in lower or "env" in lower:
            buckets["configuration_details"].append(text)
        elif "?" in text:
            buckets["open_questions"].append(text)
        elif "project" in lower:
            buckets["project_context"].append(text)
        elif "error" in lower or "api" in lower or "database" in lower:
            buckets["technical_notes"].append(text)
        else:
            buckets["facts"].append(text)
    return buckets
