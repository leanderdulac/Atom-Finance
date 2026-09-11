"""initial schema: users and reports

Revision ID: 7c1b289837ff
Revises:
Create Date: 2026-09-11 00:49:57.794401

Ports the SQLite schema from app/db/database.py to Postgres-native types:
  - INTEGER PRIMARY KEY AUTOINCREMENT -> BIGSERIAL
  - TEXT timestamps                   -> TIMESTAMPTZ
  - INTEGER 0/1 (is_active)           -> BOOLEAN
  - full_report TEXT (JSON string)    -> JSONB (queryable, indexable)
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7c1b289837ff'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="analyst"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_users_username", "users", ["username"])

    op.create_table(
        "reports",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("bull_score", sa.Float(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("full_report", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("owner", sa.Text(), nullable=True),
    )
    op.create_index("idx_reports_ticker", "reports", ["ticker"])
    op.create_index("idx_reports_created_at", "reports", ["created_at"])
    op.create_index("idx_reports_owner", "reports", ["owner", "created_at"])


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("users")
