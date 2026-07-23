"""L2.5-A MiniQMT read-only market-data subscriptions.

Revision ID: 0019_l25a
Revises: 0018_d03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_l25a"
down_revision: str | None = "0018_d03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "watchlists",
        sa.Column("realtime_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "market_subscription_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column(
            "source_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("desired_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.CheckConstraint("desired_count >= 0", name="desired_count_non_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", name="uq_market_subscription_sets_version"),
    )
    op.create_index(
        "ix_market_subscription_sets_created",
        "market_subscription_sets",
        ["created_at"],
    )
    op.create_table(
        "market_subscription_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subscription_set_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_reason", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("desired_status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["subscription_set_id"], ["market_subscription_sets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscription_set_id",
            "instrument_id",
            name="uq_market_subscription_items_set_instrument",
        ),
    )
    op.create_index(
        "ix_market_subscription_items_instrument",
        "market_subscription_items",
        ["instrument_id"],
    )
    op.create_table(
        "market_active_subscriptions",
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_symbol", sa.String(length=32), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_market_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.String(length=512), nullable=True),
        sa.Column("is_test_data", sa.Boolean(), server_default=sa.false(), nullable=False),
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
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("instrument_id"),
    )
    op.create_index(
        "ix_market_active_subscriptions_status",
        "market_active_subscriptions",
        ["status"],
    )
    op.create_table(
        "market_subscription_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subscription_set_id", sa.Uuid(), nullable=False),
        sa.Column("operation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("desired_count", sa.Integer(), nullable=False),
        sa.Column("attempted_subscribe_count", sa.Integer(), nullable=False),
        sa.Column("subscribed_count", sa.Integer(), nullable=False),
        sa.Column("attempted_unsubscribe_count", sa.Integer(), nullable=False),
        sa.Column("unsubscribed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_summary", sa.String(length=1000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "desired_count >= 0 AND attempted_subscribe_count >= 0 "
            "AND subscribed_count >= 0 AND attempted_unsubscribe_count >= 0 "
            "AND unsubscribed_count >= 0 AND failed_count >= 0",
            name="market_subscription_sync_counts_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_set_id"], ["market_subscription_sets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscription_set_id",
            "operation_fingerprint",
            name="uq_market_subscription_sync_runs_operation",
        ),
    )
    op.create_index(
        "ix_market_subscription_sync_runs_started",
        "market_subscription_sync_runs",
        ["started_at"],
    )
    op.create_index(
        "ix_market_subscription_sync_runs_correlation",
        "market_subscription_sync_runs",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_table("market_subscription_sync_runs")
    op.drop_table("market_active_subscriptions")
    op.drop_table("market_subscription_items")
    op.drop_table("market_subscription_sets")
    op.drop_column("watchlists", "realtime_enabled")
