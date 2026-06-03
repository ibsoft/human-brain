"""add health check runs

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-03 09:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "health_check_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("auto_repair", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("repairs", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_health_check_runs_started_at"), "health_check_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_health_check_runs_status"), "health_check_runs", ["status"], unique=False)
    op.create_index(op.f("ix_health_check_runs_severity"), "health_check_runs", ["severity"], unique=False)
    op.create_index(op.f("ix_health_check_runs_trigger"), "health_check_runs", ["trigger"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_health_check_runs_trigger"), table_name="health_check_runs")
    op.drop_index(op.f("ix_health_check_runs_severity"), table_name="health_check_runs")
    op.drop_index(op.f("ix_health_check_runs_status"), table_name="health_check_runs")
    op.drop_index(op.f("ix_health_check_runs_started_at"), table_name="health_check_runs")
    op.drop_table("health_check_runs")
