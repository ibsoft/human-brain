import json
from datetime import datetime
from pathlib import Path

from flask import current_app


class AgentLogService:
    LEVELS = {"debug": 10, "info": 20, "warning": 30}

    def __init__(self):
        self.log_dir = Path(current_app.root_path).parent / "logs" / "agent_api"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def enabled(self):
        from app.services.settings_service import SettingsService

        return bool(SettingsService.get("agent_api_logging_enabled", True))

    def should_log(self, level):
        from app.services.settings_service import SettingsService

        configured = str(SettingsService.get("agent_api_log_level", "info")).lower()
        return self.LEVELS.get(level, 20) >= self.LEVELS.get(configured, 20)

    def write(self, record, level="info"):
        if not self.enabled() or not self.should_log(level):
            return
        record = {"ts": datetime.utcnow().isoformat(), "level": level, **record}
        path = self._active_path()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._rotate_if_needed(path)

    def items(self, query="", page=1, per_page=50):
        query = (query or "").lower()
        rows = []
        for path in sorted(self.log_dir.glob("agent_api*.jsonl"), reverse=True):
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_no, line in enumerate(handle, 1):
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        payload = {"ts": "", "level": "warning", "error": "Invalid JSONL", "raw": line}
                    detail = self._decode_for_display(payload)
                    searchable = f"{line}\n{json.dumps(detail, ensure_ascii=False, default=str)}".lower()
                    if query and query not in searchable:
                        continue
                    row = dict(detail)
                    row["_file"] = path.name
                    row["_line"] = line_no
                    row["_detail"] = detail
                    rows.append(row)
        rows.sort(key=lambda row: row.get("ts") or "", reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * per_page
        return {"items": rows[start : start + per_page], "total": total, "page": page, "per_page": per_page}

    def _decode_for_display(self, value):
        if isinstance(value, dict):
            return {key: self._decode_for_display(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._decode_for_display(item) for item in value]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped[:1] in ("{", "[") and stripped[-1:] in ("}", "]"):
                try:
                    return self._decode_for_display(json.loads(stripped))
                except ValueError:
                    return value
        return value

    def _active_path(self):
        return self.log_dir / "agent_api.jsonl"

    def _rotate_if_needed(self, path):
        from app.services.settings_service import SettingsService

        max_bytes = int(SettingsService.get("agent_api_log_max_mb", 10)) * 1024 * 1024
        keep = max(1, int(SettingsService.get("agent_api_log_keep_files", 5)))
        if not path.exists() or path.stat().st_size <= max_bytes:
            return
        stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        path.rename(self.log_dir / f"agent_api_{stamp}.jsonl")
        rotated = sorted(self.log_dir.glob("agent_api_*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in rotated[keep:]:
            old.unlink(missing_ok=True)
