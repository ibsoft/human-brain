"""add memory assets

Revision ID: a1b2c3d4e5f6
Revises: 9c1d2e3f4a5b
Create Date: 2026-05-30 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "9c1d2e3f4a5b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("vector_hash", sa.String(length=64), nullable=True),
        sa.Column("vector_dim", sa.Integer(), nullable=True),
        sa.Column("vector", sa.JSON(), nullable=True),
        sa.Column("asset_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("memory_assets", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_memory_assets_memory_id"), ["memory_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_assets_workspace_id"), ["workspace_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_assets_asset_type"), ["asset_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_assets_vector_hash"), ["vector_hash"], unique=False)


def downgrade():
    op.drop_table("memory_assets")
