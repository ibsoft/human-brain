from pathlib import Path

from flask import current_app

from app.extensions import db
from app.models import (
    Agent,
    ApiKey,
    AuditLog,
    ConsolidationJob,
    Memory,
    MemoryAccessLog,
    MemoryAsset,
    MemoryCorrelation,
    MemoryEmbedding,
    MemoryVector,
    Session,
    SessionMessage,
    VisionEvent,
    Workspace,
    WorkspaceAgent,
)
from app.services.audit_service import AuditService
from app.services.embedding_service import EmbeddingService
from app.services.faiss_service import FaissService


class AdminService:
    @staticmethod
    def create_workspace(name, description="", local_first_privacy=True):
        workspace = Workspace(
            name=name.strip(),
            description=description.strip(),
            local_first_privacy=local_first_privacy,
        )
        db.session.add(workspace)
        db.session.commit()
        AuditService.log("workspace.created", "user", None, workspace.id, "workspace", workspace.id)
        db.session.commit()
        return workspace

    @staticmethod
    def create_agent(name, description="", workspace_ids=None, permissions=None):
        agent = Agent(
            name=name.strip(),
            description=description.strip(),
            permissions=permissions or {"memory": "rw", "context": "read"},
        )
        db.session.add(agent)
        db.session.flush()
        for workspace_id in workspace_ids or []:
            db.session.add(
                WorkspaceAgent(
                    workspace_id=int(workspace_id),
                    agent_id=agent.id,
                    permissions=permissions or {"memory": "rw", "context": "read"},
                )
            )
        db.session.commit()
        AuditService.log("agent.created", "user", None, None, "agent", agent.id)
        db.session.commit()
        return agent

    @staticmethod
    def create_api_key(agent_id, name):
        raw, prefix, key_hash = ApiKey.create_token()
        key = ApiKey(agent_id=agent_id, name=name.strip(), prefix=prefix, key_hash=key_hash)
        db.session.add(key)
        db.session.commit()
        AuditService.log("api_key.created", "user", None, None, "api_key", key.id)
        db.session.commit()
        return raw, key

    @staticmethod
    def rotate_api_key(key_id):
        key = db.session.get(ApiKey, key_id)
        raw, prefix, key_hash = ApiKey.create_token()
        key.prefix = prefix
        key.key_hash = key_hash
        key.active = True
        from datetime import datetime

        key.rotated_at = datetime.utcnow()
        db.session.commit()
        AuditService.log("api_key.rotated", "user", None, None, "api_key", key.id)
        db.session.commit()
        return raw, key

    @staticmethod
    def revoke_api_key(key_id):
        key = db.session.get(ApiKey, key_id)
        key.active = False
        db.session.commit()
        AuditService.log("api_key.revoked", "user", None, None, "api_key", key.id)
        db.session.commit()
        return key

    @staticmethod
    def delete_api_key(key_id):
        key = db.session.get(ApiKey, key_id)
        if key:
            db.session.delete(key)
            db.session.commit()
        return key

    @staticmethod
    def delete_memory(memory_id):
        memory = db.session.get(Memory, memory_id)
        if not memory:
            return None
        MemoryAccessLog.query.filter_by(memory_id=memory.id).delete()
        MemoryAsset.query.filter_by(memory_id=memory.id).delete()
        MemoryCorrelation.query.filter(
            (MemoryCorrelation.source_memory_id == memory.id) | (MemoryCorrelation.target_memory_id == memory.id)
        ).delete(synchronize_session=False)
        MemoryEmbedding.query.filter_by(memory_id=memory.id).delete()
        MemoryVector.query.filter_by(memory_id=memory.id).delete()
        VisionEvent.query.filter_by(saved_as_memory_id=memory.id).update({"saved_as_memory_id": None})
        workspace_id = memory.workspace_id
        db.session.delete(memory)
        db.session.commit()
        FaissService(current_app.config["FAISS_INDEX_DIR"]).rebuild(workspace_id, EmbeddingService(current_app.config["EMBEDDING_MODEL"]))
        return memory

    @staticmethod
    def delete_session(session_id):
        session = db.session.get(Session, session_id)
        if not session:
            return None
        Memory.query.filter_by(session_id=session.id).update({"session_id": None})
        Memory.query.filter_by(source_session_id=session.id).update({"source_session_id": None})
        ConsolidationJob.query.filter_by(session_id=session.id).delete()
        SessionMessage.query.filter_by(session_id=session.id).delete()
        db.session.delete(session)
        db.session.commit()
        return session

    @staticmethod
    def delete_agent(agent_id):
        agent = db.session.get(Agent, agent_id)
        if not agent:
            return None
        for memory in Memory.query.filter_by(agent_id=agent.id).all():
            AdminService.delete_memory(memory.id)
        VisionEvent.query.filter_by(agent_id=agent.id).delete()
        for session in Session.query.filter_by(agent_id=agent.id).all():
            AdminService.delete_session(session.id)
        ConsolidationJob.query.filter_by(agent_id=agent.id).delete()
        WorkspaceAgent.query.filter_by(agent_id=agent.id).delete()
        ApiKey.query.filter_by(agent_id=agent.id).delete()
        db.session.delete(agent)
        db.session.commit()
        return agent

    @staticmethod
    def delete_workspace(workspace_id):
        workspace = db.session.get(Workspace, workspace_id)
        if not workspace:
            return None
        for memory in Memory.query.filter_by(workspace_id=workspace.id).all():
            AdminService.delete_memory(memory.id)
        for session in Session.query.filter_by(workspace_id=workspace.id).all():
            AdminService.delete_session(session.id)
        VisionEvent.query.filter_by(workspace_id=workspace.id).delete()
        ConsolidationJob.query.filter_by(workspace_id=workspace.id).delete()
        WorkspaceAgent.query.filter_by(workspace_id=workspace.id).delete()
        AuditLog.query.filter_by(workspace_id=workspace.id).delete()
        db.session.delete(workspace)
        db.session.commit()
        return workspace

    @staticmethod
    def delete_audit_log(log_id):
        log = db.session.get(AuditLog, log_id)
        if log:
            db.session.delete(log)
            db.session.commit()
        return log

    @staticmethod
    def duplicate_groups(workspace_id=None):
        query = Memory.query.filter(Memory.deleted_at.is_(None))
        if workspace_id:
            query = query.filter_by(workspace_id=workspace_id)
        memories = query.all()
        groups = {}
        for memory in memories:
            groups.setdefault(("hash", memory.workspace_id, memory.content_hash), []).append(memory)
            signature = AdminService._memory_signature(memory)
            if signature:
                groups.setdefault(("similar", memory.workspace_id, signature), []).append(memory)
        seen = set()
        result = []
        for key, items in groups.items():
            ids = tuple(sorted(memory.id for memory in items))
            if len(items) > 1 and ids not in seen:
                seen.add(ids)
                result.append({"reason": key[0], "memories": items})
        return result

    @staticmethod
    def _memory_signature(memory):
        words = [
            word.strip(".,:;!?()[]{}").lower()
            for word in f"{memory.title} {memory.content}".split()
            if len(word) > 4
        ]
        stop = {"memory", "project", "sample", "stored", "uploaded", "document", "image"}
        unique = sorted({word for word in words if word not in stop})
        return " ".join(unique[:8])

    @staticmethod
    def health():
        workspace = Workspace.query.first()
        faiss_status = {"status": "no_workspace", "count": 0}
        if workspace:
            faiss_status = FaissService(current_app.config["FAISS_INDEX_DIR"]).status(workspace.id)
        db_uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        return {
            "database": "ready",
            "database_engine": "sqlite" if db_uri.startswith("sqlite") else "postgresql",
            "faiss": faiss_status,
            "memories": Memory.query.count(),
            "agents": Agent.query.count(),
            "workspaces": Workspace.query.count(),
            "index_dir": str(Path(current_app.config["FAISS_INDEX_DIR"])),
        }

    @staticmethod
    def rebuild_workspace_indexes():
        service = FaissService(current_app.config["FAISS_INDEX_DIR"])
        embeddings = EmbeddingService(current_app.config["EMBEDDING_MODEL"])
        return [service.rebuild(workspace.id, embeddings) for workspace in Workspace.query.all()]
