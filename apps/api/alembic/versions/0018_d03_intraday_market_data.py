"""D03 intraday market-data range indexes.

Revision ID: 0018_d03
Revises: 0017_d02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_d03"
down_revision: str | None = "0017_d02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_market_bars_timeframe_time",
        "market_bars",
        ["timeframe", "bar_time"],
    )
    op.create_index(
        "ix_market_bars_source_timeframe_time",
        "market_bars",
        ["source_id", "timeframe", "bar_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_bars_source_timeframe_time", table_name="market_bars")
    op.drop_index("ix_market_bars_timeframe_time", table_name="market_bars")
