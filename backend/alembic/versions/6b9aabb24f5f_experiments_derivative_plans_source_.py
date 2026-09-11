"""experiments, derivative plans, source snapshots, paper trading

Revision ID: 6b9aabb24f5f
Revises: 7c1b289837ff
Create Date: 2026-09-11 00:57:23.211058

Ports the four remaining tables, previously created ad hoc by
app/db/experiments.py and the api/{derivatives,market_sources,paper_trades}.py
route files directly. All TEXT id columns hold str(uuid4()) values and stay
TEXT (not native UUID) to keep the Python-side interface unchanged.

paper_events.seq replaces SQLite's implicit `rowid`, which Postgres has no
equivalent for; app code must order by this column instead.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6b9aabb24f5f'
down_revision: str | Sequence[str] | None = '7c1b289837ff'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Research journal ──────────────────────────────────────────────
    op.create_table(
        "experiments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("experiments_owner", "experiments", ["owner", "created_at"])

    op.create_table(
        "experiment_reviews",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("experiment_id", sa.Text(), sa.ForeignKey("experiments.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
    )
    op.create_index("experiment_reviews_experiment", "experiment_reviews", ["experiment_id", "created_at"])

    # ── Derivatives desk ──────────────────────────────────────────────
    op.create_table(
        "derivative_plans",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
    )
    op.create_index("derivative_plans_owner", "derivative_plans", ["owner", "created_at"])

    # ── Market source snapshots ───────────────────────────────────────
    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("source_snapshots_owner", "source_snapshots", ["owner", "created_at"])
    # Replaces SQLite's json_extract(payload, '$.ticker') filter with a
    # native jsonb expression index.
    op.create_index(
        "source_snapshots_ticker",
        "source_snapshots",
        [sa.text("(payload ->> 'ticker')")],
    )

    # ── Paper trading ──────────────────────────────────────────────────
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("plan_id", sa.Text(), nullable=False),
        sa.Column("plan_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("plan", postgresql.JSONB(), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("owner", "plan_id", "plan_index"),
    )
    op.create_index("paper_owner", "paper_trades", ["owner", "created_at"])

    op.create_table(
        "paper_events",
        # Replaces SQLite's implicit rowid for ordering: BIGSERIAL guarantees
        # monotonically increasing insertion order, which rowid gave for free.
        sa.Column("seq", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("id", sa.Text(), nullable=False, unique=True),
        sa.Column("trade_id", sa.Text(), sa.ForeignKey("paper_trades.id"), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("trade_id", "request_id"),
    )
    op.create_index("paper_event_trade", "paper_events", ["trade_id", "created_at"])


def downgrade() -> None:
    op.drop_table("paper_events")
    op.drop_table("paper_trades")
    op.drop_table("source_snapshots")
    op.drop_table("derivative_plans")
    op.drop_table("experiment_reviews")
    op.drop_table("experiments")
