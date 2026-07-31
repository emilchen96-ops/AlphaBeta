"""Add CAL01-R screening readiness states.

Revision ID: 0027_cal01r
Revises: 0026_sc02d
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_cal01r"
down_revision: str | None = "0026_sc02d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_scan_run_members_scan_run_member_status_valid"),
        "scan_run_members",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_scan_run_members_scan_run_member_status_valid"),
        "scan_run_members",
        "status IN ('INCLUDED','EXCLUDED','DATA_MISSING','BACKFILL_REQUESTED','READY',"
        "'CURRENTLY_SUSPENDED','STALE_DATA','DATA_GAP','CALENDAR_MISMATCH','DELISTED',"
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
        "WHEN status IN ('DATA_GAP','CALENDAR_MISMATCH') THEN 'INSUFFICIENT_HISTORY' "
        "WHEN status IN ('CURRENTLY_SUSPENDED','STALE_DATA','DELISTED') THEN 'NOT_APPLICABLE' "
        "ELSE status END"
    )
    op.create_check_constraint(
        op.f("ck_scan_run_members_scan_run_member_status_valid"),
        "scan_run_members",
        "status IN ('INCLUDED','EXCLUDED','DATA_MISSING','BACKFILL_REQUESTED','READY',"
        "'INSUFFICIENT_HISTORY','REFERENCE_DATA_MISSING','QUALITY_FAILED',"
        "'PROVIDER_FAILED','NOT_APPLICABLE','SCANNED','MATCHED','INDETERMINATE','FAILED')",
    )
