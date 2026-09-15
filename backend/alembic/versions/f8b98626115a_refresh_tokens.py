"""
refresh tokens

Revision ID: f8b98626115a
Revises: 6b9aabb24f5f
Create Date: 2026-09-15 18:17:40.401309

Refresh tokens for the HttpOnly-cookie session flow. Only the sha256 hash of
the opaque token is stored (the raw token never reaches the DB), enabling
rotation (replaced_by) and explicit revocation (revoked_at) — closing the
"no way to revoke one leaked token" gap.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f8b98626115a'
down_revision: str | Sequence[str] | None = '6b9aabb24f5f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("replaced_by_token_hash", sa.Text(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_refresh_tokens_user", "refresh_tokens", ["user_id"])
    op.create_index("idx_refresh_tokens_expires", "refresh_tokens", ["expires_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("refresh_tokens")
