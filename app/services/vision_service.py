from datetime import datetime, timedelta
from pathlib import Path
import time

from flask import current_app

from app.extensions import db
from app.models import Agent, Memory, MemoryAsset, VisionEvent, Workspace
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
    current_scene_signature = None
    current_scene_seen = 0
    last_scene_status = None


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
            VisionRuntime.error = f"Vision model unavailable: {self._model_error_message(model_name, exc)}"
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
            "vision_auto_save_min_confidence": SettingsService.get("vision_auto_save_min_confidence", 0.55),
            "vision_scene_stable_frames": SettingsService.get("vision_scene_stable_frames", 3),
            "backend": SettingsService.get("vision_backend", "ultralytics"),
            "active_model": SettingsService.get("yolo_model", DEFAULT_YOLO_MODEL),
            "device": SettingsService.get("yolo_device", "cpu"),
            "available_models": SettingsService.get("vision_models", []),
            "last_detection": VisionRuntime.last_detection,
            "last_scene": VisionRuntime.last_scene_status,
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
            self._draw_frame_message(cv2, frame, message)
            _, encoded = cv2.imencode(".jpg", frame)
            return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded.tobytes() + b"\r\n"
        except Exception:
            return b"--frame\r\nContent-Type: text/plain\r\n\r\nVision unavailable\r\n"

    def _draw_frame_message(self, cv2, frame, message):
        height, width = frame.shape[:2]
        max_chars = max(28, min(84, width // 12))
        lines = ["Detector unavailable"] + self._wrap_text(str(message), max_chars)[:5]
        panel_x = 24
        panel_w = min(width - 48, 900)
        panel_h = 34 + (len(lines) * 30)
        panel_y = min(max(height // 3, 96), max(height - panel_h - 24, 24))
        overlay = frame.copy()
        cv2.rectangle(overlay, (panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h), (8, 20, 18), -1)
        cv2.addWeighted(overlay, 0.82, frame, 0.18, 0, frame)
        cv2.rectangle(frame, (panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h), (72, 196, 255), 2)
        y = panel_y + 32
        for line in lines:
            cv2.putText(frame, line, (panel_x + 18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (0, 0, 0), 4)
            cv2.putText(frame, line, (panel_x + 18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (230, 255, 249), 2)
            y += 30

    def _wrap_text(self, text, max_chars):
        words = text.replace("\n", " ").split()
        lines = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = word[:max_chars]
        if current:
            lines.append(current)
        return lines or [""]

    def _model_error_message(self, model_name, exc):
        message = str(exc)
        if "C3k2" in message:
            return (
                f"{model_name} requires a newer Ultralytics/PyTorch model runtime than this install. "
                "Use models/yolov8n.pt or upgrade the ML dependencies before selecting this model."
            )
        return message

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
        label_summary = self._scene_label_summary(objects)
        scene_sentence = self._scene_sentence(objects)
        signature = self._scene_signature(objects)
        snapshot = VisionRuntime.last_snapshot if SettingsService.get("snapshot_storage_enabled", False) else None
        duplicate = self._recent_duplicate_scene(workspace_id, signature, source)
        if duplicate:
            return duplicate
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
                "scene_signature": signature,
                "scene_summary": scene_sentence,
            },
        )
        db.session.add(event)
        db.session.flush()
        content_lines = [
            scene_sentence,
            f"Timestamp: {detection.get('timestamp')}",
            f"Scene signature: {signature}",
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
                "title": f"Vision scene: {label_summary}",
                "content": "\n".join(content_lines),
                "summary": scene_sentence,
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

    def _recent_duplicate_scene(self, workspace_id, signature, source):
        window_seconds = max(int(SettingsService.get("vision_auto_save_interval_seconds", 30) or 30), 5)
        if source == "manual":
            window_seconds = 60
        since = datetime.utcnow() - timedelta(seconds=window_seconds)
        events = (
            VisionEvent.query.filter(
                VisionEvent.workspace_id == workspace_id,
                VisionEvent.created_at >= since,
                VisionEvent.saved_as_memory_id.isnot(None),
            )
            .order_by(VisionEvent.created_at.desc())
            .limit(50)
            .all()
        )
        for event in events:
            meta = event.meta or {}
            if meta.get("scene_signature") == signature and meta.get("source") == source:
                memory = db.session.get(Memory, event.saved_as_memory_id)
                if memory and not memory.deleted_at:
                    return event, memory
        return None

    def _maybe_auto_save_current_detection(self, snapshot):
        if not SettingsService.get("vision_auto_save", False):
            return
        detection = VisionRuntime.last_detection
        if not detection or not detection.get("objects"):
            return
        min_confidence = float(SettingsService.get("vision_auto_save_min_confidence", 0.55) or 0.55)
        stable_frames = max(int(SettingsService.get("vision_scene_stable_frames", 3) or 3), 1)
        objects = self._significant_objects(detection["objects"], min_confidence)
        if not objects:
            VisionRuntime.last_scene_status = {
                "status": "ignored",
                "reason": "no_objects_above_min_confidence",
                "min_confidence": min_confidence,
                "timestamp": detection.get("timestamp"),
            }
            return
        signature = self._scene_signature(objects)
        if signature == VisionRuntime.current_scene_signature:
            VisionRuntime.current_scene_seen += 1
        else:
            VisionRuntime.current_scene_signature = signature
            VisionRuntime.current_scene_seen = 1
        VisionRuntime.last_scene_status = {
            "status": "observing",
            "signature": signature,
            "summary": self._scene_sentence(objects),
            "stable_frames_seen": VisionRuntime.current_scene_seen,
            "stable_frames_required": stable_frames,
            "min_confidence": min_confidence,
            "timestamp": detection.get("timestamp"),
        }
        if VisionRuntime.current_scene_seen < stable_frames:
            return
        now = time.time()
        interval = max(int(SettingsService.get("vision_auto_save_interval_seconds", 30) or 30), 5)
        if signature == VisionRuntime.last_auto_saved_signature and VisionRuntime.last_auto_saved_at and now - VisionRuntime.last_auto_saved_at < interval:
            VisionRuntime.last_scene_status["status"] = "suppressed"
            VisionRuntime.last_scene_status["reason"] = "same_scene_inside_interval"
            return
        workspace = Workspace.query.order_by(Workspace.id.asc()).first()
        agent = Agent.query.filter_by(active=True).order_by(Agent.id.asc()).first()
        if not workspace or not agent:
            VisionRuntime.error = "Vision auto-save requires at least one workspace and active agent."
            return
        try:
            VisionRuntime.last_snapshot = snapshot
            VisionRuntime.last_detection = {**detection, "objects": objects}
            self.save_current_detection(workspace.id, agent.id, source="auto", actor_type="system", actor_id=None)
            VisionRuntime.last_auto_saved_signature = signature
            VisionRuntime.last_auto_saved_at = now
            VisionRuntime.last_scene_status["status"] = "saved"
            VisionRuntime.last_scene_status["saved_at"] = datetime.utcnow().isoformat()
        except Exception as exc:
            VisionRuntime.error = f"Vision auto-save failed: {exc}"
            current_app.logger.exception("Vision auto-save failed")

    def _significant_objects(self, objects, min_confidence):
        return [item for item in objects if item.get("label") and float(item.get("confidence", 0.0)) >= min_confidence]

    def _scene_counts(self, objects):
        counts = {}
        for item in objects:
            label = str(item.get("label") or "").strip()
            if label:
                counts[label] = counts.get(label, 0) + 1
        return dict(sorted(counts.items()))

    def _scene_signature(self, objects):
        counts = self._scene_counts(objects)
        return "|".join(f"{label}:{count}" for label, count in counts.items()) or "empty"

    def _scene_label_summary(self, objects):
        counts = self._scene_counts(objects)
        parts = [f"{count} {label}{'' if count == 1 else 's'}" for label, count in counts.items()]
        return ", ".join(parts) or "objects"

    def _scene_sentence(self, objects):
        counts = self._scene_counts(objects)
        if not counts:
            return "Local vision did not detect significant objects."
        parts = [f"{count} {label}{'' if count == 1 else 's'}" for label, count in counts.items()]
        if len(parts) == 1:
            summary = parts[0]
        else:
            summary = f"{', '.join(parts[:-1])} and {parts[-1]}"
        return f"Local vision observed a scene with {summary}."

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
