"""add user mfa fields

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("mfa_secret", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("mfa_enabled_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("mfa_enabled", server_default=None)


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("mfa_enabled_at")
        batch_op.drop_column("mfa_secret")
        batch_op.drop_column("mfa_enabled")
