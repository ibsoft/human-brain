from flask import Blueprint, Response, abort, flash, g, jsonify, redirect, render_template, request, stream_with_context, url_for
from flask_login import current_user, login_required

from app.models import Agent, Workspace
from app.security.auth import require_api_key, require_workspace_access
from app.security.rbac import minimum_role
from app.services.memory_service import serialize_memory
from app.services.vision_service import VisionService

vision_bp = Blueprint("vision", __name__)


@vision_bp.get("/vision")
@login_required
def vision_page():
    return render_template("vision.html", status=VisionService().status(), agents=Agent.query.filter_by(active=True).all(), workspaces=Workspace.query.all())


@vision_bp.get("/vision/stream")
@login_required
def vision_stream():
    return Response(stream_with_context(VisionService().mjpeg_frames()), mimetype="multipart/x-mixed-replace; boundary=frame")


@vision_bp.get("/vision/status")
@login_required
def vision_status_web():
    return jsonify(VisionService().status())


@vision_bp.post("/vision/save-current")
@login_required
@minimum_role("operator")
def vision_save_current_web():
    workspace_id = request.form.get("workspace_id", type=int)
    agent_id = request.form.get("agent_id", type=int)
    if not workspace_id or not agent_id:
        flash("Choose a workspace and active agent before saving a vision memory.", "danger")
        return redirect(url_for("vision.vision_page"))
    try:
        event, memory = VisionService().save_current_detection(workspace_id, agent_id, source="manual", actor_type="user", actor_id=current_user.id)
        flash(f"Vision memory {memory.id} stored for event {event.id}.", "success")
    except ValueError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("vision.vision_page"))


@vision_bp.post("/api/v1/vision/start")
@require_api_key
def vision_start():
    return jsonify(VisionService().start())


@vision_bp.post("/api/v1/vision/stop")
@require_api_key
def vision_stop():
    return jsonify(VisionService().stop())


@vision_bp.get("/api/v1/vision/status")
@require_api_key
def vision_status():
    return jsonify(VisionService().status())


@vision_bp.post("/api/v1/vision/save-memory")
@require_api_key
def vision_save_memory():
    payload = request.get_json(silent=True) or {}
    if payload.get("agent_id") and int(payload["agent_id"]) != g.agent.id:
        abort(403, description="API key cannot act as another agent")
    payload["agent_id"] = g.agent.id
    event, memory = VisionService().save_memory(payload)
    return jsonify({"event_id": event.id, "memory": serialize_memory(memory)}), 201


@vision_bp.post("/api/v1/vision/save-current")
@require_api_key
def vision_save_current():
    payload = request.get_json(silent=True) or {}
    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        abort(400, description="workspace_id is required")
    require_workspace_access(g.agent.id, int(workspace_id))
    event, memory = VisionService().save_current_detection(int(workspace_id), g.agent.id, source="manual", actor_type="agent", actor_id=g.agent.id)
    return jsonify({"event_id": event.id, "memory": serialize_memory(memory)}), 201
