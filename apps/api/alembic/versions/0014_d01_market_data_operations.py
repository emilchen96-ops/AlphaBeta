"""D01 daily market-data quality runs and append-only issues.

Revision ID: 0014_d01
Revises: 0013_a01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_d01"
down_revision: str | None = "0013_a01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.create_table(
        "market_data_quality_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("universe_key", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("timeframe", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("instruments_checked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("bars_checked", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("issues_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("warning_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("info_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "status IN ('CREATED','RUNNING','COMPLETED','FAILED')",
            name=op.f("ck_market_data_quality_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "timeframe IN ('MINUTE_1','MINUTE_5','MINUTE_15','MINUTE_30','MINUTE_60',"
            "'DAY_1','WEEK_1','MONTH_1')",
            name=op.f("ck_market_data_quality_runs_timeframe_valid"),
        ),
        sa.CheckConstraint(
            "instruments_checked >= 0 AND bars_checked >= 0 AND issues_found >= 0 "
            "AND error_count >= 0 AND warning_count >= 0 AND info_count >= 0",
            name=op.f("ck_market_data_quality_runs_counters_non_negative"),
        ),
        sa.CheckConstraint(
            "issues_found = error_count + warning_count + info_count",
            name=op.f("ck_market_data_quality_runs_severity_counts_match"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name=op.f("ck_market_data_quality_runs_completion_not_early"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_data_quality_runs")),
    )
    op.create_index(
        "ix_market_data_quality_runs_status_created",
        "market_data_quality_runs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_market_data_quality_runs_universe_created",
        "market_data_quality_runs",
        ["universe_key", "created_at"],
    )
    op.create_index(
        "ix_market_data_quality_runs_correlation",
        "market_data_quality_runs",
        ["correlation_id"],
    )
    op.create_table(
        "market_data_quality_issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quality_run_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=True),
        sa.Column("issue_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("timeframe", sa.String(32), nullable=False),
        sa.Column("first_affected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_affected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_value", sa.String(512), nullable=True),
        sa.Column("expected_value", sa.String(512), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("required_action", sa.String(512), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "severity IN ('ERROR','WARNING','INFO')",
            name=op.f("ck_market_data_quality_issues_severity_valid"),
        ),
        sa.CheckConstraint(
            "timeframe IN ('MINUTE_1','MINUTE_5','MINUTE_15','MINUTE_30','MINUTE_60',"
            "'DAY_1','WEEK_1','MONTH_1')",
            name=op.f("ck_market_data_quality_issues_timeframe_valid"),
        ),
        sa.CheckConstraint(
            "length(trim(issue_type)) > 0",
            name=op.f("ck_market_data_quality_issues_issue_type_non_empty"),
        ),
        sa.CheckConstraint(
            "length(trim(message)) > 0",
            name=op.f("ck_market_data_quality_issues_message_non_empty"),
        ),
        sa.CheckConstraint(
            "last_affected_at IS NULL OR first_affected_at IS NULL "
            "OR last_affected_at >= first_affected_at",
            name=op.f("ck_market_data_quality_issues_affected_range_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["quality_run_id"],
            ["market_data_quality_runs.id"],
            name=op.f("fk_market_data_quality_issues_quality_run_id_market_data_quality_runs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_market_data_quality_issues_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_data_quality_issues")),
    )
    op.create_index(
        "ix_market_data_quality_issues_run",
        "market_data_quality_issues",
        ["quality_run_id", "created_at"],
    )
    op.create_index(
        "ix_market_data_quality_issues_severity_created",
        "market_data_quality_issues",
        ["severity", "created_at"],
    )
    op.create_index(
        "ix_market_data_quality_issues_instrument_type",
        "market_data_quality_issues",
        ["instrument_id", "issue_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_data_quality_issues_instrument_type",
        table_name="market_data_quality_issues",
    )
    op.drop_index(
        "ix_market_data_quality_issues_severity_created",
        table_name="market_data_quality_issues",
    )
    op.drop_index("ix_market_data_quality_issues_run", table_name="market_data_quality_issues")
    op.drop_table("market_data_quality_issues")
    op.drop_index("ix_market_data_quality_runs_correlation", table_name="market_data_quality_runs")
    op.drop_index(
        "ix_market_data_quality_runs_universe_created",
        table_name="market_data_quality_runs",
    )
    op.drop_index(
        "ix_market_data_quality_runs_status_created", table_name="market_data_quality_runs"
    )
    op.drop_table("market_data_quality_runs")
