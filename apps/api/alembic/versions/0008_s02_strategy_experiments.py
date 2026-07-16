"""S02-B1 strategy experiments and child run associations.

Revision ID: 0008_s02
Revises: 0007_s01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_s02"
down_revision: str | None = "0007_s01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.create_table(
        "strategy_experiments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("strategy_key", sa.String(64), nullable=False),
        sa.Column("strategy_version", sa.String(32), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(32), nullable=False),
        sa.Column("instrument_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parameter_grid", postgresql.JSONB(), nullable=False),
        sa.Column("combination_count", sa.Integer(), nullable=False),
        sa.Column("runs_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("runs_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_signals", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "status IN ('CREATED','RUNNING','COMPLETED','PARTIAL_FAILED','FAILED')",
            name=op.f("ck_strategy_experiments_strategy_experiment_status_valid"),
        ),
        sa.CheckConstraint(
            "environment = 'RESEARCH'",
            name=op.f("ck_strategy_experiments_strategy_experiment_environment_research"),
        ),
        sa.CheckConstraint(
            "timeframe IN ('MINUTE_1','MINUTE_5','MINUTE_15','MINUTE_30','MINUTE_60','DAY_1','WEEK_1','MONTH_1')",
            name=op.f("ck_strategy_experiments_strategy_experiment_timeframe_valid"),
        ),
        sa.CheckConstraint(
            "start_at < end_at",
            name=op.f("ck_strategy_experiments_strategy_experiment_time_window"),
        ),
        sa.CheckConstraint(
            "combination_count > 0",
            name=op.f("ck_strategy_experiments_strategy_experiment_combination_positive"),
        ),
        sa.CheckConstraint(
            "runs_completed >= 0 AND runs_failed >= 0 AND total_signals >= 0",
            name=op.f("ck_strategy_experiments_strategy_experiment_counters_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_experiments")),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_strategy_experiments_idempotency_key")
        ),
    )
    op.create_index(
        "ix_strategy_experiments_strategy_created",
        "strategy_experiments",
        ["strategy_key", "created_at"],
    )
    op.create_index(
        "ix_strategy_experiments_status_created",
        "strategy_experiments",
        ["status", "created_at"],
    )

    op.create_table(
        "strategy_experiment_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_run_id", sa.Uuid(), nullable=False),
        sa.Column("combination_index", sa.Integer(), nullable=False),
        sa.Column("normalized_parameters", postgresql.JSONB(), nullable=False),
        sa.Column("child_idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "combination_index >= 1",
            name=op.f("ck_strategy_experiment_runs_strategy_experiment_run_index_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["strategy_experiments.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["strategy_run_id"], ["strategy_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_experiment_runs")),
        sa.UniqueConstraint(
            "experiment_id",
            "combination_index",
            name=op.f("uq_strategy_experiment_runs_experiment_index"),
        ),
        sa.UniqueConstraint(
            "strategy_run_id", name=op.f("uq_strategy_experiment_runs_strategy_run")
        ),
        sa.UniqueConstraint(
            "child_idempotency_key",
            name=op.f("uq_strategy_experiment_runs_child_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_strategy_experiment_runs_experiment_index",
        "strategy_experiment_runs",
        ["experiment_id", "combination_index"],
    )
    op.create_index(
        "ix_strategy_experiment_runs_strategy_run",
        "strategy_experiment_runs",
        ["strategy_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_experiment_runs_strategy_run", table_name="strategy_experiment_runs")
    op.drop_index(
        "ix_strategy_experiment_runs_experiment_index", table_name="strategy_experiment_runs"
    )
    op.drop_table("strategy_experiment_runs")
    op.drop_index("ix_strategy_experiments_status_created", table_name="strategy_experiments")
    op.drop_index("ix_strategy_experiments_strategy_created", table_name="strategy_experiments")
    op.drop_table("strategy_experiments")
