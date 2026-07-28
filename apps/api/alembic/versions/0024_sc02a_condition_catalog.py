"""Add SC02-A screening specification and execution audit fields.

Revision ID: 0024_sc02a
Revises: 0023_ux02b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_sc02a"
down_revision: str | None = "0023_ux02b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_scan_runs_scan_run_status_valid"), "scan_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_status_valid"),
        "scan_runs",
        "status IN ('CREATED','QUEUED','RESOLVING','CHECKING_DATA','BACKFILLING',"
        "'RUNNING','COMPLETED','PARTIAL','PARTIAL_FAILED','FAILED','CANCELED')",
    )
    op.drop_constraint(
        op.f("ck_scan_run_members_scan_run_member_status_valid"),
        "scan_run_members",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_scan_run_members_scan_run_member_status_valid"),
        "scan_run_members",
        "status IN ('INCLUDED','EXCLUDED','DATA_MISSING','BACKFILL_REQUESTED',"
        "'READY','SCANNED','MATCHED','INDETERMINATE','FAILED')",
    )
    op.add_column(
        "scan_runs",
        sa.Column(
            "screening_spec",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "scan_runs",
        sa.Column(
            "execution_stats",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    for name in (
        "indeterminate_count",
        "elapsed_ms",
        "batch_count",
        "query_count",
        "bars_read",
    ):
        op.add_column(
            "scan_runs",
            sa.Column(name, sa.Integer(), server_default="0", nullable=False),
        )
    op.drop_constraint(
        op.f("ck_scan_runs_scan_run_progress_counters_valid"),
        "scan_runs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_progress_counters_valid"),
        "scan_runs",
        "total_instruments >= 0 AND excluded_instruments >= 0 "
        "AND data_ready_instruments >= 0 AND backfill_requested >= 0 "
        "AND backfill_failed >= 0 AND insufficient_history >= 0 "
        "AND indeterminate_count >= 0 AND failed_instruments >= 0 "
        "AND elapsed_ms >= 0 AND batch_count >= 0 AND query_count >= 0 "
        "AND bars_read >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_scan_runs_scan_run_progress_counters_valid"),
        "scan_runs",
        type_="check",
    )
    for name in (
        "bars_read",
        "query_count",
        "batch_count",
        "elapsed_ms",
        "indeterminate_count",
        "execution_stats",
        "screening_spec",
    ):
        op.drop_column("scan_runs", name)
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_progress_counters_valid"),
        "scan_runs",
        "total_instruments >= 0 AND excluded_instruments >= 0 "
        "AND data_ready_instruments >= 0 AND backfill_requested >= 0 "
        "AND backfill_failed >= 0 AND insufficient_history >= 0 "
        "AND failed_instruments >= 0",
    )
    op.drop_constraint(
        op.f("ck_scan_run_members_scan_run_member_status_valid"),
        "scan_run_members",
        type_="check",
    )
    op.execute("UPDATE scan_run_members SET status = 'FAILED' WHERE status = 'INDETERMINATE'")
    op.create_check_constraint(
        op.f("ck_scan_run_members_scan_run_member_status_valid"),
        "scan_run_members",
        "status IN ('INCLUDED','EXCLUDED','DATA_MISSING','BACKFILL_REQUESTED',"
        "'READY','SCANNED','MATCHED','FAILED')",
    )
    op.drop_constraint(op.f("ck_scan_runs_scan_run_status_valid"), "scan_runs", type_="check")
    op.execute("UPDATE scan_runs SET status = 'PARTIAL' WHERE status = 'PARTIAL_FAILED'")
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_status_valid"),
        "scan_runs",
        "status IN ('CREATED','QUEUED','RESOLVING','CHECKING_DATA','BACKFILLING',"
        "'RUNNING','COMPLETED','PARTIAL','FAILED','CANCELED')",
    )
