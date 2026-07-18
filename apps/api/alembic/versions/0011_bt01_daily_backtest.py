"""BT01 deterministic A-share daily backtest facts.

Revision ID: 0011_bt01
Revises: 0010_b01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_bt01"
down_revision: str | None = "0010_b01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_NOW = sa.text("timezone('utc', now())")
AMOUNT = sa.Numeric(24, 8)
PRICE = sa.Numeric(20, 8)
QUANTITY = sa.Numeric(24, 8)
RATIO = sa.Numeric(12, 8)


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("strategy_run_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("bars_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sessions_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("signals_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risk_passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risk_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("risk_reviewed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orders_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fills_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "status IN ('CREATED','RUNNING','COMPLETED','FAILED')",
            name=op.f("ck_backtest_runs_backtest_run_status_valid"),
        ),
        sa.CheckConstraint(
            "bars_processed >= 0 AND sessions_processed >= 0 AND signals_generated >= 0 "
            "AND risk_passed >= 0 AND risk_rejected >= 0 AND risk_reviewed >= 0 "
            "AND orders_created >= 0 AND fills_generated >= 0",
            name=op.f("ck_backtest_runs_backtest_run_counters_non_negative"),
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name=op.f("ck_backtest_runs_backtest_fingerprint_length"),
        ),
        sa.ForeignKeyConstraint(["strategy_run_id"], ["strategy_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["trading_accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_backtest_runs_idempotency_key"),
        sa.UniqueConstraint("strategy_run_id", name="uq_backtest_runs_strategy_run"),
        sa.UniqueConstraint("account_id", name="uq_backtest_runs_account"),
    )
    op.create_index("ix_backtest_runs_status_created", "backtest_runs", ["status", "created_at"])

    op.create_table(
        "backtest_equity_points",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash", AMOUNT, nullable=False),
        sa.Column("market_value", AMOUNT, nullable=False),
        sa.Column("total_equity", AMOUNT, nullable=False),
        sa.Column("gross_exposure", AMOUNT, nullable=False),
        sa.Column("net_exposure", AMOUNT, nullable=False),
        sa.Column("daily_return", RATIO, nullable=True),
        sa.Column("cumulative_return", RATIO, nullable=False),
        sa.Column("drawdown", RATIO, nullable=False),
        sa.Column("positions_count", sa.Integer(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "positions_count >= 0",
            name=op.f("ck_backtest_equity_points_backtest_equity_positions_non_negative"),
        ),
        sa.CheckConstraint(
            "cash >= 0 AND market_value >= 0 AND gross_exposure >= 0",
            name=op.f("ck_backtest_equity_points_backtest_equity_values_non_negative"),
        ),
        sa.CheckConstraint(
            "total_equity = cash + market_value",
            name=op.f("ck_backtest_equity_points_backtest_equity_total_balances"),
        ),
        sa.CheckConstraint(
            "drawdown <= 0",
            name=op.f("ck_backtest_equity_points_backtest_equity_drawdown_non_positive"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "timestamp", name="uq_backtest_equity_run_timestamp"),
    )
    op.create_index(
        "ix_backtest_equity_run_timestamp",
        "backtest_equity_points",
        ["run_id", "timestamp"],
    )

    op.create_table(
        "backtest_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("initial_equity", AMOUNT, nullable=False),
        sa.Column("final_equity", AMOUNT, nullable=False),
        sa.Column("total_return", RATIO, nullable=False),
        sa.Column("annualized_return", RATIO, nullable=True),
        sa.Column("maximum_drawdown", RATIO, nullable=False),
        sa.Column("annualized_volatility", RATIO, nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(24, 12), nullable=True),
        sa.Column("trading_sessions", sa.Integer(), nullable=False),
        sa.Column("fill_count", sa.Integer(), nullable=False),
        sa.Column("buy_fill_count", sa.Integer(), nullable=False),
        sa.Column("sell_fill_count", sa.Integer(), nullable=False),
        sa.Column("total_turnover", AMOUNT, nullable=False),
        sa.Column("total_commission", AMOUNT, nullable=False),
        sa.Column("total_stamp_duty", AMOUNT, nullable=False),
        sa.Column("total_transfer_fee", AMOUNT, nullable=False),
        sa.Column("total_other_fee", AMOUNT, nullable=False),
        sa.Column("total_fees", AMOUNT, nullable=False),
        sa.Column("realized_pnl", AMOUNT, nullable=False),
        sa.Column("win_rate", RATIO, nullable=True),
        sa.Column("loss_rate", RATIO, nullable=True),
        sa.Column("profit_factor", sa.Numeric(24, 12), nullable=True),
        sa.Column("average_win", AMOUNT, nullable=True),
        sa.Column("average_loss", AMOUNT, nullable=True),
        sa.Column("average_exposure", RATIO, nullable=False),
        sa.Column("maximum_exposure", RATIO, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "trading_sessions > 0 AND fill_count >= 0 AND buy_fill_count >= 0 "
            "AND sell_fill_count >= 0 AND buy_fill_count + sell_fill_count = fill_count",
            name=op.f("ck_backtest_metrics_backtest_metric_counts_valid"),
        ),
        sa.CheckConstraint(
            "initial_equity > 0 AND final_equity >= 0 AND total_turnover >= 0 "
            "AND total_commission >= 0 AND total_stamp_duty >= 0 "
            "AND total_transfer_fee >= 0 AND total_other_fee >= 0 AND total_fees >= 0",
            name=op.f("ck_backtest_metrics_backtest_metric_amounts_valid"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_backtest_metrics_run"),
    )

    op.create_table(
        "backtest_trade_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", QUANTITY, nullable=False),
        sa.Column("entry_price", PRICE, nullable=False),
        sa.Column("exit_price", PRICE, nullable=False),
        sa.Column("gross_pnl", AMOUNT, nullable=False),
        sa.Column("fees", AMOUNT, nullable=False),
        sa.Column("net_pnl", AMOUNT, nullable=False),
        sa.CheckConstraint(
            "quantity > 0 AND entry_price > 0 AND exit_price > 0 AND fees >= 0",
            name=op.f("ck_backtest_trade_summaries_backtest_trade_values_valid"),
        ),
        sa.CheckConstraint(
            "closed_at >= opened_at",
            name=op.f("ck_backtest_trade_summaries_backtest_trade_time_valid"),
        ),
        sa.CheckConstraint(
            "net_pnl = gross_pnl - fees",
            name=op.f("ck_backtest_trade_summaries_backtest_trade_pnl_balances"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_backtest_trades_run_closed", "backtest_trade_summaries", ["run_id", "closed_at"]
    )

    op.create_table(
        "backtest_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(256), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('RUN_CREATED','RUN_STARTED','SESSION_OPEN','SESSION_CLOSE',"
            "'SESSION_END','SIGNAL_GENERATED','RISK_DECIDED','ORDER_CREATED',"
            "'EXECUTION_ATTEMPTED','FILL_GENERATED','WARNING','RUN_COMPLETED','RUN_FAILED')",
            name=op.f("ck_backtest_events_backtest_event_type_valid"),
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name=op.f("ck_backtest_events_backtest_event_sequence_positive"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence_number", name="uq_backtest_events_run_sequence"),
    )
    op.create_index(
        "ix_backtest_events_run_sequence", "backtest_events", ["run_id", "sequence_number"]
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_events_run_sequence", table_name="backtest_events")
    op.drop_table("backtest_events")
    op.drop_index("ix_backtest_trades_run_closed", table_name="backtest_trade_summaries")
    op.drop_table("backtest_trade_summaries")
    op.drop_table("backtest_metrics")
    op.drop_index("ix_backtest_equity_run_timestamp", table_name="backtest_equity_points")
    op.drop_table("backtest_equity_points")
    op.drop_index("ix_backtest_runs_status_created", table_name="backtest_runs")
    op.drop_table("backtest_runs")
