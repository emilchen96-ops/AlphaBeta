"""Track the currently activated idempotent subscription plan.

Revision ID: 0020_l25a
Revises: 0019_l25a
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_l25a"
down_revision: str | None = "0019_l25a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "market_subscription_sets",
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_market_subscription_sets_activated",
        "market_subscription_sets",
        ["activated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_subscription_sets_activated",
        table_name="market_subscription_sets",
    )
    op.drop_column("market_subscription_sets", "activated_at")
