"""Add BT02-A intraday replay audit counters and summaries.

Revision ID: 0032_bt02a_intraday
Revises: 0031_ta01_graph
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0032_bt02a_intraday"
down_revision: str | None = "0031_ta01_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column(
        "backtest_runs",
        sa.Column("candidate_session_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "backtest_runs",
        sa.Column("minute_replay_session_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "backtest_runs",
        sa.Column("processed_minute_bar_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("backtest_runs", sa.Column("skipped_reason", sa.String(length=512)))
    op.add_column(
        "backtest_runs",
        sa.Column(
            "data_preparation_summary",
            jsonb,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "backtest_runs",
        sa.Column(
            "performance_summary",
            jsonb,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "backtest_intraday_counters_non_negative",
        "backtest_runs",
        "candidate_session_count >= 0 AND minute_replay_session_count >= 0 "
        "AND processed_minute_bar_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "backtest_intraday_counters_non_negative", "backtest_runs", type_="check"
    )
    op.drop_column("backtest_runs", "performance_summary")
    op.drop_column("backtest_runs", "data_preparation_summary")
    op.drop_column("backtest_runs", "skipped_reason")
    op.drop_column("backtest_runs", "processed_minute_bar_count")
    op.drop_column("backtest_runs", "minute_replay_session_count")
    op.drop_column("backtest_runs", "candidate_session_count")
