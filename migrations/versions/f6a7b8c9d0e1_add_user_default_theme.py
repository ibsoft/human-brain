"""add user default theme

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-02 22:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def _has_column(table_name, column_name):
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    if not _has_column("users", "default_theme"):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.add_column(sa.Column("default_theme", sa.String(length=16), nullable=False, server_default="dark"))
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.alter_column("default_theme", server_default=None)


def downgrade():
    if _has_column("users", "default_theme"):
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.drop_column("default_theme")
