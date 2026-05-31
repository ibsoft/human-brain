from datetime import datetime

from app.extensions import db
from app.models import Memory, Workspace
from app.services.memory_service import MemoryService


class DuplicateConsolidationService:
    def consolidate(self, workspace_id=None, archive_duplicates=True, min_group_size=2):
        from app.services.admin_service import AdminService

        groups = AdminService.duplicate_groups(workspace_id=workspace_id)
        created = []
        for group in groups:
            memories = [memory for memory in group["memories"] if memory.deleted_at is None and not memory.archived]
            if len(memories) < int(min_group_size):
                continue
            primary = memories[0]
            summary = self._summary(memories)
            consolidated, duplicate = MemoryService().add_memory(
                {
                    "agent_id": primary.agent_id,
                    "workspace_id": primary.workspace_id,
                    "title": f"Consolidated duplicate memory: {primary.title[:180]}",
                    "content": summary,
                    "summary": summary[:300],
                    "memory_type": primary.memory_type,
                    "tags": sorted({tag for memory in memories for tag in (memory.tags or [])} | {"consolidated", "duplicates"}),
                    "importance_score": max(memory.importance_score for memory in memories),
                    "trust_score": min(1.0, max(memory.trust_score for memory in memories) + 0.05),
                    "sensitivity_level": max((memory.sensitivity_level for memory in memories), key=lambda value: {"normal": 0, "high": 1, "secret": 2}.get(value, 0)),
                    "confirmed": all(memory.confirmed for memory in memories),
                    "source": "duplicate_consolidation",
                    "storage_reason": f"Consolidated {len(memories)} duplicate/similar memories.",
                },
                actor_type="worker",
            )
            if archive_duplicates:
                for memory in memories:
                    memory.archived = True
                    memory.updated_at = datetime.utcnow()
            db.session.commit()
            created.append({"memory_id": consolidated.id, "duplicate": duplicate, "merged_ids": [memory.id for memory in memories]})
        return created

    def run_for_all_workspaces(self, archive_duplicates=True, min_group_size=2):
        result = {}
        for workspace in Workspace.query.order_by(Workspace.id.asc()).all():
            result[str(workspace.id)] = self.consolidate(workspace.id, archive_duplicates=archive_duplicates, min_group_size=min_group_size)
        return result

    def _summary(self, memories):
        lines = ["Consolidated duplicate/similar memories:"]
        for memory in memories:
            lines.append(f"- #{memory.id} {memory.title}: {memory.content[:1200]}")
        return "\n".join(lines)
