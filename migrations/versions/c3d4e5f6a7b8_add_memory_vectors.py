"""add memory vectors

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-30 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_vectors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("vector_id", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("vector_dim", sa.Integer(), nullable=False),
        sa.Column("embedding_hash", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("faiss_index_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("memory_id"),
        sa.UniqueConstraint("vector_id"),
    )
    op.create_index(op.f("ix_memory_vectors_agent_id"), "memory_vectors", ["agent_id"], unique=False)
    op.create_index(op.f("ix_memory_vectors_content_hash"), "memory_vectors", ["content_hash"], unique=False)
    op.create_index(op.f("ix_memory_vectors_embedding_hash"), "memory_vectors", ["embedding_hash"], unique=False)
    op.create_index(op.f("ix_memory_vectors_embedding_model"), "memory_vectors", ["embedding_model"], unique=False)
    op.create_index(op.f("ix_memory_vectors_faiss_index_name"), "memory_vectors", ["faiss_index_name"], unique=False)
    op.create_index(op.f("ix_memory_vectors_memory_id"), "memory_vectors", ["memory_id"], unique=False)
    op.create_index(op.f("ix_memory_vectors_vector_id"), "memory_vectors", ["vector_id"], unique=False)
    op.create_index(op.f("ix_memory_vectors_workspace_id"), "memory_vectors", ["workspace_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_memory_vectors_workspace_id"), table_name="memory_vectors")
    op.drop_index(op.f("ix_memory_vectors_vector_id"), table_name="memory_vectors")
    op.drop_index(op.f("ix_memory_vectors_memory_id"), table_name="memory_vectors")
    op.drop_index(op.f("ix_memory_vectors_faiss_index_name"), table_name="memory_vectors")
    op.drop_index(op.f("ix_memory_vectors_embedding_model"), table_name="memory_vectors")
    op.drop_index(op.f("ix_memory_vectors_embedding_hash"), table_name="memory_vectors")
    op.drop_index(op.f("ix_memory_vectors_content_hash"), table_name="memory_vectors")
    op.drop_index(op.f("ix_memory_vectors_agent_id"), table_name="memory_vectors")
    op.drop_table("memory_vectors")
