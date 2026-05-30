from datetime import datetime

from app.extensions import db
from app.models import Memory, MemoryAccessLog


class MemoryRepository:
    def create(self, **kwargs):
        memory = Memory(**kwargs)
        db.session.add(memory)
        db.session.flush()
        return memory

    def get_visible(self, memory_id, workspace_id):
        return Memory.query.filter(
            Memory.id == memory_id,
            Memory.workspace_id == workspace_id,
            Memory.deleted_at.is_(None),
        ).first()

    def query_scope(self, workspace_id, include_archived=False):
        query = Memory.query.filter(Memory.workspace_id == workspace_id, Memory.deleted_at.is_(None))
        if not include_archived:
            query = query.filter(Memory.archived.is_(False))
        return query

    def mark_accessed(self, memory, agent_id=None, purpose="context"):
        memory.last_accessed_at = datetime.utcnow()
        memory.access_count += 1
        db.session.add(
            MemoryAccessLog(
                memory_id=memory.id,
                workspace_id=memory.workspace_id,
                agent_id=agent_id,
                purpose=purpose,
            )
        )

