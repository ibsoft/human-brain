from flask import Blueprint, abort, current_app, g, jsonify, request

from app.extensions import db, limiter
from app.models import ConsolidationJob, Memory, MemoryVector, Session
from app.security.auth import require_api_key, require_workspace_access
from app.services.context_service import ContextService, confirm_memory
from app.services.document_service import DocumentIngestionService
from app.services.embedding_service import EmbeddingService
from app.services.faiss_service import FaissService
from app.services.audit_service import AuditService
from app.services.memory_service import MemoryService, serialize_asset, serialize_correlations, serialize_memory
from app.services.memory_quality_service import MemoryQualityService
from app.services.performance_service import PerformanceService
from app.services.settings_service import SettingsService
from app.services.session_service import SessionService
from app.utils.hash import sha256_text

api_bp = Blueprint("api", __name__)


def json_payload():
    payload = request.get_json(silent=True) or {}
    if hasattr(g, "agent"):
        if payload.get("agent_id") and int(payload["agent_id"]) != g.agent.id:
            abort(403, description="API key cannot act as another agent")
        payload["agent_id"] = g.agent.id
    return payload


def bool_arg(name, default=False):
    value = request.args.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def bool_form(name, default=False):
    value = request.form.get(name)
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def form_float(name, default):
    value = request.form.get(name)
    try:
        return float(value) if str(value or "").strip() else default
    except ValueError:
        abort(400, description=f"{name} must be a number")


def form_int(name, default):
    value = request.form.get(name)
    try:
        return int(value) if str(value or "").strip() else default
    except ValueError:
        abort(400, description=f"{name} must be an integer")


def form_tags():
    raw = request.form.get("tags", "")
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


@api_bp.post("/memory/add")
@require_api_key
@limiter.limit("120 per minute")
def memory_add():
    payload = MemoryQualityService().normalize_payload(json_payload())
    require_workspace_access(payload.get("agent_id"), payload.get("workspace_id"))
    quality_service = MemoryQualityService()
    quality = quality_service.evaluate_payload(payload)
    agent_policy = quality_service.write_policy_status(payload)
    if quality["reject_low_quality"] and quality["score"] < quality["reject_below_score"]:
        abort(400, description=f"Memory quality too low: {', '.join(quality['warnings'])}")
    if agent_policy["strict_mode"] and agent_policy["warnings"]:
        abort(400, description=f"Agent policy violation: {', '.join(agent_policy['warnings'])}")
    memory, duplicate = MemoryService().add_memory(payload, actor_id=payload.get("agent_id"))
    AuditService.log(
        "agent.memory_writeback",
        "agent",
        payload.get("agent_id"),
        payload.get("workspace_id"),
        "memory",
        memory.id,
        metadata={"duplicate": duplicate, "quality": quality, "agent_policy": agent_policy, "memory_type": memory.memory_type},
    )
    db.session.commit()
    return jsonify({"memory": serialize_memory(memory), "duplicate": duplicate, "quality": quality, "agent_policy": agent_policy}), 201


@api_bp.post("/memory/upload")
@require_api_key
@limiter.limit("60 per minute")
def memory_upload():
    workspace_id = request.form.get("workspace_id", type=int)
    if not workspace_id:
        abort(400, description="workspace_id is required")
    require_workspace_access(g.agent.id, workspace_id)
    uploads = [item for item in request.files.getlist("uploads") if item and item.filename]
    if not uploads:
        single = request.files.get("file")
        uploads = [single] if single and single.filename else []
    if not uploads:
        abort(400, description="Upload at least one file using the 'uploads' or 'file' multipart field")
    base_payload = {
        "agent_id": g.agent.id,
        "workspace_id": workspace_id,
        "session_id": request.form.get("session_id", type=int),
        "title": request.form.get("title", "").strip(),
        "memory_type": request.form.get("memory_type", "long-term").strip() or "long-term",
        "tags": form_tags(),
        "importance_score": form_float("importance_score", 0.5),
        "trust_score": form_float("trust_score", 0.5),
        "sensitivity_level": request.form.get("sensitivity_level", "normal").strip() or "normal",
        "visibility": request.form.get("visibility", "workspace").strip() or "workspace",
        "confirmed": bool_form("confirmed", False),
        "source": "agent_upload",
        "storage_reason": request.form.get("storage_reason", "Stored from agent-uploaded file.").strip(),
    }
    created = DocumentIngestionService().ingest_uploads(
        uploads,
        base_payload,
        actor_type="agent",
        actor_id=g.agent.id,
        mode=request.form.get("ingest_mode", "full"),
        chunk_size=form_int("chunk_size", 4000),
    )
    return jsonify({"count": len(created), "memories": [serialize_memory(memory) for memory in created]}), 201


@api_bp.post("/memory/<int:memory_id>/asset/replace")
@require_api_key
@limiter.limit("60 per minute")
def memory_asset_replace(memory_id):
    memory = db.session.get(Memory, memory_id)
    if not memory or memory.deleted_at:
        abort(404, description="Memory not found")
    require_workspace_access(g.agent.id, memory.workspace_id)
    upload = request.files.get("file")
    if not upload or not upload.filename:
        uploads = [item for item in request.files.getlist("uploads") if item and item.filename]
        upload = uploads[0] if uploads else None
    if not upload or not upload.filename:
        abort(400, description="Upload one replacement file using the 'file' or 'uploads' multipart field")
    tags = form_tags() if "tags" in request.form else None
    try:
        memory, asset = DocumentIngestionService().replace_memory_asset(
            memory,
            upload,
            actor_type="agent",
            actor_id=g.agent.id,
            title=request.form.get("title", "").strip() or None,
            tags=tags,
            mode=request.form.get("ingest_mode", "full"),
            chunk_size=form_int("chunk_size", 4000),
        )
    except ValueError as exc:
        abort(400, description=str(exc))
    return jsonify({"memory": serialize_memory(memory), "asset": serialize_asset(asset)})


@api_bp.post("/memory/search")
@require_api_key
def memory_search():
    payload = json_payload()
    require_workspace_access(payload.get("agent_id"), payload.get("workspace_id"))
    payload.setdefault("include_timing", True)
    search = MemoryService().search(payload, semantic=True)
    response = search if isinstance(search, dict) else {"results": search}
    _record_agent_search(payload, "agent.memory_search", response)
    response["agent_policy"] = MemoryQualityService().search_policy_status()
    return jsonify(response)


@api_bp.get("/search")
@require_api_key
def memory_search_get():
    workspace_id = request.args.get("workspace_id", type=int)
    require_workspace_access(g.agent.id, workspace_id)
    payload = {
        "agent_id": g.agent.id,
        "workspace_id": workspace_id,
        "query": request.args.get("query", ""),
        "top_k": request.args.get("top_k", 10, type=int),
        "mode": request.args.get("mode", "agent"),
        "compact": bool_arg("compact", True),
        "include_timing": True,
        "include_vector_details": bool_arg("include_vector_details", False),
        "include_correlations": bool_arg("include_correlations", False),
        "include_assets": bool_arg("include_assets", False),
        "record_access": bool_arg("record_access", True),
    }
    search = MemoryService().search(payload, semantic=True)
    response = search if isinstance(search, dict) else {"results": search}
    _record_agent_search(payload, "agent.memory_search", response)
    response["agent_policy"] = MemoryQualityService().search_policy_status()
    return jsonify(response)


@api_bp.post("/memory/hybrid-search")
@require_api_key
def memory_hybrid_search():
    payload = json_payload()
    require_workspace_access(payload.get("agent_id"), payload.get("workspace_id"))
    payload.setdefault("include_timing", True)
    search = MemoryService().search(payload, semantic=True)
    response = search if isinstance(search, dict) else {"results": search}
    _record_agent_search(payload, "agent.memory_search", response)
    response["agent_policy"] = MemoryQualityService().search_policy_status()
    return jsonify(response)


@api_bp.post("/memory/update")
@require_api_key
def memory_update():
    payload = json_payload()
    memory = db.session.get(Memory, payload.get("id"))
    if not memory:
        abort(404, description="Memory not found")
    require_workspace_access(payload.get("agent_id"), memory.workspace_id)
    for field in ("title", "content", "summary", "tags", "importance_score", "trust_score", "sensitivity_level", "visibility"):
        if field in payload:
            setattr(memory, field, payload[field])
    db.session.commit()
    if "content" in payload:
        memory.content_hash = sha256_text(memory.content.strip())
        embeddings = EmbeddingService(current_app.config["EMBEDDING_MODEL"])
        FaissService(current_app.config["FAISS_INDEX_DIR"]).upsert_memory(memory, embeddings)
    return jsonify({"memory": serialize_memory(memory)})


@api_bp.post("/memory/archive")
@require_api_key
def memory_archive():
    payload = json_payload()
    memory = db.session.get(Memory, payload.get("id"))
    if not memory:
        abort(404, description="Memory not found")
    require_workspace_access(payload.get("agent_id"), memory.workspace_id)
    MemoryService().archive(memory, payload.get("agent_id"))
    return jsonify({"ok": True})


@api_bp.post("/memory/delete")
@require_api_key
def memory_delete():
    payload = json_payload()
    memory = db.session.get(Memory, payload.get("id"))
    if not memory:
        abort(404, description="Memory not found")
    require_workspace_access(payload.get("agent_id"), memory.workspace_id)
    MemoryService().delete(memory, payload.get("agent_id"))
    return jsonify({"ok": True})


@api_bp.post("/memory/forget")
@require_api_key
def memory_forget():
    payload = json_payload()
    memory = db.session.get(Memory, payload.get("id"))
    if not memory:
        abort(404, description="Memory not found")
    require_workspace_access(payload.get("agent_id"), memory.workspace_id)
    MemoryService().delete(memory, payload.get("agent_id"), forget=True)
    return jsonify({"ok": True, "forgotten": True})


@api_bp.post("/memory/merge")
@require_api_key
def memory_merge():
    payload = json_payload()
    primary = db.session.get(Memory, payload.get("primary_id"))
    secondary = db.session.get(Memory, payload.get("secondary_id"))
    if not primary or not secondary:
        abort(404, description="Memory not found")
    require_workspace_access(payload.get("agent_id"), primary.workspace_id)
    primary.content = f"{primary.content}\n\nMerged note:\n{secondary.content}"
    primary.trust_score = min(1.0, max(primary.trust_score, secondary.trust_score) + 0.05)
    secondary.archived = True
    db.session.commit()
    return jsonify({"memory": serialize_memory(primary)})


@api_bp.post("/memory/confirm")
@require_api_key
def memory_confirm():
    payload = json_payload()
    memory = confirm_memory(payload.get("id"))
    if not memory:
        abort(404, description="Memory not found")
    require_workspace_access(payload.get("agent_id"), memory.workspace_id)
    return jsonify({"memory": serialize_memory(memory)})


@api_bp.get("/memory/<int:memory_id>")
@require_api_key
def memory_get(memory_id):
    workspace_id = request.args.get("workspace_id", type=int)
    agent_id = g.agent.id
    require_workspace_access(agent_id, workspace_id)
    memory = Memory.query.filter_by(id=memory_id, workspace_id=workspace_id).first_or_404()
    return jsonify({"memory": serialize_memory(memory)})


@api_bp.get("/memory/<int:memory_id>/correlations")
@require_api_key
def memory_get_correlations(memory_id):
    workspace_id = request.args.get("workspace_id", type=int)
    agent_id = g.agent.id
    require_workspace_access(agent_id, workspace_id)
    memory = Memory.query.filter_by(id=memory_id, workspace_id=workspace_id).first_or_404()
    limit = request.args.get("limit", 10, type=int)
    min_strength = request.args.get("min_strength", 0.35, type=float)
    return jsonify({"memory": serialize_memory(memory), "correlations": serialize_correlations(memory.id, limit=limit, min_strength=min_strength)})


@api_bp.get("/memory/stats")
@require_api_key
def memory_stats():
    workspace_id = request.args.get("workspace_id", type=int)
    agent_id = g.agent.id
    require_workspace_access(agent_id, workspace_id)
    return jsonify(
        {
            "total": Memory.query.filter_by(workspace_id=workspace_id).count(),
            "active": Memory.query.filter_by(workspace_id=workspace_id, archived=False, deleted_at=None).count(),
            "sensitive": Memory.query.filter(Memory.workspace_id == workspace_id, Memory.sensitivity_level.in_(["high", "secret"])).count(),
        }
    )


@api_bp.get("/memory/quality-report")
@require_api_key
def memory_quality_report():
    workspace_id = request.args.get("workspace_id", type=int)
    agent_id = g.agent.id
    require_workspace_access(agent_id, workspace_id)
    return jsonify(MemoryQualityService().quality_report(workspace_id))


@api_bp.get("/memory/stale")
@require_api_key
def memory_stale():
    workspace_id = request.args.get("workspace_id", type=int)
    agent_id = g.agent.id
    require_workspace_access(agent_id, workspace_id)
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 25, type=int), 100)
    pagination = MemoryQualityService().stale_memories(workspace_id, page=page, per_page=per_page)
    return jsonify(
        {
            "items": [serialize_memory(memory, include_assets=False) for memory in pagination.items],
            "page": pagination.page,
            "pages": pagination.pages,
            "per_page": pagination.per_page,
            "total": pagination.total,
        }
    )


@api_bp.get("/vector/health")
@require_api_key
def vector_health():
    return jsonify(FaissService(current_app.config["FAISS_INDEX_DIR"]).health())


@api_bp.post("/vector/warmup")
@require_api_key
def vector_warmup():
    service = FaissService(current_app.config["FAISS_INDEX_DIR"])
    embeddings = EmbeddingService(SettingsService.get("embedding_model", current_app.config["EMBEDDING_MODEL"]))
    return jsonify(service.warmup(embeddings))


@api_bp.get("/performance")
@require_api_key
def performance():
    faiss = FaissService(current_app.config["FAISS_INDEX_DIR"])
    health = faiss.health()
    model_name = SettingsService.get("embedding_model", current_app.config["EMBEDDING_MODEL"])
    return jsonify(
        {
            "embedding_model_loaded": model_name in EmbeddingService._model_cache or model_name == "hash",
            "embedding_model": model_name,
            "index_loaded": FaissService.cache_stats()["index_cache_entries"] > 0,
            "vector_count": MemoryVector.query.count(),
            "memory_count": Memory.query.filter_by(archived=False, deleted_at=None).count(),
            "cache": FaissService.cache_stats(),
            "search_latency": PerformanceService.search_stats(),
            "vector_health": health,
        }
    )


@api_bp.post("/context/build")
@require_api_key
def context_build():
    payload = json_payload()
    require_workspace_access(payload.get("agent_id"), payload.get("workspace_id"))
    response = ContextService().build(payload)
    _record_agent_search(payload, "agent.context_build", response)
    response["agent_policy"] = MemoryQualityService().search_policy_status()
    return jsonify(response)


@api_bp.post("/session/start")
@require_api_key
def session_start():
    payload = json_payload()
    require_workspace_access(payload.get("agent_id"), payload.get("workspace_id"))
    session = SessionService().start(payload)
    return jsonify({"session_id": session.id, "uuid": session.uuid}), 201


@api_bp.post("/session/add-message")
@require_api_key
def session_add_message():
    payload = json_payload()
    session = db.session.get(Session, payload.get("session_id"))
    if not session:
        abort(404, description="Session not found")
    require_workspace_access(payload.get("agent_id"), session.workspace_id)
    msg = SessionService().add_message(payload)
    return jsonify({"message_id": msg.id}), 201


@api_bp.post("/session/end")
@require_api_key
def session_end():
    payload = json_payload()
    existing = db.session.get(Session, payload.get("session_id"))
    if not existing:
        abort(404, description="Session not found")
    require_workspace_access(payload.get("agent_id"), existing.workspace_id)
    session = SessionService().end(payload.get("session_id"))
    return jsonify({"session": SessionService().serialize_session(session)})


@api_bp.post("/session/consolidate")
@require_api_key
def session_consolidate():
    payload = json_payload()
    session = db.session.get(Session, payload.get("session_id"))
    if not session:
        abort(404, description="Session not found")
    require_workspace_access(payload.get("agent_id"), session.workspace_id)
    job = SessionService().queue_consolidation(payload.get("session_id"))
    return jsonify({"job_id": job.id, "status": job.status}), 202


@api_bp.get("/session/<int:session_id>")
@require_api_key
def session_get(session_id):
    session = db.session.get(Session, session_id)
    if not session:
        abort(404, description="Session not found")
    require_workspace_access(g.agent.id, session.workspace_id)
    return jsonify({"session": SessionService().serialize_session(session)})


@api_bp.get("/jobs")
@require_api_key
def jobs_list():
    workspace_id = request.args.get("workspace_id", type=int)
    require_workspace_access(g.agent.id, workspace_id)
    jobs = (
        ConsolidationJob.query.filter_by(workspace_id=workspace_id, agent_id=g.agent.id)
        .order_by(ConsolidationJob.created_at.desc())
        .limit(request.args.get("limit", 50, type=int))
        .all()
    )
    return jsonify({"jobs": [_serialize_job(job) for job in jobs]})


@api_bp.get("/jobs/<int:job_id>")
@require_api_key
def job_get(job_id):
    job = db.session.get(ConsolidationJob, job_id)
    if not job:
        abort(404, description="Job not found")
    require_workspace_access(g.agent.id, job.workspace_id)
    if job.agent_id != g.agent.id:
        abort(403, description="API key cannot read another agent's job")
    return jsonify({"job": _serialize_job(job)})


def _serialize_job(job):
    return {
        "id": job.id,
        "session_id": job.session_id,
        "workspace_id": job.workspace_id,
        "agent_id": job.agent_id,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _record_agent_search(payload, action, response):
    results = response.get("results") if isinstance(response, dict) else None
    AuditService.log(
        action,
        "agent",
        payload.get("agent_id"),
        payload.get("workspace_id"),
        "memory",
        None,
        metadata={
            "query": payload.get("query") or payload.get("prompt") or "",
            "top_k": payload.get("top_k"),
            "result_count": len(results or []),
        },
    )
    db.session.commit()
