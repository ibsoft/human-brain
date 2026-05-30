"""add asset public tokens

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-30 00:00:02.000000

"""
import secrets
import uuid

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("memory_assets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("uuid", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("public_token", sa.String(length=64), nullable=True))

    connection = op.get_bind()
    assets = connection.execute(sa.text("SELECT id FROM memory_assets")).fetchall()
    for asset in assets:
        connection.execute(
            sa.text("UPDATE memory_assets SET uuid = :uuid, public_token = :token WHERE id = :id"),
            {"uuid": str(uuid.uuid4()), "token": secrets.token_urlsafe(32), "id": asset.id},
        )

    with op.batch_alter_table("memory_assets", schema=None) as batch_op:
        batch_op.alter_column("uuid", existing_type=sa.String(length=36), nullable=False)
        batch_op.alter_column("public_token", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_unique_constraint("uq_memory_assets_uuid", ["uuid"])
        batch_op.create_unique_constraint("uq_memory_assets_public_token", ["public_token"])


def downgrade():
    with op.batch_alter_table("memory_assets", schema=None) as batch_op:
        batch_op.drop_constraint("uq_memory_assets_public_token", type_="unique")
        batch_op.drop_constraint("uq_memory_assets_uuid", type_="unique")
        batch_op.drop_column("public_token")
        batch_op.drop_column("uuid")
