"""Allow manual shared-portfolio backtest batches.

Revision ID: 0033_bt03_portfolio
Revises: 0032_bt02a_intraday
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0033_bt03_portfolio"
down_revision: str | None = "0032_bt02a_intraday"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "backtest_batch_scope_valid", "backtest_batches", type_="check"
    )
    op.create_check_constraint(
        "backtest_batch_scope_valid",
        "backtest_batches",
        "scope IN ('MANUAL', 'WATCHLIST', 'ALL_A_SHARES')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "backtest_batch_scope_valid", "backtest_batches", type_="check"
    )
    op.create_check_constraint(
        "backtest_batch_scope_valid",
        "backtest_batches",
        "scope IN ('WATCHLIST', 'ALL_A_SHARES')",
    )
