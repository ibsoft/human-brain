import json
from datetime import datetime, timedelta

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Agent, ApiKey, AuditLog, ConsolidationJob, Memory, MemoryAsset, MemoryCorrelation, Session, Workspace, WorkspaceAgent
from app.security.rbac import minimum_role, role_required
from app.services.admin_service import AdminService
from app.services.backup_service import BackupService
from app.services.context_service import ContextService
from app.services.document_service import DocumentIngestionService
from app.services.memory_service import MemoryService
from app.services.session_service import SessionService
from app.services.settings_service import SettingsService
from app.services.vision_service import VisionService

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def dashboard():
    workspace = Workspace.query.first()
    workspace_id = workspace.id if workspace else None
    stats = {
        "memories": Memory.query.filter(Memory.deleted_at.is_(None)).count(),
        "agents": Agent.query.filter_by(active=True).count(),
        "workspaces": Workspace.query.count(),
        "sessions": Session.query.count(),
        "jobs": ConsolidationJob.query.count(),
        "sensitive": Memory.query.filter(Memory.sensitivity_level.in_(["high", "secret"]), Memory.deleted_at.is_(None)).count(),
    }
    recent = Memory.query.filter(Memory.deleted_at.is_(None)).order_by(Memory.created_at.desc()).limit(8).all()
    top_tags = {}
    active_memories = Memory.query.filter(Memory.deleted_at.is_(None)).all()
    for memory in active_memories[:500]:
        for tag in memory.tags or []:
            top_tags[tag] = top_tags.get(tag, 0) + 1
    today = datetime.utcnow().date()
    chart_days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    chart_start = datetime.combine(chart_days[0], datetime.min.time())
    writes_by_day = {day.isoformat(): 0 for day in chart_days}
    for memory in Memory.query.filter(Memory.deleted_at.is_(None), Memory.created_at >= chart_start).all():
        key = memory.created_at.date().isoformat()
        if key in writes_by_day:
            writes_by_day[key] += 1
    activity_chart = {
        "labels": [day.strftime("%a") for day in chart_days],
        "values": [writes_by_day[day.isoformat()] for day in chart_days],
    }
    memory_types = {}
    sensitivity = {}
    source_counts = {}
    workspace_names = {workspace.id: workspace.name for workspace in Workspace.query.all()}
    workspace_counts = {}
    trust_buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for memory in active_memories:
        memory_types[memory.memory_type] = memory_types.get(memory.memory_type, 0) + 1
        sensitivity[memory.sensitivity_level] = sensitivity.get(memory.sensitivity_level, 0) + 1
        source_counts[memory.source] = source_counts.get(memory.source, 0) + 1
        workspace_label = workspace_names.get(memory.workspace_id, f"Workspace {memory.workspace_id}")
        workspace_counts[workspace_label] = workspace_counts.get(workspace_label, 0) + 1
        score = max(0, min(memory.trust_score or 0, 1))
        if score < 0.2:
            trust_buckets["0.0-0.2"] += 1
        elif score < 0.4:
            trust_buckets["0.2-0.4"] += 1
        elif score < 0.6:
            trust_buckets["0.4-0.6"] += 1
        elif score < 0.8:
            trust_buckets["0.6-0.8"] += 1
        else:
            trust_buckets["0.8-1.0"] += 1
    dashboard_charts = {
        "activity": activity_chart,
        "types": {"labels": list(memory_types.keys()), "values": list(memory_types.values())},
        "sensitivity": {"labels": list(sensitivity.keys()), "values": list(sensitivity.values())},
        "workspaces": {"labels": list(workspace_counts.keys()), "values": list(workspace_counts.values())},
        "trust": {"labels": list(trust_buckets.keys()), "values": list(trust_buckets.values())},
        "sources": {"labels": list(source_counts.keys()), "values": list(source_counts.values())},
    }
    return render_template("dashboard.html", stats=stats, recent=recent, top_tags=top_tags, workspace_id=workspace_id, dashboard_charts=dashboard_charts)


@main_bp.route("/memories")
@login_required
def memories():
    page = request.args.get("page", 1, type=int)
    pagination = Memory.query.filter(Memory.deleted_at.is_(None)).order_by(Memory.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template("memories.html", memories=pagination.items, pagination=pagination, agents=Agent.query.all(), workspaces=Workspace.query.all())


@main_bp.get("/memory-assets/<asset_token>")
def memory_asset(asset_token):
    asset = MemoryAsset.query.filter_by(public_token=asset_token).first()
    if not asset:
        abort(404)
    memory = db.session.get(Memory, asset.memory_id)
    if not memory or memory.deleted_at:
        abort(404)
    return send_file(asset.stored_path, as_attachment=False, download_name=asset.original_filename)


@main_bp.post("/memories")
@login_required
@minimum_role("operator")
def web_add_memory():
    if not Agent.query.first():
        flash("Create an agent before storing memories.", "danger")
        return redirect(url_for("main.agents"))
    if not Workspace.query.first():
        flash("Create a workspace before storing memories.", "danger")
        return redirect(url_for("main.workspaces"))
    agent = db.session.get(Agent, request.form.get("agent_id", type=int))
    workspace = db.session.get(Workspace, request.form.get("workspace_id", type=int))
    if not agent or not agent.active:
        flash("Choose an active agent before storing a memory.", "danger")
        return redirect(url_for("main.memories"))
    if not workspace:
        flash("Choose a valid workspace before storing a memory.", "danger")
        return redirect(url_for("main.memories"))
    input_mode = request.form.get("memory_input_mode", "single")
    tags = [tag.strip() for tag in request.form.get("tags", "").split(",") if tag.strip()]
    payload = {
        "agent_id": agent.id,
        "workspace_id": workspace.id,
        "title": request.form.get("title"),
        "content": request.form.get("content", "").strip(),
        "memory_type": request.form.get("memory_type", "long-term"),
        "tags": tags,
        "importance_score": float(request.form.get("importance_score", 0.5)),
        "trust_score": float(request.form.get("trust_score", 0.5)),
        "sensitivity_level": request.form.get("sensitivity_level", "normal"),
        "confirmed": request.form.get("confirmed") == "on",
        "source": "web",
    }
    uploads = [item for item in request.files.getlist("uploads") if item and item.filename]
    if input_mode in ["file", "image"] and not uploads:
        flash("Choose a file or image to upload.", "danger")
        return redirect(url_for("main.memories"))
    if input_mode in ["file", "image"] and uploads:
        created = DocumentIngestionService().ingest_uploads(
            uploads,
            payload,
            actor_id=current_user.id,
            mode=request.form.get("ingest_mode", "all"),
            chunk_size=int(request.form.get("chunk_size", 4000) or 4000),
        )
        flash(f"{len(created)} uploaded memory records stored.", "success")
    else:
        if not payload["content"]:
            flash("Add memory content or upload at least one file.", "danger")
            return redirect(url_for("main.memories"))
        MemoryService().add_memory(payload, actor_type="user", actor_id=current_user.id)
        flash("Memory stored.", "success")
    return redirect(url_for("main.memories"))


@main_bp.route("/search")
@login_required
def search_page():
    return render_template("search.html", agents=Agent.query.all(), workspaces=Workspace.query.all())


@main_bp.route("/sessions")
@login_required
def sessions():
    page = request.args.get("page", 1, type=int)
    pagination = Session.query.order_by(Session.started_at.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template(
        "sessions.html",
        sessions=pagination.items,
        pagination=pagination,
        agents=Agent.query.all(),
        workspaces=Workspace.query.all(),
    )


@main_bp.post("/sessions")
@login_required
@minimum_role("operator")
def web_start_session():
    agent = db.session.get(Agent, request.form.get("agent_id", type=int))
    workspace = db.session.get(Workspace, request.form.get("workspace_id", type=int))
    if not agent or not agent.active:
        flash("Create or choose an active agent before starting a session.", "danger")
        return redirect(url_for("main.sessions"))
    if not workspace:
        flash("Create or choose a workspace before starting a session.", "danger")
        return redirect(url_for("main.sessions"))
    session = SessionService().start(
        {
            "agent_id": agent.id,
            "workspace_id": workspace.id,
            "title": request.form.get("title") or "Manual session",
        }
    )
    flash("Session started.", "success")
    return redirect(url_for("main.session_replay", session_id=session.id))


@main_bp.get("/sessions/<int:session_id>")
@login_required
def session_replay(session_id):
    session = db.session.get(Session, session_id)
    if not session:
        abort(404)
    return render_template("session_replay.html", session=SessionService().serialize_session(session))


@main_bp.post("/sessions/<int:session_id>/message")
@login_required
@minimum_role("operator")
def web_add_session_message(session_id):
    SessionService().add_message(
        {
            "session_id": session_id,
            "role": request.form.get("role", "user"),
            "content": request.form["content"],
        }
    )
    return redirect(url_for("main.session_replay", session_id=session_id))


@main_bp.post("/sessions/<int:session_id>/consolidate")
@login_required
@minimum_role("operator")
def web_consolidate_session(session_id):
    job = SessionService().queue_consolidation(session_id)
    if not job:
        abort(404)
    flash(f"Consolidation job {job.id}: {job.status}.", "success" if job.status in ["queued", "completed"] else "danger")
    return redirect(url_for("main.sessions"))


@main_bp.route("/agents")
@login_required
def agents():
    return render_template("agents.html", agents=Agent.query.order_by(Agent.created_at.desc()).all(), workspaces=Workspace.query.all())


@main_bp.post("/agents")
@login_required
@minimum_role("operator")
def create_agent():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Enter an agent name.", "danger")
        return redirect(url_for("main.agents"))
    workspace_id = request.form.get("workspace_id", type=int)
    if workspace_id and not db.session.get(Workspace, workspace_id):
        flash("Choose a valid workspace for the agent.", "danger")
        return redirect(url_for("main.agents"))
    AdminService.create_agent(
        name,
        request.form.get("description", ""),
        [workspace_id] if workspace_id else [],
    )
    flash("Agent created.", "success")
    return redirect(url_for("main.agents"))


@main_bp.post("/agents/<int:agent_id>/edit")
@login_required
@minimum_role("operator")
def edit_agent(agent_id):
    agent = db.session.get(Agent, agent_id)
    if not agent:
        abort(404)
    agent.name = request.form.get("name", agent.name).strip()
    agent.description = request.form.get("description", agent.description).strip()
    agent.active = request.form.get("active") == "on"
    permissions = {
        "memory": request.form.get("memory_permission", "rw"),
        "context": request.form.get("context_permission", "read"),
        "scope": request.form.get("memory_scope", "workspace"),
    }
    agent.permissions = permissions
    workspace_id = request.form.get("workspace_id")
    if workspace_id:
        WorkspaceAgent.query.filter_by(agent_id=agent.id).delete()
        db.session.add(WorkspaceAgent(workspace_id=int(workspace_id), agent_id=agent.id, permissions=permissions))
    db.session.commit()
    flash("Agent updated.", "success")
    return redirect(url_for("main.agents"))


@main_bp.route("/agents/<int:agent_id>/passport")
@login_required
def agent_passport(agent_id):
    agent = db.session.get(Agent, agent_id)
    memories = Memory.query.filter_by(agent_id=agent_id).filter(Memory.deleted_at.is_(None)).order_by(Memory.created_at.desc()).limit(20).all()
    tags = {}
    trust = 0
    for memory in memories:
        trust += memory.trust_score
        for tag in memory.tags or []:
            tags[tag] = tags.get(tag, 0) + 1
    avg_trust = round(trust / len(memories), 2) if memories else 0
    return render_template("agent_passport.html", agent=agent, memories=memories, tags=tags, avg_trust=avg_trust)


@main_bp.route("/workspaces")
@login_required
def workspaces():
    workspace_cards = []
    for workspace in Workspace.query.all():
        workspace_cards.append(
            {
                "workspace": workspace,
                "memories": Memory.query.filter_by(workspace_id=workspace.id).filter(Memory.deleted_at.is_(None)).count(),
                "agents": Agent.query.join(WorkspaceAgent, Agent.id == WorkspaceAgent.agent_id).filter(WorkspaceAgent.workspace_id == workspace.id).count(),
                "sessions": Session.query.filter_by(workspace_id=workspace.id).count(),
                "sensitive": Memory.query.filter(
                    Memory.workspace_id == workspace.id,
                    Memory.sensitivity_level.in_(["high", "secret"]),
                    Memory.deleted_at.is_(None),
                ).count(),
            }
        )
    return render_template("workspaces.html", workspace_cards=workspace_cards)


@main_bp.post("/memories/<int:memory_id>/edit")
@login_required
@minimum_role("operator")
def web_edit_memory(memory_id):
    memory = db.session.get(Memory, memory_id)
    memory.title = request.form["title"]
    memory.content = request.form["content"]
    memory.summary = request.form.get("summary")
    memory.memory_type = request.form.get("memory_type", memory.memory_type)
    memory.tags = [tag.strip() for tag in request.form.get("tags", "").split(",") if tag.strip()]
    memory.importance_score = float(request.form.get("importance_score", memory.importance_score))
    memory.trust_score = float(request.form.get("trust_score", memory.trust_score))
    memory.sensitivity_level = request.form.get("sensitivity_level", memory.sensitivity_level)
    memory.visibility = request.form.get("visibility", memory.visibility)
    memory.confirmed = request.form.get("confirmed") == "on"
    memory.pending_approval = not memory.confirmed
    db.session.commit()
    flash("Memory updated.", "success")
    return redirect(request.referrer or url_for("main.memories"))


@main_bp.get("/memories/<int:memory_id>/correlations")
@login_required
def memory_correlations(memory_id):
    memory = db.session.get(Memory, memory_id)
    if not memory or memory.deleted_at:
        abort(404)
    min_strength = request.args.get("min_strength", 0.35, type=float)
    correlations = (
        MemoryCorrelation.query.filter(
            (MemoryCorrelation.source_memory_id == memory_id) | (MemoryCorrelation.target_memory_id == memory_id)
        )
        .filter(MemoryCorrelation.strength >= min_strength)
        .order_by(MemoryCorrelation.strength.desc())
        .all()
    )
    items = []
    for correlation in correlations:
        related_id = correlation.target_memory_id if correlation.source_memory_id == memory_id else correlation.source_memory_id
        related = db.session.get(Memory, related_id)
        if not related or related.deleted_at:
            continue
        items.append(
            {
                "id": correlation.id,
                "related_memory_id": related.id,
                "related_title": related.title,
                "related_type": related.memory_type,
                "related_tags": related.tags or [],
                "related_sensitivity": related.sensitivity_level,
                "strength": round(correlation.strength, 3),
                "correlation_type": correlation.correlation_type,
                "explanation": correlation.explanation,
                "created_at": correlation.created_at.isoformat() if correlation.created_at else None,
            }
        )
    return jsonify({"memory_id": memory.id, "count": len(items), "correlations": items})


@main_bp.post("/workspaces")
@login_required
@minimum_role("operator")
def create_workspace():
    AdminService.create_workspace(
        request.form.get("name", ""),
        request.form.get("description", ""),
        request.form.get("local_first_privacy") == "on",
    )
    flash("Workspace created.", "success")
    return redirect(url_for("main.workspaces"))


@main_bp.route("/context-builder")
@login_required
def context_builder():
    return render_template("context_builder.html", agents=Agent.query.all(), workspaces=Workspace.query.all())


@main_bp.route("/timeline")
@login_required
def timeline():
    page = request.args.get("page", 1, type=int)
    pagination = Memory.query.order_by(Memory.created_at.desc()).paginate(page=page, per_page=30, error_out=False)
    return render_template("timeline.html", memories=pagination.items, pagination=pagination)


@main_bp.route("/graph")
@login_required
def graph():
    focus_memory_id = request.args.get("memory_id", type=int)
    focus_memory = db.session.get(Memory, focus_memory_id) if focus_memory_id else None
    correlation_query = MemoryCorrelation.query
    if focus_memory and not focus_memory.deleted_at:
        correlations = (
            correlation_query.filter(
                (MemoryCorrelation.source_memory_id == focus_memory.id)
                | (MemoryCorrelation.target_memory_id == focus_memory.id)
            )
            .order_by(MemoryCorrelation.strength.desc())
            .all()
        )
        memory_ids = {focus_memory.id}
        for correlation in correlations:
            memory_ids.add(correlation.source_memory_id)
            memory_ids.add(correlation.target_memory_id)
        memories = (
            Memory.query.filter(Memory.id.in_(memory_ids), Memory.deleted_at.is_(None))
            .order_by(Memory.created_at.desc())
            .all()
        )
    else:
        focus_memory = None
        memories = Memory.query.filter(Memory.deleted_at.is_(None)).order_by(Memory.created_at.desc()).limit(120).all()
        correlations = correlation_query.order_by(MemoryCorrelation.strength.desc()).limit(250).all()
    agents = {agent.id: agent for agent in Agent.query.all()}
    workspaces = {workspace.id: workspace for workspace in Workspace.query.all()}
    nodes = {}
    edges = []

    def node(node_id, label, kind, meta=None):
        nodes[node_id] = {"id": node_id, "label": label, "kind": kind, "meta": meta or {}}

    for memory in memories:
        mem_id = f"memory:{memory.id}"
        node(
            mem_id,
            memory.title[:42],
            "memory",
            {
                "type": memory.memory_type,
                "trust": memory.trust_score,
                "sensitivity": memory.sensitivity_level,
                "created": memory.created_at.isoformat(),
            },
        )
        agent = agents.get(memory.agent_id)
        if agent:
            agent_id = f"agent:{agent.id}"
            node(agent_id, agent.name, "agent")
            edges.append({"source": agent_id, "target": mem_id, "label": "knows"})
        workspace = workspaces.get(memory.workspace_id)
        if workspace:
            workspace_id = f"workspace:{workspace.id}"
            node(workspace_id, workspace.name, "workspace")
            edges.append({"source": workspace_id, "target": mem_id, "label": "contains"})
        type_id = f"type:{memory.memory_type}"
        node(type_id, memory.memory_type, "type")
        edges.append({"source": type_id, "target": mem_id, "label": "classifies"})
        if memory.session_id:
            session_id = f"session:{memory.session_id}"
            node(session_id, f"Session {memory.session_id}", "session")
            edges.append({"source": session_id, "target": mem_id, "label": "created"})
        for tag in memory.tags or []:
            tag_id = f"tag:{tag}"
            node(tag_id, tag, "tag")
            edges.append({"source": tag_id, "target": mem_id, "label": "tags"})
    for correlation in correlations:
        source = f"memory:{correlation.source_memory_id}"
        target = f"memory:{correlation.target_memory_id}"
        if source in nodes and target in nodes:
            edges.append({"source": source, "target": target, "label": f"correlates {correlation.strength:.2f}"})
    graph_data = {"nodes": list(nodes.values()), "edges": edges}
    return render_template("graph.html", graph_data=graph_data, memory_count=len(memories), focus_memory=focus_memory)


@main_bp.route("/forget-center")
@login_required
def forget_center():
    page = request.args.get("page", 1, type=int)
    pagination = Memory.query.filter(Memory.deleted_at.is_(None)).order_by(Memory.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    return render_template("forget_center.html", memories=pagination.items, pagination=pagination)


@main_bp.route("/sensitive-review")
@login_required
def sensitive_review():
    page = request.args.get("page", 1, type=int)
    pagination = Memory.query.filter(Memory.sensitivity_level.in_(["high", "secret"]), Memory.deleted_at.is_(None)).order_by(Memory.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    memories = pagination.items
    stats = {
        "total": len(memories),
        "pending": sum(1 for memory in memories if memory.pending_approval),
        "secret": sum(1 for memory in memories if memory.sensitivity_level == "secret"),
        "high": sum(1 for memory in memories if memory.sensitivity_level == "high"),
    }
    return render_template("sensitive_review.html", memories=memories, stats=stats, pagination=pagination)


@main_bp.route("/audit-logs")
@login_required
@role_required("admin", "operator", "auditor")
def audit_logs():
    action = request.args.get("action", "").strip()
    actor_type = request.args.get("actor_type", "").strip()
    query = AuditLog.query
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if actor_type:
        query = query.filter(AuditLog.actor_type == actor_type)
    logs = query.order_by(AuditLog.created_at.desc()).limit(250).all()
    total = AuditLog.query.count()
    action_counts = {}
    actor_counts = {}
    for log in AuditLog.query.order_by(AuditLog.created_at.desc()).limit(1000).all():
        action_counts[log.action] = action_counts.get(log.action, 0) + 1
        actor_counts[log.actor_type] = actor_counts.get(log.actor_type, 0) + 1
    return render_template(
        "audit_logs.html",
        logs=logs,
        total=total,
        action_counts=sorted(action_counts.items(), key=lambda item: item[1], reverse=True)[:8],
        actor_counts=actor_counts,
        filters={"action": action, "actor_type": actor_type},
    )


@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
@minimum_role("operator")
def settings():
    SettingsService.ensure_defaults()
    if request.method == "POST":
        values = {
            "local_first_privacy_mode": request.form.get("local_first_privacy_mode") == "on",
            "auto_store_consolidated_memory": request.form.get("auto_store_consolidated_memory") == "on",
            "camera_enabled": request.form.get("camera_enabled") == "on",
            "snapshot_storage_enabled": request.form.get("snapshot_storage_enabled") == "on",
            "vision_auto_save": request.form.get("vision_auto_save") == "on",
            "retention_days": int(request.form.get("retention_days", 365)),
            "embedding_model": request.form.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2").strip(),
            "embedding_models": [x.strip() for x in request.form.get("embedding_models", "").splitlines() if x.strip()],
            "ollama_base_url": request.form.get("ollama_base_url", "http://localhost:11434").strip(),
            "backup_schedule": {
                "enabled": request.form.get("backup_schedule_enabled") == "on",
                "frequency": request.form.get("backup_frequency", "daily"),
                "time": request.form.get("backup_time", "02:00"),
                "keep_last": int(request.form.get("backup_keep_last", 7)),
            },
            "reranker_enabled": request.form.get("reranker_enabled") == "on",
            "reranker_provider": request.form.get("reranker_provider", "none").strip(),
            "reranker_default_mode": request.form.get("reranker_default_mode", "conditional").strip(),
            "reranker_cross_encoder_model": request.form.get("reranker_cross_encoder_model", "BAAI/bge-reranker-base").strip(),
            "reranker_ollama_base_url": request.form.get("reranker_ollama_base_url", "http://localhost:11434").strip(),
            "reranker_ollama_model": request.form.get("reranker_ollama_model", "qwen2.5:7b").strip(),
            "reranker_top_n": int(request.form.get("reranker_top_n", 5)),
            "reranker_return_k": int(request.form.get("reranker_return_k", 5)),
            "reranker_timeout_ms": int(request.form.get("reranker_timeout_ms", 150)),
            "reranker_weight": float(request.form.get("reranker_weight", 0.70)),
            "faiss_weight": float(request.form.get("faiss_weight", 0.30)),
            "trust_weight": float(request.form.get("trust_weight", 0.05)),
            "importance_weight": float(request.form.get("importance_weight", 0.05)),
            "reranker_conditional_threshold": float(request.form.get("reranker_conditional_threshold", 0.08)),
            "reranker_max_text_chars": int(request.form.get("reranker_max_text_chars", 1500)),
            "reranker_device": request.form.get("reranker_device", "cpu").strip(),
            "yolo_model": request.form.get("yolo_model", "yolo26x.pt").strip(),
            "vision_backend": request.form.get("vision_backend", "ultralytics").strip(),
            "camera_index": int(request.form.get("camera_index", 0)),
            "camera_api": request.form.get("camera_api", "auto").strip(),
            "vision_models": [x.strip() for x in request.form.get("vision_models", "").splitlines() if x.strip()],
            "sensitivity_firewall": {
                "block_high": request.form.get("block_high") == "on",
                "block_secret": request.form.get("block_secret") == "on",
                "allow_sensitive_context_for_admin": request.form.get("allow_sensitive_context_for_admin") == "on",
            },
        }
        SettingsService.update(values)
        flash("Settings saved.", "success")
        return redirect(url_for("main.settings"))
    settings_map = {item.key: item.value for item in SettingsService.all()}
    return render_template("settings.html", settings=settings_map, settings_json=json.dumps(settings_map, indent=2))


@main_bp.post("/settings/test-reranker")
@login_required
@minimum_role("operator")
def test_reranker():
    from app.services.reranker_service import RerankerService

    result = RerankerService().test()
    return jsonify(result)


@main_bp.route("/api-keys")
@login_required
def api_keys():
    return render_template("api_keys.html", keys=ApiKey.query.all(), agents=Agent.query.all())


@main_bp.post("/api-keys")
@login_required
@minimum_role("operator")
def create_api_key():
    agent_id = request.form.get("agent_id", type=int)
    if not agent_id:
        flash("Create an agent before creating an API key.", "danger")
        return redirect(url_for("main.api_keys"))
    agent = db.session.get(Agent, agent_id)
    if not agent or not agent.active:
        flash("Choose an active agent before creating an API key.", "danger")
        return redirect(url_for("main.api_keys"))
    name = request.form.get("name", "").strip()
    if not name:
        flash("Enter a name for the API key.", "danger")
        return redirect(url_for("main.api_keys"))
    raw, _ = AdminService.create_api_key(agent.id, name)
    flash(f"New API key, copy it now: {raw}", "warning")
    return redirect(url_for("main.api_keys"))


@main_bp.post("/api-keys/<int:key_id>/rotate")
@login_required
@minimum_role("operator")
def rotate_api_key(key_id):
    raw, _ = AdminService.rotate_api_key(key_id)
    flash(f"Rotated API key, copy it now: {raw}", "warning")
    return redirect(url_for("main.api_keys"))


@main_bp.post("/api-keys/<int:key_id>/revoke")
@login_required
@minimum_role("operator")
def revoke_api_key(key_id):
    AdminService.revoke_api_key(key_id)
    flash("API key revoked.", "success")
    return redirect(url_for("main.api_keys"))


@main_bp.post("/api-keys/<int:key_id>/delete")
@login_required
@role_required("admin")
def delete_api_key(key_id):
    AdminService.delete_api_key(key_id)
    flash("API key deleted.", "success")
    return redirect(url_for("main.api_keys"))


@main_bp.route("/backups")
@login_required
def backups():
    service = BackupService()
    return render_template("backups.html", backups=service.backup_items(), backup_count=len(service.list_backups()))


@main_bp.post("/backups/create")
@login_required
@minimum_role("operator")
def create_backup():
    backup = BackupService().create_backup()
    flash(f"Backup created: {backup['path']}", "success")
    return redirect(url_for("main.backups"))


@main_bp.post("/backups/restore")
@login_required
@role_required("admin")
def restore_backup():
    upload = request.files.get("backup")
    if not upload:
        flash("Choose a backup zip file.", "danger")
        return redirect(url_for("main.backups"))
    result = BackupService().restore_backup(upload)
    flash(f"Restore completed: {result}", "success")
    return redirect(url_for("main.backups"))


@main_bp.post("/backups/<path:filename>/delete")
@login_required
@role_required("admin")
def delete_backup(filename):
    BackupService().delete_backup(filename)
    flash("Backup deleted.", "success")
    return redirect(url_for("main.backups"))


@main_bp.get("/agents/<int:agent_id>/export")
@login_required
@minimum_role("operator")
def export_agent_brain(agent_id):
    path = BackupService().export_agent_brain(agent_id)
    return send_file(path, as_attachment=True)


@main_bp.route("/system-health")
@login_required
def system_health():
    return render_template("system_health.html", health=AdminService.health(), vision=VisionService().status())


@main_bp.post("/memories/<int:memory_id>/confirm")
@login_required
@minimum_role("operator")
def web_confirm_memory(memory_id):
    memory = db.session.get(Memory, memory_id)
    memory.confirmed = True
    memory.pending_approval = False
    db.session.commit()
    flash("Memory confirmed.", "success")
    return redirect(request.referrer or url_for("main.memories"))


@main_bp.post("/memories/<int:memory_id>/archive")
@login_required
@minimum_role("operator")
def web_archive_memory(memory_id):
    MemoryService().archive(db.session.get(Memory, memory_id), current_user.id)
    flash("Memory archived.", "success")
    return redirect(request.referrer or url_for("main.memories"))


@main_bp.post("/memories/<int:memory_id>/forget")
@login_required
@minimum_role("operator")
def web_forget_memory(memory_id):
    MemoryService().delete(db.session.get(Memory, memory_id), current_user.id, forget=True)
    flash("Memory forgotten.", "success")
    return redirect(request.referrer or url_for("main.forget_center"))


@main_bp.post("/memories/<int:memory_id>/delete-hard")
@login_required
@role_required("admin")
def web_delete_memory(memory_id):
    AdminService.delete_memory(memory_id)
    flash("Memory permanently deleted.", "success")
    return redirect(request.referrer or url_for("main.memories"))


@main_bp.post("/sessions/<int:session_id>/delete")
@login_required
@role_required("admin")
def web_delete_session(session_id):
    AdminService.delete_session(session_id)
    flash("Session deleted.", "success")
    return redirect(url_for("main.sessions"))


@main_bp.post("/agents/<int:agent_id>/delete")
@login_required
@role_required("admin")
def delete_agent(agent_id):
    AdminService.delete_agent(agent_id)
    flash("Agent and related records deleted.", "success")
    return redirect(url_for("main.agents"))


@main_bp.post("/workspaces/<int:workspace_id>/delete")
@login_required
@role_required("admin")
def delete_workspace(workspace_id):
    AdminService.delete_workspace(workspace_id)
    flash("Workspace and related records deleted.", "success")
    return redirect(url_for("main.workspaces"))


@main_bp.post("/audit-logs/<int:log_id>/delete")
@login_required
@role_required("admin")
def delete_audit_log(log_id):
    AdminService.delete_audit_log(log_id)
    flash("Audit log deleted.", "success")
    return redirect(url_for("main.audit_logs"))


@main_bp.post("/web/search")
@login_required
def web_search():
    payload = request.get_json(silent=True) or {}
    required = ["workspace_id", "query"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
    try:
        payload.setdefault("include_vector_details", True)
        payload.setdefault("include_correlations", True)
        payload.setdefault("include_timing", True)
        search = MemoryService().search(payload, semantic=True)
        return jsonify(search if isinstance(search, dict) else {"results": search})
    except Exception as exc:
        current_app.logger.exception("Semantic search failed")
        return jsonify({"error": str(exc)}), 500


@main_bp.post("/web/context")
@login_required
def web_context():
    payload = request.get_json(silent=True) or {}
    required = ["agent_id", "workspace_id", "prompt"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
    try:
        payload.setdefault("include_correlations", True)
        payload.setdefault("correlation_limit", 5)
        return jsonify(ContextService().build(payload))
    except Exception as exc:
        current_app.logger.exception("Context builder failed")
        return jsonify({"error": str(exc)}), 500


@main_bp.get("/duplicates")
@login_required
def duplicates():
    groups = AdminService.duplicate_groups()
    return render_template("duplicates.html", groups=groups)


@main_bp.post("/system-health/rebuild-index")
@login_required
@minimum_role("operator")
def rebuild_indexes():
    results = AdminService.rebuild_workspace_indexes()
    flash(f"Rebuilt {len(results)} workspace index(es).", "success")
    return redirect(url_for("main.system_health"))
