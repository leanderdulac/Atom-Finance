"""sentiment snapshots for the market thermometer

Revision ID: c3a91f0e7b12
Revises: f8b98626115a
Create Date: 2026-11-13

Historical series of the directional sentiment signal (score, intensity,
momentum, price). Used to measure hit-rate vs future returns — the weight
does not rise without this evidence.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3a91f0e7b12"
down_revision: str | Sequence[str] | None = "f8b98626115a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sentiment_snapshots",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("intensity", sa.Float(), nullable=False),
        sa.Column("momentum", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("price_divergence", sa.Float(), nullable=True),
        sa.Column("n_mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("holding_days", sa.Integer(), nullable=False, server_default="21"),
        sa.Column("headlines", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index(
        "sentiment_snapshots_ticker_horizon",
        "sentiment_snapshots",
        ["ticker", "horizon", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("sentiment_snapshots_ticker_horizon", table_name="sentiment_snapshots")
    op.drop_table("sentiment_snapshots")
