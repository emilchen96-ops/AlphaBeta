"""SC01 deterministic daily market scanners.

Revision ID: 0011_sc01
Revises: 0010_b01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_sc01"
down_revision: str | None = "0010_b01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scanner_key", sa.String(64), nullable=False),
        sa.Column("scanner_version", sa.String(32), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("universe_type", sa.String(32), nullable=False),
        sa.Column("instrument_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("timeframe", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("instruments_scanned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matches_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
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
            name=op.f("ck_scan_runs_scan_run_status_valid"),
        ),
        sa.CheckConstraint(
            "timeframe = 'DAY_1'", name=op.f("ck_scan_runs_scan_run_timeframe_daily")
        ),
        sa.CheckConstraint(
            "instruments_scanned >= 0 AND matches_found >= 0 "
            "AND matches_found <= instruments_scanned",
            name=op.f("ck_scan_runs_scan_run_counters_valid"),
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name=op.f("ck_scan_runs_scan_run_fingerprint_sha256"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_runs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_scan_runs_idempotency_key")),
    )
    op.create_index("ix_scan_runs_scanner_created", "scan_runs", ["scanner_key", "created_at"])
    op.create_index("ix_scan_runs_status_created", "scan_runs", ["status", "created_at"])
    op.create_index("ix_scan_runs_correlation", "scan_runs", ["correlation_id"])
    op.create_table(
        "scan_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_run_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(24, 8), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_scan_results_scan_result_rank_positive")),
        sa.CheckConstraint(
            "score >= 0", name=op.f("ck_scan_results_scan_result_score_non_negative")
        ),
        sa.CheckConstraint(
            "reference_price > 0",
            name=op.f("ck_scan_results_scan_result_reference_price_positive"),
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name=op.f("ck_scan_results_scan_result_schema_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_scan_results_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scan_run_id"],
            ["scan_runs.id"],
            name=op.f("fk_scan_results_scan_run_id_scan_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_results")),
        sa.UniqueConstraint(
            "scan_run_id", "instrument_id", name=op.f("uq_scan_results_run_instrument")
        ),
        sa.UniqueConstraint("scan_run_id", "rank", name=op.f("uq_scan_results_run_rank")),
    )
    op.create_index("ix_scan_results_run_rank", "scan_results", ["scan_run_id", "rank"])
    op.create_index(
        "ix_scan_results_instrument_matched",
        "scan_results",
        ["instrument_id", "matched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scan_results_instrument_matched", table_name="scan_results")
    op.drop_index("ix_scan_results_run_rank", table_name="scan_results")
    op.drop_table("scan_results")
    op.drop_index("ix_scan_runs_correlation", table_name="scan_runs")
    op.drop_index("ix_scan_runs_status_created", table_name="scan_runs")
    op.drop_index("ix_scan_runs_scanner_created", table_name="scan_runs")
    op.drop_table("scan_runs")
