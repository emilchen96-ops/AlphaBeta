"""S01-B historical strategy runs and persisted signal provenance.

Revision ID: 0007_s01
Revises: 0006_m05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_s01"
down_revision: str | None = "0006_m05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_OBJECT = sa.text("'{}'::jsonb")
UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.create_table(
        "strategy_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=True),
        sa.Column("strategy_key", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("strategy_version_id", sa.Uuid(), nullable=True),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(32), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("instrument_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("bars_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("signals_generated", sa.Integer(), server_default="0", nullable=False),
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
            name=op.f("ck_strategy_runs_strategy_run_status_valid"),
        ),
        sa.CheckConstraint(
            "environment IN ('RESEARCH','BACKTEST','REPLAY','PAPER','LIVE')",
            name=op.f("ck_strategy_runs_strategy_run_environment_valid"),
        ),
        sa.CheckConstraint(
            "timeframe IN ('MINUTE_1','MINUTE_5','MINUTE_15','MINUTE_30','MINUTE_60','DAY_1','WEEK_1','MONTH_1')",
            name=op.f("ck_strategy_runs_run_timeframe_valid"),
        ),
        sa.CheckConstraint(
            "start_at < end_at", name=op.f("ck_strategy_runs_strategy_run_time_window")
        ),
        sa.CheckConstraint(
            "bars_processed >= 0 AND signals_generated >= 0",
            name=op.f("ck_strategy_runs_strategy_run_counters_non_negative"),
        ),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"], ["strategy_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_runs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_strategy_runs_idempotency_key")),
    )
    op.create_index("ix_strategy_runs_status_created", "strategy_runs", ["status", "created_at"])
    op.create_index(
        "ix_strategy_runs_strategy_created", "strategy_runs", ["strategy_key", "created_at"]
    )

    op.alter_column("signals", "strategy_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("signals", "strategy_version_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("signals", "account_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("signals", sa.Column("strategy_run_id", sa.Uuid(), nullable=True))
    op.add_column("signals", sa.Column("sequence_number", sa.Integer(), nullable=True))
    op.add_column("signals", sa.Column("strategy_key", sa.String(64), nullable=True))
    op.add_column("signals", sa.Column("strategy_version", sa.String(32), nullable=True))
    op.add_column("signals", sa.Column("bar_timestamp", sa.DateTime(timezone=True), nullable=True))
    op.add_column("signals", sa.Column("confidence", sa.Numeric(12, 8), nullable=True))
    op.add_column(
        "signals",
        sa.Column("metadata", postgresql.JSONB(), server_default=JSON_OBJECT, nullable=False),
    )
    op.add_column(
        "signals", sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_foreign_key(
        op.f("fk_signals_strategy_run_id_strategy_runs"),
        "signals",
        "strategy_runs",
        ["strategy_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        op.f("uq_signals_run_sequence"), "signals", ["strategy_run_id", "sequence_number"]
    )
    op.create_check_constraint(
        op.f("ck_signals_signal_target_mutually_exclusive"),
        "signals",
        "target_quantity IS NULL OR target_weight IS NULL",
    )
    op.create_check_constraint(
        op.f("ck_signals_signal_confidence_range"),
        "signals",
        "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
    )
    op.create_check_constraint(
        op.f("ck_signals_signal_sequence_positive"),
        "signals",
        "sequence_number IS NULL OR sequence_number >= 1",
    )
    op.create_check_constraint(
        op.f("ck_signals_signal_schema_version_positive"), "signals", "schema_version >= 1"
    )
    op.create_index("ix_signals_strategy_run_id", "signals", ["strategy_run_id"])


def downgrade() -> None:
    op.execute("DELETE FROM signals WHERE strategy_run_id IS NOT NULL")
    op.drop_index("ix_signals_strategy_run_id", table_name="signals")
    op.drop_constraint(op.f("ck_signals_signal_schema_version_positive"), "signals", type_="check")
    op.drop_constraint(op.f("ck_signals_signal_sequence_positive"), "signals", type_="check")
    op.drop_constraint(op.f("ck_signals_signal_confidence_range"), "signals", type_="check")
    op.drop_constraint(
        op.f("ck_signals_signal_target_mutually_exclusive"), "signals", type_="check"
    )
    op.drop_constraint(op.f("uq_signals_run_sequence"), "signals", type_="unique")
    op.drop_constraint(
        op.f("fk_signals_strategy_run_id_strategy_runs"), "signals", type_="foreignkey"
    )
    for column in (
        "schema_version",
        "metadata",
        "confidence",
        "bar_timestamp",
        "strategy_version",
        "strategy_key",
        "sequence_number",
        "strategy_run_id",
    ):
        op.drop_column("signals", column)
    op.alter_column("signals", "account_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("signals", "strategy_version_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("signals", "strategy_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index("ix_strategy_runs_strategy_created", table_name="strategy_runs")
    op.drop_index("ix_strategy_runs_status_created", table_name="strategy_runs")
    op.drop_table("strategy_runs")
