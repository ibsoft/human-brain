from datetime import datetime, timedelta

from app.models import AuditLog, Memory
from app.services.admin_service import AdminService
from app.services.settings_service import SettingsService


class MemoryQualityService:
    TASK_FIELDS = {
        "task_status": "Task status",
        "task_priority": "Task priority",
        "task_owner": "Task owner",
        "task_due_at": "Task due",
        "task_next_action": "Next action",
        "task_acceptance_criteria": "Acceptance criteria",
        "task_dependencies": "Dependencies",
    }
    PROJECT_FIELDS = {
        "project_status": "Project status",
        "project_goal": "Project goal",
        "project_phase": "Project phase",
        "project_next_actions": "Next actions",
        "project_decisions": "Decisions",
        "project_risks": "Risks",
        "project_open_questions": "Open questions",
    }

    def quality_policy(self):
        return SettingsService.get("memory_quality_policy", {}) or {}

    def enforcement_policy(self):
        return SettingsService.get("agent_enforcement", {}) or {}

    def stale_policy(self):
        return SettingsService.get("stale_memory_policy", {}) or {}

    def normalize_payload(self, payload):
        normalized = dict(payload)
        tags = self._tags(normalized.get("tags"))
        memory_type = str(normalized.get("memory_type") or "").lower()
        content = str(normalized.get("content") or "")
        sections = []

        if self._is_task_payload(memory_type, tags, normalized):
            tags = self._add_tags(tags, ["task"])
            sections.extend(self._workflow_lines(normalized, self.TASK_FIELDS))
            status = normalized.get("task_status")
            priority = normalized.get("task_priority")
            if status:
                tags = self._add_tags(tags, [f"status-{self._tag_value(status)}"])
            if priority:
                tags = self._add_tags(tags, [f"priority-{self._tag_value(priority)}"])

        if self._is_project_payload(memory_type, tags, normalized):
            tags = self._add_tags(tags, ["project"])
            sections.extend(self._workflow_lines(normalized, self.PROJECT_FIELDS))
            status = normalized.get("project_status")
            if status:
                tags = self._add_tags(tags, [f"status-{self._tag_value(status)}"])

        if sections and "Human-Brain workflow fields:" not in content:
            normalized["content"] = content.rstrip() + "\n\nHuman-Brain workflow fields:\n" + "\n".join(sections)
        normalized["tags"] = tags
        return normalized

    def evaluate_payload(self, payload):
        policy = self.quality_policy()
        if not policy.get("enabled", True):
            return {
                "enabled": False,
                "score": 100,
                "level": "disabled",
                "warnings": [],
                "reject_low_quality": False,
                "reject_below_score": int(policy.get("reject_below_score", 50)),
            }
        content = str(payload.get("content") or "").strip()
        title = str(payload.get("title") or "").strip()
        tags = self._tags(payload.get("tags"))
        storage_reason = str(payload.get("storage_reason") or "").strip()
        warnings = []
        score = 100

        min_content_chars = int(policy.get("min_content_chars", 20))
        min_tags = int(policy.get("min_tags", 1))
        if len(content) < min_content_chars:
            score -= 30
            warnings.append("content_too_short")
        if policy.get("require_title", True) and not title:
            score -= 15
            warnings.append("missing_title")
        if len(tags) < min_tags:
            score -= 15
            warnings.append("missing_tags")
        if policy.get("require_storage_reason", True) and not storage_reason:
            score -= 15
            warnings.append("missing_storage_reason")
        if self._is_task_payload(str(payload.get("memory_type") or "").lower(), tags, payload):
            for key in ("task_status", "task_next_action"):
                if not payload.get(key) and key.replace("task_", "").replace("_", " ") not in content.lower():
                    score -= 8
                    warnings.append(f"missing_{key}")
        if self._is_project_payload(str(payload.get("memory_type") or "").lower(), tags, payload):
            for key in ("project_goal", "project_status"):
                if not payload.get(key) and key.replace("project_", "").replace("_", " ") not in content.lower():
                    score -= 8
                    warnings.append(f"missing_{key}")

        score = max(0, min(100, score))
        return {
            "enabled": bool(policy.get("enabled", True)),
            "score": score,
            "level": "good" if score >= 80 else ("needs_review" if score >= 50 else "poor"),
            "warnings": warnings,
            "reject_low_quality": bool(policy.get("reject_low_quality", False)),
            "reject_below_score": int(policy.get("reject_below_score", 50)),
        }

    def write_policy_status(self, payload):
        policy = self.enforcement_policy()
        window_minutes = int(policy.get("search_window_minutes", 30))
        recent = self.recent_agent_search(payload.get("agent_id"), payload.get("workspace_id"), window_minutes)
        warnings = []
        if policy.get("enabled", True) and policy.get("require_search_before_write", True) and not recent:
            warnings.append("search_before_write_missing")
        return {
            "enabled": bool(policy.get("enabled", True)),
            "strict_mode": bool(policy.get("strict_mode", False)),
            "search_before_write_ok": bool(recent),
            "search_window_minutes": window_minutes,
            "warnings": warnings,
        }

    def search_policy_status(self):
        policy = self.enforcement_policy()
        return {
            "enabled": bool(policy.get("enabled", True)),
            "search_before_answer": bool(policy.get("require_search_before_answer", True)),
            "write_back_after_work": bool(policy.get("require_writeback_after_work", True)),
            "instruction": "Use these results before answering, then write back durable outcomes, decisions, tasks, corrections, and next steps.",
        }

    def recent_agent_search(self, agent_id, workspace_id, window_minutes):
        if not agent_id or not workspace_id:
            return None
        cutoff = datetime.utcnow() - timedelta(minutes=max(window_minutes, 1))
        return (
            AuditLog.query.filter(
                AuditLog.actor_type == "agent",
                AuditLog.actor_id == str(agent_id),
                AuditLog.workspace_id == int(workspace_id),
                AuditLog.action.in_(["agent.memory_search", "agent.context_build"]),
                AuditLog.created_at >= cutoff,
            )
            .order_by(AuditLog.created_at.desc())
            .first()
        )

    def stale_memories(self, workspace_id, page=1, per_page=25):
        policy = self.stale_policy()
        if not policy.get("enabled", True):
            return Memory.query.filter(Memory.id == -1).paginate(page=page, per_page=per_page, error_out=False)
        stale_after_days = int(policy.get("stale_after_days", 90))
        cutoff = datetime.utcnow() - timedelta(days=max(stale_after_days, 1))
        return (
            Memory.query.filter(
                Memory.workspace_id == int(workspace_id),
                Memory.archived.is_(False),
                Memory.deleted_at.is_(None),
                Memory.updated_at < cutoff,
            )
            .order_by(Memory.updated_at.asc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

    def quality_report(self, workspace_id):
        stale = self.stale_memories(workspace_id, page=1, per_page=1)
        memories = (
            Memory.query.filter_by(workspace_id=workspace_id, archived=False, deleted_at=None)
            .order_by(Memory.updated_at.desc())
            .limit(500)
            .all()
        )
        low_quality = []
        for memory in memories:
            quality = self.evaluate_payload(
                {
                    "title": memory.title,
                    "content": memory.content,
                    "tags": memory.tags or [],
                    "storage_reason": memory.storage_reason,
                    "memory_type": memory.memory_type,
                }
            )
            if quality["score"] < int(self.quality_policy().get("warn_below_score", 70)):
                low_quality.append({"id": memory.id, "title": memory.title, "score": quality["score"], "warnings": quality["warnings"]})
        duplicate_groups = [group for group in AdminService.duplicate_groups(workspace_id=workspace_id) if len(group.get("memories") or []) > 1]
        return {
            "workspace_id": workspace_id,
            "active_memories": len(memories),
            "low_quality_count": len(low_quality),
            "low_quality": low_quality[:25],
            "stale_count": stale.total,
            "stale_after_days": int(self.stale_policy().get("stale_after_days", 90)),
            "duplicate_group_count": len(duplicate_groups),
            "duplicate_groups": duplicate_groups[:10],
        }

    def _workflow_lines(self, payload, fields):
        lines = []
        for key, label in fields.items():
            value = payload.get(key)
            if value:
                lines.append(f"- {label}: {value}")
        return lines

    def _is_task_payload(self, memory_type, tags, payload):
        return "task" in memory_type or "task" in tags or any(key in payload for key in self.TASK_FIELDS)

    def _is_project_payload(self, memory_type, tags, payload):
        return "project" in memory_type or "project" in tags or any(key in payload for key in self.PROJECT_FIELDS)

    def _tags(self, values):
        if isinstance(values, str):
            values = [item.strip() for item in values.split(",")]
        return self._add_tags([], values or [])

    def _add_tags(self, tags, values):
        seen = {tag.lower(): tag for tag in tags if tag}
        for value in values:
            tag = self._tag_value(value)
            if tag and tag.lower() not in seen:
                seen[tag.lower()] = tag
        return list(seen.values())

    def _tag_value(self, value):
        return str(value or "").strip().lower().replace(" ", "-").replace("_", "-")[:64]
