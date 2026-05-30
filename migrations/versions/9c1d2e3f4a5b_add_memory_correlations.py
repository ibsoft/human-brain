"""add memory correlations

Revision ID: 9c1d2e3f4a5b
Revises: 356403278d76
Create Date: 2026-05-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9c1d2e3f4a5b"
down_revision = "356403278d76"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_correlations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("source_memory_id", sa.Integer(), nullable=False),
        sa.Column("target_memory_id", sa.Integer(), nullable=False),
        sa.Column("correlation_type", sa.String(length=64), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_memory_id"], ["memories.id"]),
        sa.ForeignKeyConstraint(["target_memory_id"], ["memories.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_memory_id", "target_memory_id", "correlation_type", name="uq_memory_correlation"),
    )
    with op.batch_alter_table("memory_correlations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_memory_correlations_workspace_id"), ["workspace_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_correlations_source_memory_id"), ["source_memory_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_correlations_target_memory_id"), ["target_memory_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_correlations_correlation_type"), ["correlation_type"], unique=False)


def downgrade():
    op.drop_table("memory_correlations")
