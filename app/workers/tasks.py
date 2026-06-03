from datetime import datetime, timedelta

from app.extensions import celery, db
from app.models import ConsolidationJob, Memory, SessionMessage, Workspace
from app.services.embedding_service import EmbeddingService
from app.services.faiss_service import FaissService
from app.services.memory_service import MemoryService
from app.services.session_service import extract_consolidated_items
from app.services.settings_service import SettingsService


@celery.task(name="consolidate_session")
def consolidate_session_task(job_id):
    job = db.session.get(ConsolidationJob, job_id)
    job.status = "running"
    db.session.commit()
    try:
        messages = SessionMessage.query.filter_by(session_id=job.session_id).order_by(SessionMessage.created_at.asc()).all()
        extracted = extract_consolidated_items(messages)
        created = []
        auto_store = SettingsService.get("auto_store_consolidated_memory", False)
        for memory_type, items in extracted.items():
            for item in items:
                memory, duplicate = MemoryService().add_memory(
                    {
                        "agent_id": job.agent_id,
                        "workspace_id": job.workspace_id,
                        "source_session_id": job.session_id,
                        "title": f"Consolidated {memory_type.replace('_', ' ')}",
                        "content": item,
                        "summary": item[:300],
                        "memory_type": memory_type,
                        "tags": ["consolidated", memory_type],
                        "importance_score": 0.6,
                        "trust_score": 0.4 if "?" in item else 0.65,
                        "sensitivity_level": "high" if any(x in item.lower() for x in ("secret", "token", "password")) else "normal",
                        "source": "session_consolidation",
                        "confirmed": auto_store,
                        "storage_reason": "Extracted from a session consolidation job.",
                    },
                    actor_type="worker",
                    actor_id=job.agent_id,
                )
                created.append({"id": memory.id, "duplicate": duplicate, "type": memory_type})
        job.status = "completed"
        job.result = {"created": created, "extracted": extracted}
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
    job.updated_at = datetime.utcnow()
    db.session.commit()
    return job.result


@celery.task(name="rebuild_faiss_index")
def rebuild_faiss_index_task(workspace_id):
    from flask import current_app

    return FaissService(current_app.config["FAISS_INDEX_DIR"]).rebuild(
        workspace_id, EmbeddingService(current_app.config["EMBEDDING_MODEL"])
    )


@celery.task(name="detect_duplicates")
def detect_duplicates_task():
    hashes = {}
    duplicates = []
    for memory in Memory.query.filter(Memory.deleted_at.is_(None)).all():
        key = (memory.workspace_id, memory.content_hash)
        if key in hashes:
            duplicates.append({"primary": hashes[key], "duplicate": memory.id})
        else:
            hashes[key] = memory.id
    return duplicates


@celery.task(name="consolidate_duplicate_memories")
def consolidate_duplicate_memories_task():
    settings = SettingsService.get("duplicate_consolidation", {})
    if not settings.get("enabled"):
        return {"status": "disabled"}
    now = datetime.utcnow()
    configured_hour = int(str(settings.get("time", "03:00")).split(":", 1)[0] or 3)
    if now.hour != configured_hour:
        return {"status": "skipped", "reason": "outside_configured_hour", "configured_time": settings.get("time")}
    if settings.get("frequency") == "weekly" and now.weekday() != 0:
        return {"status": "skipped", "reason": "outside_weekly_window"}
    from app.services.duplicate_service import DuplicateConsolidationService

    result = DuplicateConsolidationService().run_for_all_workspaces(
        archive_duplicates=bool(settings.get("archive_duplicates", True)),
        min_group_size=int(settings.get("min_group_size", 2)),
    )
    return {"status": "completed", "workspaces": result}


@celery.task(name="scheduled_health_check")
def scheduled_health_check_task():
    from app.services.health_service import HealthCheckService

    service = HealthCheckService()
    should_run, reason = service.should_run_scheduled()
    if not should_run:
        return {"status": "skipped", "reason": reason}
    run = service.run(trigger="scheduled")
    return {"status": run.status, "severity": run.severity, "run_id": run.id, "summary": run.summary}


@celery.task(name="run_health_check")
def run_health_check_task(auto_repair=True):
    from app.services.health_service import HealthCheckService

    run = HealthCheckService().run(trigger="manual", auto_repair=auto_repair)
    return {"status": run.status, "severity": run.severity, "run_id": run.id, "summary": run.summary}


@celery.task(name="calculate_trust_scores")
def calculate_trust_scores_task():
    for memory in Memory.query.filter(Memory.deleted_at.is_(None)).all():
        if memory.access_count > 10:
            memory.trust_score = min(1.0, memory.trust_score + 0.02)
    db.session.commit()


@celery.task(name="expire_old_memories")
def expire_old_memories_task():
    now = datetime.utcnow()
    expired = Memory.query.filter(Memory.expires_at.isnot(None), Memory.expires_at < now, Memory.deleted_at.is_(None)).all()
    for memory in expired:
        memory.archived = True
    db.session.commit()
    return len(expired)


@celery.task(name="backup_database")
def backup_database_task():
    return {"status": "queued", "note": "Use python manage.py backup for a filesystem backup."}


@celery.task(name="cleanup_old_snapshots")
def cleanup_old_snapshots_task():
    return {"status": "ok"}


@celery.task(name="daily_memory_report")
def daily_memory_report_task():
    since = datetime.utcnow() - timedelta(days=1)
    return {"new_memories": Memory.query.filter(Memory.created_at >= since).count()}
