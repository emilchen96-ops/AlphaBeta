"""Add SC02-D screening data-preparation states.

Revision ID: 0026_sc02d
Revises: 0025_sc02c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_sc02d"
down_revision: str | None = "0025_sc02c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_scan_runs_scan_run_status_valid"), "scan_runs", type_="check")
    op.alter_column(
        "scan_runs",
        "status",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_status_valid"),
        "scan_runs",
        "status IN ('CREATED','QUEUED','PLANNING','CHECKING_COVERAGE',"
        "'BACKFILLING_MARKET_DATA','BACKFILLING_REFERENCE_DATA','VERIFYING_DATA',"
        "'PREPARING_FEATURES','SCREENING','RESOLVING','CHECKING_DATA','BACKFILLING',"
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
        "status IN ('INCLUDED','EXCLUDED','DATA_MISSING','BACKFILL_REQUESTED','READY',"
        "'INSUFFICIENT_HISTORY','REFERENCE_DATA_MISSING','QUALITY_FAILED',"
        "'PROVIDER_FAILED','NOT_APPLICABLE','SCANNED','MATCHED','INDETERMINATE','FAILED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_scan_run_members_scan_run_member_status_valid"),
        "scan_run_members",
        type_="check",
    )
    op.execute(
        "UPDATE scan_run_members SET status = CASE "
        "WHEN status IN ('INSUFFICIENT_HISTORY','REFERENCE_DATA_MISSING') THEN 'DATA_MISSING' "
        "WHEN status IN ('QUALITY_FAILED','PROVIDER_FAILED','NOT_APPLICABLE') THEN 'FAILED' "
        "ELSE status END"
    )
    op.create_check_constraint(
        op.f("ck_scan_run_members_scan_run_member_status_valid"),
        "scan_run_members",
        "status IN ('INCLUDED','EXCLUDED','DATA_MISSING','BACKFILL_REQUESTED',"
        "'READY','SCANNED','MATCHED','INDETERMINATE','FAILED')",
    )
    op.drop_constraint(op.f("ck_scan_runs_scan_run_status_valid"), "scan_runs", type_="check")
    op.execute(
        "UPDATE scan_runs SET status = CASE "
        "WHEN status = 'PLANNING' THEN 'RESOLVING' "
        "WHEN status IN ('CHECKING_COVERAGE','VERIFYING_DATA','PREPARING_FEATURES') "
        "THEN 'CHECKING_DATA' "
        "WHEN status IN ('BACKFILLING_MARKET_DATA','BACKFILLING_REFERENCE_DATA') "
        "THEN 'BACKFILLING' "
        "WHEN status = 'SCREENING' THEN 'RUNNING' "
        "ELSE status END"
    )
    op.alter_column(
        "scan_runs",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_scan_runs_scan_run_status_valid"),
        "scan_runs",
        "status IN ('CREATED','QUEUED','RESOLVING','CHECKING_DATA','BACKFILLING',"
        "'RUNNING','COMPLETED','PARTIAL','PARTIAL_FAILED','FAILED','CANCELED')",
    )
