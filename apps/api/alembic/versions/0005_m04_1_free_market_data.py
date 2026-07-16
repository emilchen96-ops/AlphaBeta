"""m04.1 free market data worker and provider capabilities

Revision ID: 0005_m04_1
Revises: 0004_m04
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_m04_1"
down_revision: str | None = "0004_m04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("timezone('utc', now())")
JSON_OBJECT = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.add_column(
        "market_data_sources",
        sa.Column("provider_tier", sa.String(32), nullable=False, server_default="DEMO"),
    )
    op.add_column(
        "market_data_sources",
        sa.Column("supports_quotes", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "market_data_sources",
        sa.Column(
            "supports_recent_minute_bars",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "market_data_sources",
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_market_data_sources_provider_tier_valid"),
        "market_data_sources",
        "provider_tier IN ('DEMO', 'FREE_BEST_EFFORT')",
    )
    op.create_table(
        "market_realtime_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.String(1000), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_OBJECT,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','PARTIALLY_SUCCEEDED','FAILED',"
            "'SKIPPED_NOT_LEADER','DISABLED')",
            name=op.f("ck_market_realtime_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "requested_count >= 0 AND received_count >= 0 AND changed_count >= 0 "
            "AND rejected_count >= 0",
            name=op.f("ck_market_realtime_runs_counters_non_negative"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name=op.f("ck_market_realtime_runs_completion_not_early"),
        ),
        sa.CheckConstraint(
            "error_summary IS NULL OR length(error_summary) <= 1000",
            name=op.f("ck_market_realtime_runs_error_summary_length"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["market_data_sources.id"],
            name=op.f("fk_market_realtime_runs_source_id_market_data_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_realtime_runs")),
    )
    op.create_index(
        "ix_market_realtime_runs_source_started",
        "market_realtime_runs",
        ["source_id", "started_at"],
    )
    op.create_index(
        "ix_market_realtime_runs_status_started",
        "market_realtime_runs",
        ["status", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_market_realtime_runs_status_started", table_name="market_realtime_runs")
    op.drop_index("ix_market_realtime_runs_source_started", table_name="market_realtime_runs")
    op.drop_table("market_realtime_runs")
    op.drop_constraint(
        op.f("ck_market_data_sources_provider_tier_valid"),
        "market_data_sources",
        type_="check",
    )
    op.drop_column("market_data_sources", "last_health_check_at")
    op.drop_column("market_data_sources", "supports_recent_minute_bars")
    op.drop_column("market_data_sources", "supports_quotes")
    op.drop_column("market_data_sources", "provider_tier")
