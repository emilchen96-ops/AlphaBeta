"""SC01-R full-market scanner jobs and auditable universe members.

Revision ID: 0021_sc01r
Revises: 0020_l25a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_sc01r"
down_revision: str | None = "0020_l25a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.drop_constraint(op.f("ck_scan_runs_scan_run_status_valid"), "scan_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_status_valid"),
        "scan_runs",
        "status IN ('CREATED','QUEUED','RESOLVING','CHECKING_DATA','BACKFILLING',"
        "'RUNNING','COMPLETED','PARTIAL','FAILED','CANCELED')",
    )
    op.add_column(
        "scan_runs",
        sa.Column(
            "universe_filters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "scan_runs",
        sa.Column("source_code", sa.String(32), server_default="MINIQMT", nullable=False),
    )
    for name in (
        "total_instruments",
        "excluded_instruments",
        "data_ready_instruments",
        "backfill_requested",
        "backfill_failed",
        "insufficient_history",
        "failed_instruments",
        "progress_percent",
    ):
        op.add_column(
            "scan_runs",
            sa.Column(name, sa.Integer(), server_default="0", nullable=False),
        )
    op.add_column(
        "scan_runs",
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "scan_runs",
        sa.Column("backfill_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_progress_counters_valid"),
        "scan_runs",
        "total_instruments >= 0 AND excluded_instruments >= 0 "
        "AND data_ready_instruments >= 0 AND backfill_requested >= 0 "
        "AND backfill_failed >= 0 AND insufficient_history >= 0 "
        "AND failed_instruments >= 0",
    )
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_progress_percent_valid"),
        "scan_runs",
        "progress_percent >= 0 AND progress_percent <= 100",
    )
    op.create_table(
        "scan_run_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_run_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("instrument_name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(512), nullable=True),
        sa.Column("bars_available", sa.Integer(), server_default="0", nullable=False),
        sa.Column("required_bars", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "status IN ('INCLUDED','EXCLUDED','DATA_MISSING','BACKFILL_REQUESTED',"
            "'READY','SCANNED','MATCHED','FAILED')",
            name=op.f("ck_scan_run_members_scan_run_member_status_valid"),
        ),
        sa.CheckConstraint(
            "bars_available >= 0 AND required_bars >= 0",
            name=op.f("ck_scan_run_members_scan_run_member_bar_counts_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_scan_run_members_instrument_id_instruments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scan_run_id"],
            ["scan_runs.id"],
            name=op.f("fk_scan_run_members_scan_run_id_scan_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_run_members")),
        sa.UniqueConstraint(
            "scan_run_id",
            "instrument_id",
            name=op.f("uq_scan_run_members_run_instrument"),
        ),
    )
    op.create_index(
        "ix_scan_run_members_run_status",
        "scan_run_members",
        ["scan_run_id", "status"],
    )
    op.create_index(
        "ix_scan_run_members_instrument",
        "scan_run_members",
        ["instrument_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scan_run_members_instrument", table_name="scan_run_members")
    op.drop_index("ix_scan_run_members_run_status", table_name="scan_run_members")
    op.drop_table("scan_run_members")
    op.drop_constraint(
        op.f("ck_scan_runs_scan_run_progress_percent_valid"),
        "scan_runs",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_scan_runs_scan_run_progress_counters_valid"),
        "scan_runs",
        type_="check",
    )
    for name in (
        "backfill_requested_at",
        "cancel_requested",
        "progress_percent",
        "failed_instruments",
        "insufficient_history",
        "backfill_failed",
        "backfill_requested",
        "data_ready_instruments",
        "excluded_instruments",
        "total_instruments",
        "source_code",
        "universe_filters",
    ):
        op.drop_column("scan_runs", name)
    op.drop_constraint(op.f("ck_scan_runs_scan_run_status_valid"), "scan_runs", type_="check")
    op.execute(
        "UPDATE scan_runs SET status = CASE "
        "WHEN status = 'PARTIAL' THEN 'COMPLETED' "
        "WHEN status IN ('QUEUED','RESOLVING','CHECKING_DATA','BACKFILLING',"
        "'CANCELED') THEN 'FAILED' ELSE status END"
    )
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_status_valid"),
        "scan_runs",
        "status IN ('CREATED','RUNNING','COMPLETED','FAILED')",
    )
