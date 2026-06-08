"""add record versions

Revision ID: a8b9c0d1e2f3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a8b9c0d1e2f3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "record_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("table_name", sa.String(length=120), nullable=False),
        sa.Column("record_id", sa.String(length=120), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("table_name", "record_id", "version_number", name="uq_record_version_number"),
    )
    with op.batch_alter_table("record_versions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_record_versions_table_name"), ["table_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_record_versions_record_id"), ["record_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_record_versions_event"), ["event"], unique=False)
        batch_op.create_index(batch_op.f("ix_record_versions_created_at"), ["created_at"], unique=False)
        batch_op.create_index("ix_record_versions_lookup", ["table_name", "record_id", "version_number"], unique=False)


def downgrade():
    op.drop_table("record_versions")
