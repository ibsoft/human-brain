from datetime import datetime
from pathlib import Path
import time

from flask import current_app

from app.extensions import db
from app.models import Agent, MemoryAsset, VisionEvent, Workspace
from app.services.asset_vector_service import AssetVectorService
from app.services.memory_service import MemoryService, asset_url
from app.services.settings_service import SettingsService
from app.utils.hash import sha256_text


class VisionRuntime:
    running = False
    last_detection = None
    model = None
    model_name = None
    error = None
    last_snapshot = None
    last_auto_saved_signature = None
    last_auto_saved_at = None


DEFAULT_YOLO_MODEL = "models/yolov8n.pt"


class VisionService:
    def _load_model(self):
        model_name = SettingsService.get("yolo_model", DEFAULT_YOLO_MODEL)
        if VisionRuntime.model and VisionRuntime.model_name == model_name:
            return VisionRuntime.model
        try:
            from ultralytics import YOLO

            VisionRuntime.model = YOLO(model_name)
            VisionRuntime.model_name = model_name
            VisionRuntime.error = None
            return VisionRuntime.model
        except Exception as exc:
            VisionRuntime.error = f"Vision model unavailable: {exc}"
            return None

    def start(self):
        if not SettingsService.get("camera_enabled", False):
            return {"running": False, "error": "Camera use is disabled on the Settings page."}
        self._load_model()
        VisionRuntime.running = True
        return {"running": True, "error": VisionRuntime.error}

    def stop(self):
        VisionRuntime.running = False
        return {"running": False}

    def status(self):
        return {
            "running": VisionRuntime.running,
            "camera_enabled": SettingsService.get("camera_enabled", False),
            "camera_index": SettingsService.get("camera_index", 0),
            "camera_api": SettingsService.get("camera_api", "auto"),
            "snapshot_storage_enabled": SettingsService.get("snapshot_storage_enabled", False),
            "vision_auto_save": SettingsService.get("vision_auto_save", False),
            "vision_auto_save_interval_seconds": SettingsService.get("vision_auto_save_interval_seconds", 30),
            "backend": SettingsService.get("vision_backend", "ultralytics"),
            "active_model": SettingsService.get("yolo_model", DEFAULT_YOLO_MODEL),
            "device": SettingsService.get("yolo_device", "cpu"),
            "available_models": SettingsService.get("vision_models", []),
            "last_detection": VisionRuntime.last_detection,
            "snapshot_available": bool(VisionRuntime.last_snapshot),
            "error": VisionRuntime.error,
        }

    def mjpeg_frames(self):
        if not SettingsService.get("camera_enabled", False):
            yield self._jpeg_message("Camera disabled on Settings page.")
            return
        try:
            import cv2
        except Exception as exc:
            yield self._jpeg_message(f"OpenCV unavailable: {exc}")
            return
        camera_index = int(SettingsService.get("camera_index", 0))
        api_name = SettingsService.get("camera_api", "auto")
        api_map = {
            "v4l2": getattr(cv2, "CAP_V4L2", 0),
            "dshow": getattr(cv2, "CAP_DSHOW", 0),
            "avfoundation": getattr(cv2, "CAP_AVFOUNDATION", 0),
        }
        capture = cv2.VideoCapture(camera_index, api_map[api_name]) if api_name in api_map else cv2.VideoCapture(camera_index)
        if not capture.isOpened():
            VisionRuntime.error = f"No webcam available at index {camera_index} using {api_name}."
            yield self._jpeg_message(VisionRuntime.error)
            return
        model = self._load_model()
        VisionRuntime.running = True
        try:
            while VisionRuntime.running:
                ok, frame = capture.read()
                if not ok:
                    break
                labels = []
                if model is not None:
                    try:
                        results = model.predict(frame, verbose=False, conf=0.25, device=SettingsService.get("yolo_device", "cpu"))
                        for box in results[0].boxes:
                            cls = int(box.cls[0])
                            conf = float(box.conf[0])
                            label = results[0].names.get(cls, str(cls))
                            labels.append({"label": label, "confidence": round(conf, 3)})
                            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (72, 196, 255), 2)
                            cv2.putText(frame, f"{label} {conf:.2f}", (x1, max(y1 - 8, 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (72, 196, 255), 2)
                    except Exception as exc:
                        VisionRuntime.error = str(exc)
                elif VisionRuntime.error:
                    self._draw_frame_message(cv2, frame, VisionRuntime.error)
                ok, encoded = cv2.imencode(".jpg", frame)
                if not ok:
                    continue
                snapshot = encoded.tobytes()
                if labels:
                    VisionRuntime.last_snapshot = snapshot
                    VisionRuntime.last_detection = {"timestamp": datetime.utcnow().isoformat(), "objects": labels}
                    self._maybe_auto_save_current_detection(snapshot)
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"
                time.sleep(0.03)
        finally:
            capture.release()
            VisionRuntime.running = False

    def _jpeg_message(self, message):
        try:
            import cv2
            import numpy as np

            frame = np.zeros((540, 960, 3), dtype=np.uint8)
            cv2.putText(frame, message[:90], (40, 270), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (72, 196, 255), 2)
            _, encoded = cv2.imencode(".jpg", frame)
            return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"
        except Exception:
            return b"--frame\r\nContent-Type: text/plain\r\n\r\nVision unavailable\r\n"

    def _draw_frame_message(self, cv2, frame, message):
        lines = ["Detector unavailable", str(message)[:86]]
        y = 36
        for line in lines:
            cv2.putText(frame, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (0, 0, 0), 4)
            cv2.putText(frame, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (72, 196, 255), 2)
            y += 30

    def save_memory(self, payload):
        event = VisionEvent(
            workspace_id=payload["workspace_id"],
            agent_id=payload.get("agent_id"),
            label=payload["label"],
            confidence=float(payload.get("confidence", 0.0)),
            snapshot_path=payload.get("snapshot_path") if SettingsService.get("snapshot_storage_enabled", False) else None,
            meta=payload.get("metadata") or {"timestamp": datetime.utcnow().isoformat()},
        )
        db.session.add(event)
        db.session.flush()
        memory, _ = MemoryService().add_memory(
            {
                "workspace_id": event.workspace_id,
                "agent_id": event.agent_id or payload["agent_id"],
                "title": f"Vision detected {event.label}",
                "content": f"Local vision detected {event.label} with confidence {event.confidence:.2f}.",
                "memory_type": "vision",
                "tags": ["vision", event.label],
                "importance_score": 0.35,
                "trust_score": min(max(event.confidence, 0.1), 1.0),
                "source": "vision",
                "confirmed": False,
                "storage_reason": "Saved manually from the Vision page.",
            }
        )
        event.saved_as_memory_id = memory.id
        db.session.commit()
        return event, memory

    def save_current_detection(self, workspace_id, agent_id, source="manual", actor_type="user", actor_id=None):
        detection = VisionRuntime.last_detection
        if not detection or not detection.get("objects"):
            raise ValueError("No object detection is available yet.")
        objects = detection["objects"]
        labels = [item["label"] for item in objects if item.get("label")]
        label_summary = ", ".join(dict.fromkeys(labels)) or "objects"
        snapshot = VisionRuntime.last_snapshot if SettingsService.get("snapshot_storage_enabled", False) else None
        event = VisionEvent(
            workspace_id=workspace_id,
            agent_id=agent_id,
            label=label_summary[:120],
            confidence=max(float(item.get("confidence", 0.0)) for item in objects),
            meta={
                "timestamp": detection.get("timestamp"),
                "objects": objects,
                "source": source,
                "snapshot_attached": bool(snapshot),
            },
        )
        db.session.add(event)
        db.session.flush()
        content_lines = [
            f"Local vision detected {label_summary}.",
            f"Timestamp: {detection.get('timestamp')}",
            "Objects:",
        ]
        for item in objects:
            content_lines.append(f"- {item.get('label')} confidence {float(item.get('confidence', 0.0)):.2f}")
        if snapshot:
            content_lines.append("Snapshot: attached image asset.")
        else:
            content_lines.append("Snapshot: not stored because snapshot storage is disabled.")
        memory, _ = MemoryService().add_memory(
            {
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "title": f"Vision detected {label_summary}",
                "content": "\n".join(content_lines),
                "summary": f"Detected {label_summary} from the local camera.",
                "memory_type": "vision",
                "tags": sorted(set(["vision", "camera", source] + labels)),
                "importance_score": 0.35,
                "trust_score": min(max(event.confidence, 0.1), 1.0),
                "source": f"vision_{source}",
                "confirmed": source == "manual",
                "storage_reason": f"Saved {source} from the Vision page.",
            },
            actor_type=actor_type,
            actor_id=actor_id,
        )
        event.saved_as_memory_id = memory.id
        if snapshot:
            asset = self._attach_snapshot_asset(memory, snapshot, detection)
            memory.content = f"{memory.content.rstrip()}\nSnapshot URL: {asset_url(asset, external=True)}"
            memory.content_hash = sha256_text(memory.content.strip())
        db.session.commit()
        if snapshot:
            try:
                service = MemoryService()
                service.faiss.upsert_memory(memory, service.embedding_service)
            except Exception:
                current_app.logger.exception("Could not refresh vision snapshot memory vector")
        return event, memory

    def _maybe_auto_save_current_detection(self, snapshot):
        if not SettingsService.get("vision_auto_save", False):
            return
        detection = VisionRuntime.last_detection
        if not detection or not detection.get("objects"):
            return
        signature = self._detection_signature(detection["objects"])
        now = time.time()
        interval = max(int(SettingsService.get("vision_auto_save_interval_seconds", 30) or 30), 5)
        if signature == VisionRuntime.last_auto_saved_signature and VisionRuntime.last_auto_saved_at and now - VisionRuntime.last_auto_saved_at < interval:
            return
        workspace = Workspace.query.order_by(Workspace.id.asc()).first()
        agent = Agent.query.filter_by(active=True).order_by(Agent.id.asc()).first()
        if not workspace or not agent:
            VisionRuntime.error = "Vision auto-save requires at least one workspace and active agent."
            return
        try:
            VisionRuntime.last_snapshot = snapshot
            self.save_current_detection(workspace.id, agent.id, source="auto", actor_type="system", actor_id=None)
            VisionRuntime.last_auto_saved_signature = signature
            VisionRuntime.last_auto_saved_at = now
        except Exception as exc:
            VisionRuntime.error = f"Vision auto-save failed: {exc}"
            current_app.logger.exception("Vision auto-save failed")

    def _detection_signature(self, objects):
        parts = [f"{item.get('label')}:{round(float(item.get('confidence', 0.0)), 1)}" for item in objects]
        return "|".join(sorted(parts))

    def _attach_snapshot_asset(self, memory, snapshot, detection):
        snapshot_dir = Path(current_app.config["SNAPSHOT_DIR"])
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        filename = f"vision_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}.jpg"
        path = snapshot_dir / filename
        path.write_bytes(snapshot)
        vector, vector_hash, metadata = AssetVectorService().image_vector(path)
        metadata = {
            **metadata,
            "timestamp": detection.get("timestamp"),
            "objects": detection.get("objects", []),
            "source": "vision_snapshot",
        }
        asset = MemoryAsset(
            memory_id=memory.id,
            workspace_id=memory.workspace_id,
            asset_type="image",
            original_filename=filename,
            stored_path=str(path),
            content_type="image/jpeg",
            vector_hash=vector_hash,
            vector_dim=len(vector) if vector else None,
            vector=vector,
            asset_metadata=metadata,
        )
        db.session.add(asset)
        db.session.flush()
        return asset
