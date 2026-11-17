"""Operation thesis monitors and their check history.

Revision ID: c59e013daef9
Revises: c3a91f0e7b12
Create Date: 2026-11-16

A monitor is a declared paper operation (ticker, direction, levels,
horizon) plus a simulation baseline taken at declaration. Checks append
point-in-time evaluations; terminal states never change.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c59e013daef9"
down_revision: str | Sequence[str] | None = "c3a91f0e7b12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operation_monitors",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("entry", sa.Float(), nullable=False),
        sa.Column("stop", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("size", sa.Float(), nullable=False, server_default="1"),
        sa.Column("vol_annual", sa.Float(), nullable=False),
        sa.Column("baseline", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("state", sa.Text(), nullable=False, server_default="watching"),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_px", sa.Float(), nullable=True),
        sa.Column("last_spot", sa.Float(), nullable=True),
        sa.Column("last_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
    )
    op.execute("CREATE INDEX IF NOT EXISTS monitors_owner ON operation_monitors(owner, declared_at)")
    op.create_table(
        "monitor_checks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("monitor_id", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("spot", sa.Float(), nullable=False),
        sa.Column("oracle_usable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("disagreement_bps", sa.Float(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("alerts", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("metrics", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["monitor_id"], ["operation_monitors.id"], ondelete="CASCADE"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS checks_monitor ON monitor_checks(monitor_id, checked_at)")


def downgrade() -> None:
    op.drop_table("monitor_checks")
    op.drop_table("operation_monitors")
