import secrets
import uuid
from datetime import datetime

from app.extensions import db


class Memory(db.Model):
    __tablename__ = "memories"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=False, index=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), index=True)
    source_session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), index=True)
    title = db.Column(db.String(240), nullable=False)
    content = db.Column(db.Text, nullable=False)
    summary = db.Column(db.Text)
    memory_type = db.Column(db.String(64), nullable=False, index=True)
    tags = db.Column(db.JSON, nullable=False, default=list)
    importance_score = db.Column(db.Float, nullable=False, default=0.5)
    trust_score = db.Column(db.Float, nullable=False, default=0.5)
    sensitivity_level = db.Column(db.String(32), nullable=False, default="normal", index=True)
    visibility = db.Column(db.String(32), nullable=False, default="workspace", index=True)
    embedding_hash = db.Column(db.String(64), index=True)
    content_hash = db.Column(db.String(64), nullable=False, index=True)
    source = db.Column(db.String(120), nullable=False, default="api")
    created_by = db.Column(db.String(120), nullable=False, default="system")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_accessed_at = db.Column(db.DateTime)
    access_count = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.DateTime, index=True)
    archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    deleted_at = db.Column(db.DateTime, index=True)
    confirmed = db.Column(db.Boolean, nullable=False, default=False)
    pending_approval = db.Column(db.Boolean, nullable=False, default=True)
    storage_reason = db.Column(db.Text)

    __table_args__ = (
        db.Index("ix_memory_scope", "workspace_id", "agent_id", "memory_type", "archived", "deleted_at"),
        db.UniqueConstraint("workspace_id", "content_hash", name="uq_memory_workspace_content_hash"),
    )


class MemoryEmbedding(db.Model):
    __tablename__ = "memory_embeddings"

    id = db.Column(db.Integer, primary_key=True)
    memory_id = db.Column(db.Integer, db.ForeignKey("memories.id"), nullable=False, unique=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    embedding_hash = db.Column(db.String(64), nullable=False, index=True)
    vector_dim = db.Column(db.Integer, nullable=False)
    faiss_position = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MemoryVector(db.Model):
    __tablename__ = "memory_vectors"

    id = db.Column(db.Integer, primary_key=True)
    memory_id = db.Column(db.Integer, db.ForeignKey("memories.id"), nullable=False, unique=True, index=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=False, index=True)
    vector_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    embedding_model = db.Column(db.String(255), nullable=False, index=True)
    vector_dim = db.Column(db.Integer, nullable=False)
    embedding_hash = db.Column(db.String(64), nullable=False, index=True)
    content_hash = db.Column(db.String(64), nullable=False, index=True)
    faiss_index_name = db.Column(db.String(255), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class MemoryAsset(db.Model):
    __tablename__ = "memory_assets"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    public_token = db.Column(db.String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(32))
    memory_id = db.Column(db.Integer, db.ForeignKey("memories.id"), nullable=False, index=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    asset_type = db.Column(db.String(32), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.Text, nullable=False)
    content_type = db.Column(db.String(120))
    vector_hash = db.Column(db.String(64), index=True)
    vector_dim = db.Column(db.Integer)
    vector = db.Column(db.JSON)
    asset_metadata = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MemoryAccessLog(db.Model):
    __tablename__ = "memory_access_logs"

    id = db.Column(db.Integer, primary_key=True)
    memory_id = db.Column(db.Integer, db.ForeignKey("memories.id"), nullable=False, index=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), index=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    purpose = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class MemoryCorrelation(db.Model):
    __tablename__ = "memory_correlations"

    id = db.Column(db.Integer, primary_key=True)
    workspace_id = db.Column(db.Integer, db.ForeignKey("workspaces.id"), nullable=False, index=True)
    source_memory_id = db.Column(db.Integer, db.ForeignKey("memories.id"), nullable=False, index=True)
    target_memory_id = db.Column(db.Integer, db.ForeignKey("memories.id"), nullable=False, index=True)
    correlation_type = db.Column(db.String(64), nullable=False, default="related", index=True)
    strength = db.Column(db.Float, nullable=False, default=0.5)
    explanation = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("source_memory_id", "target_memory_id", "correlation_type", name="uq_memory_correlation"),
    )
