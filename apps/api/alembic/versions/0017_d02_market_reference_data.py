"""D02 A-share calendar, adjustments, suspensions and lifecycle facts.

Revision ID: 0017_d02
Revises: 0016_rt01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_d02"
down_revision: str | None = "0016_rt01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.add_column("instruments", sa.Column("listed_at", sa.Date(), nullable=True))
    op.add_column("instruments", sa.Column("delisted_at", sa.Date(), nullable=True))
    op.create_check_constraint(
        op.f("ck_instruments_lifecycle_dates_valid"),
        "instruments",
        "delisted_at IS NULL OR listed_at IS NULL OR delisted_at >= listed_at",
    )

    for table, column in (
        ("strategy_runs", "price_adjustment_mode"),
        ("scan_runs", "price_adjustment_mode"),
        ("backtest_runs", "strategy_price_adjustment_mode"),
        ("replay_runs", "strategy_price_adjustment_mode"),
    ):
        op.add_column(
            table,
            sa.Column(column, sa.String(8), nullable=False, server_default="RAW"),
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_{column}_valid"), table, f"{column} IN ('RAW','QFQ')"
        )

    op.create_table(
        "trading_calendar_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exchange", sa.String(8), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("previous_open_date", sa.Date(), nullable=True),
        sa.Column("next_open_date", sa.Date(), nullable=True),
        sa.Column("session_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint("exchange IN ('SHSE','SZSE')", name=op.f("ck_trading_calendar_sessions_calendar_exchange_valid")),
        sa.CheckConstraint(
            "session_type IN ('NORMAL','HOLIDAY','WEEKEND','SPECIAL_CLOSED','UNKNOWN')",
            name=op.f("ck_trading_calendar_sessions_calendar_session_type_valid"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exchange", "session_date", name="uq_calendar_exchange_date"),
    )
    op.create_index(
        "ix_calendar_exchange_open_date",
        "trading_calendar_sessions",
        ["exchange", "is_open", "session_date"],
    )

    op.create_table(
        "adjustment_factors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("factor", sa.Numeric(28, 12), nullable=False),
        sa.Column("factor_convention", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint("factor > 0", name=op.f("ck_adjustment_factors_adjustment_factor_positive")),
        sa.CheckConstraint(
            "factor_convention IN ('NONE','TUSHARE_CUMULATIVE')",
            name=op.f("ck_adjustment_factors_adjustment_factor_convention_valid"),
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id", "trade_date", "source", "factor_convention",
            name="uq_adjustment_factor_business_key",
        ),
    )
    op.create_index(
        "ix_adjustment_instrument_date", "adjustment_factors", ["instrument_id", "trade_date"]
    )

    op.create_table(
        "instrument_trading_statuses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("suspension_type", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint(
            "status IN ('TRADING','SUSPENDED','RESUMED','UNKNOWN')",
            name=op.f("ck_instrument_trading_statuses_instrument_trading_status_valid"),
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id", "session_date", "source", name="uq_trading_status_business_key"
        ),
    )
    op.create_index(
        "ix_trading_status_instrument_date",
        "instrument_trading_statuses",
        ["instrument_id", "session_date"],
    )

    op.create_table(
        "instrument_lifecycle_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint(
            "event_type IN ('LISTED','DELISTED','SUSPENDED_LONG_TERM','RESUMED','STATUS_CHANGED')",
            name=op.f("ck_instrument_lifecycle_events_instrument_lifecycle_type_valid"),
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instrument_id", "event_date", "event_type", "source", name="uq_lifecycle_event"
        ),
    )
    op.create_index(
        "ix_lifecycle_instrument_date",
        "instrument_lifecycle_events",
        ["instrument_id", "event_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_lifecycle_instrument_date", table_name="instrument_lifecycle_events")
    op.drop_table("instrument_lifecycle_events")
    op.drop_index("ix_trading_status_instrument_date", table_name="instrument_trading_statuses")
    op.drop_table("instrument_trading_statuses")
    op.drop_index("ix_adjustment_instrument_date", table_name="adjustment_factors")
    op.drop_table("adjustment_factors")
    op.drop_index("ix_calendar_exchange_open_date", table_name="trading_calendar_sessions")
    op.drop_table("trading_calendar_sessions")
    for table, column in reversed(
        (
            ("strategy_runs", "price_adjustment_mode"),
            ("scan_runs", "price_adjustment_mode"),
            ("backtest_runs", "strategy_price_adjustment_mode"),
            ("replay_runs", "strategy_price_adjustment_mode"),
        )
    ):
        op.drop_constraint(op.f(f"ck_{table}_{column}_valid"), table, type_="check")
        op.drop_column(table, column)
    op.drop_constraint(op.f("ck_instruments_lifecycle_dates_valid"), "instruments", type_="check")
    op.drop_column("instruments", "delisted_at")
    op.drop_column("instruments", "listed_at")
