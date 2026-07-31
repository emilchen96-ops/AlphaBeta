"""Add durable independent backtest batch orchestration.

Revision ID: 0029_bt_batches
Revises: 0028_bt01exec
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0029_bt_batches"
down_revision: str | None = "0028_bt01exec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("watchlist_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("pending_count", sa.Integer(), nullable=False),
        sa.Column("running_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("cancelled_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scope IN ('WATCHLIST', 'ALL_A_SHARES')",
            name="backtest_batch_scope_valid",
        ),
        sa.CheckConstraint(
            "status IN ('CREATED', 'RUNNING', 'COMPLETED', 'PARTIAL_FAILED', "
            "'FAILED', 'CANCELLED')",
            name="backtest_batch_status_valid",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name="backtest_batch_fingerprint_length",
        ),
        sa.CheckConstraint(
            "total_count > 0 AND pending_count >= 0 AND running_count >= 0 "
            "AND completed_count >= 0 AND failed_count >= 0 AND cancelled_count >= 0 "
            "AND pending_count + running_count + completed_count + failed_count "
            "+ cancelled_count = total_count",
            name="backtest_batch_counters_valid",
        ),
        sa.CheckConstraint(
            "(scope <> 'WATCHLIST') OR watchlist_id IS NOT NULL",
            name="backtest_batch_watchlist_required",
        ),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_backtest_batches_idempotency_key"),
    )
    op.create_index(
        "ix_backtest_batches_status_created",
        "backtest_batches",
        ["status", "created_at"],
    )
    op.create_table(
        "backtest_batch_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("backtest_run_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="backtest_batch_item_status_valid",
        ),
        sa.CheckConstraint(
            "ordinal >= 0 AND attempt_count >= 0",
            name="backtest_batch_item_counters_valid",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["backtest_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "instrument_id",
            name="uq_backtest_batch_items_batch_instrument",
        ),
        sa.UniqueConstraint("backtest_run_id", name="uq_backtest_batch_items_run"),
    )
    op.create_index(
        "ix_backtest_batch_items_claim",
        "backtest_batch_items",
        ["status", "updated_at", "ordinal"],
    )
    op.create_index(
        "ix_backtest_batch_items_batch_ordinal",
        "backtest_batch_items",
        ["batch_id", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_backtest_batch_items_batch_ordinal",
        table_name="backtest_batch_items",
    )
    op.drop_index(
        "ix_backtest_batch_items_claim",
        table_name="backtest_batch_items",
    )
    op.drop_table("backtest_batch_items")
    op.drop_index(
        "ix_backtest_batches_status_created",
        table_name="backtest_batches",
    )
    op.drop_table("backtest_batches")
