from datetime import datetime
import time

from app.extensions import db
from app.models import VisionEvent
from app.services.memory_service import MemoryService
from app.services.settings_service import SettingsService


class VisionRuntime:
    running = False
    last_detection = None
    model = None
    model_name = None
    error = None


class VisionService:
    def _load_model(self):
        model_name = SettingsService.get("yolo_model", "yolo26x.pt")
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
            "backend": SettingsService.get("vision_backend", "ultralytics"),
            "active_model": SettingsService.get("yolo_model", "yolo26x.pt"),
            "available_models": SettingsService.get("vision_models", []),
            "last_detection": VisionRuntime.last_detection,
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
                        results = model.predict(frame, verbose=False, conf=0.25)
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
                if labels:
                    VisionRuntime.last_detection = {"timestamp": datetime.utcnow().isoformat(), "objects": labels}
                ok, encoded = cv2.imencode(".jpg", frame)
                if not ok:
                    continue
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
