from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter

from flask import current_app
from sqlalchemy import text

from app.extensions import db
from app.models import HealthCheckRun, Memory, MemoryVector, Workspace
from app.services.embedding_service import EmbeddingService
from app.services.faiss_service import FaissService
from app.services.settings_service import SettingsService


class HealthCheckService:
    def should_run_scheduled(self, now=None):
        now = now or datetime.utcnow()
        schedule = SettingsService.get("health_check_schedule", {})
        if not schedule.get("enabled"):
            return False, "disabled"
        frequency = schedule.get("frequency", "daily")
        configured_time = str(schedule.get("time", "04:00") or "04:00")
        hour = self._configured_hour(configured_time)
        if frequency in {"daily", "weekly"} and now.hour != hour:
            return False, "outside_configured_hour"
        if frequency == "weekly" and now.weekday() != 0:
            return False, "outside_weekly_window"
        last_run = (
            HealthCheckRun.query.filter_by(trigger="scheduled")
            .filter(HealthCheckRun.status.in_(["completed", "failed"]))
            .order_by(HealthCheckRun.started_at.desc())
            .first()
        )
        if last_run and not self._window_elapsed(last_run.started_at, now, frequency):
            return False, "already_ran_in_window"
        return True, "due"

    def run(self, trigger="manual", auto_repair=None):
        schedule = SettingsService.get("health_check_schedule", {})
        if auto_repair is None:
            auto_repair = bool(schedule.get("auto_repair", True))
        started = perf_counter()
        run = HealthCheckRun(trigger=trigger, status="running", severity="info", auto_repair=bool(auto_repair))
        db.session.add(run)
        db.session.commit()
        try:
            result = self._run_checks(auto_repair=bool(auto_repair))
            run.status = "completed"
            run.severity = result["severity"]
            run.summary = result["summary"]
            run.checks = result["checks"]
            run.repairs = result["repairs"]
            run.metrics = result["metrics"]
        except Exception as exc:
            run.status = "failed"
            run.severity = "error"
            run.summary = "Health check failed before completion."
            run.error = str(exc)
        run.completed_at = datetime.utcnow()
        run.duration_ms = round((perf_counter() - started) * 1000, 2)
        db.session.commit()
        return run

    def _run_checks(self, auto_repair):
        checks = []
        repairs = []
        metrics = {}

        checks.append(self._database_check())
        checks.extend(self._directory_checks())
        faiss_result = self._faiss_check()
        checks.extend(faiss_result["checks"])
        metrics.update(faiss_result["metrics"])

        repair_workspace_ids = set(faiss_result["repair_workspace_ids"])
        if auto_repair and repair_workspace_ids:
            repairs.extend(self._repair_faiss(sorted(repair_workspace_ids)))
            repaired_result = self._faiss_check()
            checks.append(
                {
                    "name": "FAISS after repair",
                    "status": "ok" if not repaired_result["repair_workspace_ids"] else "warning",
                    "message": "FAISS indexes were rechecked after automatic repair.",
                    "details": repaired_result["metrics"],
                }
            )
            metrics["faiss_after_repair"] = repaired_result["metrics"]

        severity = self._severity(checks)
        issue_count = sum(1 for check in checks if check["status"] != "ok")
        if repairs:
            summary = f"{issue_count} issue(s) found; {len(repairs)} repair action(s) completed."
        elif issue_count:
            summary = f"{issue_count} issue(s) found."
        else:
            summary = "All health checks passed."
        return {"severity": severity, "summary": summary, "checks": checks, "repairs": repairs, "metrics": metrics}

    def _database_check(self):
        db.session.execute(text("select 1"))
        return {"name": "Database", "status": "ok", "message": "Database connection is reachable."}

    def _directory_checks(self):
        paths = {
            "FAISS index directory": Path(current_app.config["FAISS_INDEX_DIR"]),
            "Snapshot directory": Path(current_app.config["SNAPSHOT_DIR"]),
            "Memory upload directory": Path(current_app.config["MEMORY_UPLOAD_DIR"]),
        }
        checks = []
        for name, path in paths.items():
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".healthcheck"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                checks.append({"name": name, "status": "ok", "message": f"{path} is writable."})
            except Exception as exc:
                checks.append({"name": name, "status": "error", "message": f"{path} is not writable: {exc}"})
        return checks

    def _faiss_check(self):
        service = FaissService(current_app.config["FAISS_INDEX_DIR"])
        health = service.health()
        checks = []
        repair_workspace_ids = set()
        index_rows = health.get("loaded_indexes", [])

        for item in index_rows:
            workspace_id = item["workspace_id"]
            active_count = Memory.query.filter_by(workspace_id=workspace_id, archived=False, deleted_at=None).count()
            status = item.get("status")
            vectors = int(item.get("vectors") or 0)
            if status != "ready":
                checks.append(
                    {
                        "name": f"FAISS workspace {workspace_id}",
                        "status": "warning",
                        "message": f"{item.get('workspace')} index is {status}.",
                        "details": item,
                    }
                )
                repair_workspace_ids.add(workspace_id)
            elif active_count != vectors:
                checks.append(
                    {
                        "name": f"FAISS workspace {workspace_id}",
                        "status": "warning",
                        "message": f"{item.get('workspace')} has {active_count} active memories but {vectors} FAISS vectors.",
                        "details": item,
                    }
                )
                repair_workspace_ids.add(workspace_id)
            else:
                checks.append(
                    {
                        "name": f"FAISS workspace {workspace_id}",
                        "status": "ok",
                        "message": f"{item.get('workspace')} index is ready with {vectors} vectors.",
                        "details": item,
                    }
                )

        missing_vectors = int(health.get("memories_without_vectors") or 0)
        missing_faiss = int(health.get("missing_faiss_vectors") or 0)
        orphan_vectors = int(health.get("orphan_database_vectors") or 0)
        if missing_vectors:
            checks.append({"name": "Memory vectors", "status": "warning", "message": f"{missing_vectors} active memories do not have vector rows."})
            for (workspace_id,) in (
                Memory.query.with_entities(Memory.workspace_id)
                .filter_by(archived=False, deleted_at=None)
                .outerjoin(MemoryVector, MemoryVector.memory_id == Memory.id)
                .filter(MemoryVector.id.is_(None))
                .distinct()
                .all()
            ):
                repair_workspace_ids.add(workspace_id)
        if missing_faiss:
            checks.append({"name": "FAISS mappings", "status": "warning", "message": f"{missing_faiss} database vectors are missing from FAISS indexes."})
            repair_workspace_ids.update(workspace.id for workspace in Workspace.query.all())
        if orphan_vectors:
            checks.append({"name": "Orphan vectors", "status": "warning", "message": f"{orphan_vectors} database vector rows no longer map to active memories."})
            repair_workspace_ids.update(workspace.id for workspace in Workspace.query.all())
        if not index_rows:
            checks.append({"name": "FAISS indexes", "status": "ok", "message": "No workspaces exist yet."})
        return {"checks": checks, "metrics": {"faiss": health}, "repair_workspace_ids": repair_workspace_ids}

    def _repair_faiss(self, workspace_ids):
        service = FaissService(current_app.config["FAISS_INDEX_DIR"])
        embeddings = EmbeddingService(SettingsService.get("embedding_model", current_app.config["EMBEDDING_MODEL"]))
        repairs = []
        for workspace_id in workspace_ids:
            workspace = db.session.get(Workspace, workspace_id)
            if not workspace:
                continue
            result = service.rebuild(workspace.id, embeddings)
            repairs.append({"type": "faiss_rebuild", "workspace_id": workspace.id, "workspace": workspace.name, "result": result})
        return repairs

    def _severity(self, checks):
        if any(check["status"] == "error" for check in checks):
            return "error"
        if any(check["status"] == "warning" for check in checks):
            return "warning"
        return "ok"

    def _configured_hour(self, configured_time):
        try:
            return max(0, min(23, int(configured_time.split(":", 1)[0])))
        except (TypeError, ValueError):
            return 4

    def _window_elapsed(self, last_started_at, now, frequency):
        if frequency == "hourly":
            return last_started_at <= now - timedelta(hours=1)
        if frequency == "weekly":
            return last_started_at.date().isocalendar()[:2] != now.date().isocalendar()[:2]
        return last_started_at.date() != now.date()
