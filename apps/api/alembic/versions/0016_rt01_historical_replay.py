"""RT01 controllable historical daily replay facts.

Revision ID: 0016_rt01
Revises: 0015_bt01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_rt01"
down_revision: str | None = "0015_bt01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_NOW = sa.text("timezone('utc', now())")
AMOUNT = sa.Numeric(24, 8)
RATIO = sa.Numeric(12, 8)


def upgrade() -> None:
    op.create_table(
        "replay_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("strategy_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_session_date", sa.Date(), nullable=True),
        sa.Column("current_session_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_sessions", sa.Integer(), nullable=False),
        sa.Column("speed_mode", sa.String(16), nullable=False),
        sa.Column("bars_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("signals_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("orders_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fills_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "final_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "integrity_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint(
            "status IN ('CREATED','READY','RUNNING','PAUSED','COMPLETED','STOPPED','FAILED')",
            name=op.f("ck_replay_runs_replay_run_status_valid"),
        ),
        sa.CheckConstraint(
            "speed_mode IN ('MANUAL','X1','X10','X100')",
            name=op.f("ck_replay_runs_replay_speed_valid"),
        ),
        sa.CheckConstraint(
            "row_version >= 0 AND total_sessions > 0 AND current_session_index >= 0 "
            "AND current_session_index <= total_sessions AND bars_processed >= 0 "
            "AND signals_generated >= 0 AND orders_created >= 0 AND fills_generated >= 0",
            name=op.f("ck_replay_runs_replay_run_counters_valid"),
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name=op.f("ck_replay_runs_replay_fingerprint_length"),
        ),
        sa.ForeignKeyConstraint(["account_id"], ["trading_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["strategy_run_id"], ["strategy_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_replay_runs_idempotency_key"),
        sa.UniqueConstraint("account_id", name="uq_replay_runs_account"),
        sa.UniqueConstraint("strategy_run_id", name="uq_replay_runs_strategy_run"),
    )
    op.create_index("ix_replay_runs_status_created", "replay_runs", ["status", "created_at"])
    op.create_index("ix_replay_runs_lease", "replay_runs", ["status", "lease_expires_at"])

    op.create_table(
        "replay_control_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("replay_run_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("expected_run_version", sa.Integer(), nullable=False),
        sa.Column("applied_run_version", sa.Integer(), nullable=False),
        sa.Column("requested_speed", sa.String(16), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint(
            "action_type IN ('START','PAUSE','RESUME','STEP','SET_SPEED','STOP')",
            name=op.f("ck_replay_control_actions_replay_action_type_valid"),
        ),
        sa.CheckConstraint(
            "requested_speed IS NULL OR requested_speed IN ('MANUAL','X1','X10','X100')",
            name=op.f("ck_replay_control_actions_replay_action_speed_valid"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('LOCAL_USER','SYSTEM')",
            name=op.f("ck_replay_control_actions_replay_actor_type_valid"),
        ),
        sa.CheckConstraint(
            "expected_run_version >= 0 AND applied_run_version >= 0",
            name=op.f("ck_replay_control_actions_replay_action_versions_valid"),
        ),
        sa.ForeignKeyConstraint(["replay_run_id"], ["replay_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "replay_run_id", "idempotency_key", name="uq_replay_actions_run_idempotency"
        ),
    )
    op.create_index(
        "ix_replay_actions_run_occurred", "replay_control_actions", ["replay_run_id", "occurred_at"]
    )

    op.create_table(
        "replay_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("replay_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("business_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("related_entity_type", sa.String(64), nullable=True),
        sa.Column("related_entity_id", sa.Uuid(), nullable=True),
        sa.Column("summary", sa.String(256), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint("sequence_number >= 1", name=op.f("ck_replay_events_sequence_positive")),
        sa.ForeignKeyConstraint(["replay_run_id"], ["replay_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "replay_run_id", "sequence_number", name="uq_replay_events_run_sequence"
        ),
    )
    op.create_index(
        "ix_replay_events_run_sequence", "replay_events", ["replay_run_id", "sequence_number"]
    )
    op.create_index("ix_replay_events_type", "replay_events", ["replay_run_id", "event_type"])

    op.create_table(
        "replay_equity_points",
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint(
            "cash >= 0 AND market_value >= 0 AND total_equity = cash + market_value "
            "AND gross_exposure >= 0 AND drawdown <= 0 AND positions_count >= 0",
            name=op.f("ck_replay_equity_points_values_valid"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["replay_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "timestamp", name="uq_replay_equity_run_timestamp"),
    )
    op.create_index(
        "ix_replay_equity_run_timestamp", "replay_equity_points", ["run_id", "timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_replay_equity_run_timestamp", table_name="replay_equity_points")
    op.drop_table("replay_equity_points")
    op.drop_index("ix_replay_events_type", table_name="replay_events")
    op.drop_index("ix_replay_events_run_sequence", table_name="replay_events")
    op.drop_table("replay_events")
    op.drop_index("ix_replay_actions_run_occurred", table_name="replay_control_actions")
    op.drop_table("replay_control_actions")
    op.drop_index("ix_replay_runs_lease", table_name="replay_runs")
    op.drop_index("ix_replay_runs_status_created", table_name="replay_runs")
    op.drop_table("replay_runs")
