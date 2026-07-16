"""M05 manual order workflow, actions, and transactional outbox facts.

Revision ID: 0006_m05
Revises: 0005_m04_1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_m05"
down_revision: str | None = "0005_m04_1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_OBJECT = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("intent_source", sa.String(16), nullable=False, server_default="MANUAL")
    )
    op.add_column(
        "orders",
        sa.Column("request_fingerprint", sa.String(128), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "orders", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "orders",
        sa.Column("confirmation_required", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    for name in ("confirmed_at", "cancelled_at", "expired_at"):
        op.add_column("orders", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "orders",
        sa.Column(
            "created_by_actor_type", sa.String(32), nullable=False, server_default="LOCAL_USER"
        ),
    )
    op.add_column("orders", sa.Column("created_by_actor_id", sa.String(128), nullable=True))
    op.create_check_constraint("ck_orders_row_version_positive", "orders", "row_version >= 1")
    op.create_check_constraint(
        "ck_orders_intent_source",
        "orders",
        "intent_source IN ('MANUAL','STRATEGY','SCANNER','AI','SYSTEM')",
    )
    op.create_index(
        "ix_orders_account_status_created",
        "orders",
        ["account_id", "status", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_orders_instrument_created", "orders", ["instrument_id", sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_orders_intent_created", "orders", ["intent_source", sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_orders_expires_pending",
        "orders",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    op.create_index("ix_orders_request_fingerprint", "orders", ["request_fingerprint"])
    for name, column in (
        ("order_version", sa.Integer()),
        ("action_id", sa.Uuid()),
        ("command_id", sa.Uuid()),
    ):
        op.add_column(
            "order_state_transitions",
            sa.Column(
                name,
                column,
                nullable=name != "order_version",
                server_default="1" if name == "order_version" else None,
            ),
        )
    op.create_check_constraint(
        "ck_order_state_transitions_version_positive",
        "order_state_transitions",
        "order_version >= 1",
    )
    op.create_table(
        "order_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("action_type", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(128), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128)),
        sa.Column("expected_order_version", sa.Integer(), nullable=False),
        sa.Column("applied_order_version", sa.Integer(), nullable=False),
        sa.Column("applied_transition_id", sa.BigInteger()),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(1024)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=JSON_OBJECT),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_order_actions_idempotency_key"),
        sa.CheckConstraint(
            "action_type IN ('CONFIRM','CANCEL')", name="ck_order_actions_action_type"
        ),
        sa.CheckConstraint(
            "actor_type IN ('LOCAL_USER','SYSTEM','RISK_ENGINE','EXECUTOR','BROKER','RECONCILIATION')",
            name="ck_order_actions_actor_type",
        ),
        sa.CheckConstraint(
            "expected_order_version >= 1", name="order_action_expected_version_positive"
        ),
        sa.CheckConstraint(
            "applied_order_version >= expected_order_version",
            name="order_action_applied_version_valid",
        ),
    )
    op.create_foreign_key(
        "fk_order_state_transitions_action",
        "order_state_transitions",
        "order_actions",
        ["action_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_order_actions_order_occurred", "order_actions", ["order_id", "occurred_at"])
    op.create_index("ix_order_actions_correlation", "order_actions", ["correlation_id"])
    op.create_index(
        "uq_order_commands_submit_per_order",
        "order_commands",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("command_type = 'SUBMIT_ORDER'"),
    )


def downgrade() -> None:
    op.drop_index("uq_order_commands_submit_per_order", table_name="order_commands")
    op.drop_constraint(
        "fk_order_state_transitions_action", "order_state_transitions", type_="foreignkey"
    )
    op.drop_index("ix_order_actions_correlation", table_name="order_actions")
    op.drop_index("ix_order_actions_order_occurred", table_name="order_actions")
    op.drop_table("order_actions")
    op.drop_constraint(
        "ck_order_state_transitions_version_positive",
        "order_state_transitions",
        type_="check",
    )
    for name in ("command_id", "action_id", "order_version"):
        op.drop_column("order_state_transitions", name)
    for name in (
        "ix_orders_request_fingerprint",
        "ix_orders_expires_pending",
        "ix_orders_intent_created",
        "ix_orders_instrument_created",
        "ix_orders_account_status_created",
    ):
        op.drop_index(name, table_name="orders")
    op.drop_constraint("ck_orders_intent_source", "orders", type_="check")
    op.drop_constraint("ck_orders_row_version_positive", "orders", type_="check")
    for name in (
        "created_by_actor_id",
        "created_by_actor_type",
        "expired_at",
        "cancelled_at",
        "confirmed_at",
        "confirmation_required",
        "row_version",
        "request_fingerprint",
        "intent_source",
    ):
        op.drop_column("orders", name)
