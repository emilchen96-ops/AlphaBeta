"""M01 infrastructure bootstrap with no trading-domain tables.

Revision ID: 0001_m01_bootstrap
Revises:
Create Date: 2026-07-15
"""

revision: str = "0001_m01_bootstrap"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Intentionally empty: domain persistence starts in M02."""


def downgrade() -> None:
    """Intentionally empty: no M01 domain objects exist."""
