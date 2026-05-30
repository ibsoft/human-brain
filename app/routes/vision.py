from flask import Blueprint, Response, abort, g, jsonify, render_template, request, stream_with_context
from flask_login import login_required

from app.security.auth import require_api_key
from app.services.memory_service import serialize_memory
from app.services.vision_service import VisionService

vision_bp = Blueprint("vision", __name__)


@vision_bp.get("/vision")
@login_required
def vision_page():
    return render_template("vision.html", status=VisionService().status())


@vision_bp.get("/vision/stream")
@login_required
def vision_stream():
    return Response(stream_with_context(VisionService().mjpeg_frames()), mimetype="multipart/x-mixed-replace; boundary=frame")


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
