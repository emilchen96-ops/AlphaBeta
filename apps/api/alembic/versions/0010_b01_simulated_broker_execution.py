"""B01-B simulated execution attempts, Fill links and local consumption.

Revision ID: 0010_b01
Revises: 0009_r01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_b01"
down_revision: str | None = "0009_r01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_order_commands_command_status_valid"), "order_commands", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_order_commands_command_status_valid"),
        "order_commands",
        "status IN ('CREATED','PENDING','QUEUED','ACKNOWLEDGED','CONSUMED','EXPIRED','FAILED')",
    )
    op.add_column(
        "order_commands", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("order_commands", sa.Column("consumed_by", sa.String(64), nullable=True))
    op.create_check_constraint(
        op.f("ck_order_commands_consumption_pair"),
        "order_commands",
        "(consumed_at IS NULL) = (consumed_by IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_order_commands_consumed_status_matches_fields"),
        "order_commands",
        "(status = 'CONSUMED') = (consumed_at IS NOT NULL)",
    )

    op.drop_constraint(
        op.f("ck_outbox_messages_outbox_status_valid"), "outbox_messages", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_outbox_messages_outbox_status_valid"),
        "outbox_messages",
        "status IN ('PENDING','PUBLISHED','SUPPRESSED','FAILED')",
    )
    op.add_column(
        "outbox_messages", sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("outbox_messages", sa.Column("suppression_reason", sa.String(64), nullable=True))
    op.create_check_constraint(
        op.f("ck_outbox_messages_suppression_pair"),
        "outbox_messages",
        "(suppressed_at IS NULL) = (suppression_reason IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_outbox_messages_suppressed_status_matches_fields"),
        "outbox_messages",
        "(status = 'SUPPRESSED') = (suppressed_at IS NOT NULL)",
    )

    op.create_table(
        "broker_execution_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("broker_key", sa.String(64), nullable=False),
        sa.Column("broker_version", sa.String(32), nullable=False),
        sa.Column("execution_mode", sa.String(16), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("input_order_status", sa.String(32), nullable=False),
        sa.Column("result_status", sa.String(32), nullable=False),
        sa.Column("requested_quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("previously_filled_quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("attempted_quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("filled_quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("average_fill_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("rejection_code", sa.String(128), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("market_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("account_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("fee_model_version", sa.String(64), nullable=False),
        sa.Column("slippage_model_version", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "execution_mode = 'SIMULATED'",
            name=op.f("ck_broker_execution_attempts_execution_mode_valid"),
        ),
        sa.CheckConstraint(
            "result_status IN ('FILLED','PARTIALLY_FILLED','REJECTED','EXPIRED','NO_FILL')",
            name=op.f("ck_broker_execution_attempts_result_status_valid"),
        ),
        sa.CheckConstraint(
            "input_order_status IN ('CREATED','RISK_CHECKING','RISK_REJECTED',"
            "'WAITING_CONFIRMATION','QUEUED','DISPATCHED','EXECUTOR_ACCEPTED',"
            "'EXECUTOR_REJECTED','BROKER_SUBMITTED','BROKER_ACCEPTED','PARTIALLY_FILLED',"
            "'FILLED','CANCEL_PENDING','CANCELLED','EXPIRED','FAILED',"
            "'RECONCILIATION_REQUIRED')",
            name=op.f("ck_broker_execution_attempts_input_order_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name=op.f("ck_broker_execution_attempts_attempt_number_positive"),
        ),
        sa.CheckConstraint(
            "requested_quantity > 0 AND previously_filled_quantity >= 0 "
            "AND attempted_quantity > 0 AND filled_quantity >= 0 "
            "AND remaining_quantity >= 0",
            name=op.f("ck_broker_execution_attempts_quantities_non_negative"),
        ),
        sa.CheckConstraint(
            "previously_filled_quantity + attempted_quantity = requested_quantity",
            name=op.f("ck_broker_execution_attempts_attempted_quantity_balances"),
        ),
        sa.CheckConstraint(
            "previously_filled_quantity + filled_quantity + remaining_quantity "
            "= requested_quantity",
            name=op.f("ck_broker_execution_attempts_result_quantities_balance"),
        ),
        sa.CheckConstraint(
            "filled_quantity <= attempted_quantity",
            name=op.f("ck_broker_execution_attempts_filled_within_attempted"),
        ),
        sa.CheckConstraint(
            "(filled_quantity = 0 AND average_fill_price IS NULL) OR "
            "(filled_quantity > 0 AND average_fill_price > 0)",
            name=op.f("ck_broker_execution_attempts_average_price_matches_fill"),
        ),
        sa.CheckConstraint(
            "completed_at >= started_at",
            name=op.f("ck_broker_execution_attempts_completion_after_start"),
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name=op.f("ck_broker_execution_attempts_fingerprint_length"),
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["command_id"], ["order_commands.command_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["trading_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_broker_execution_attempts_idempotency"),
        sa.UniqueConstraint(
            "order_id", "attempt_number", name="uq_broker_execution_attempts_order_attempt"
        ),
        sa.UniqueConstraint(
            "command_id", "attempt_number", name="uq_broker_execution_attempts_command_attempt"
        ),
    )
    op.create_index(
        "ix_broker_execution_attempts_command",
        "broker_execution_attempts",
        ["command_id"],
    )
    op.create_index(
        "ix_broker_execution_attempts_account_created",
        "broker_execution_attempts",
        ["account_id", "created_at"],
    )
    op.create_index(
        "ix_broker_execution_attempts_result_created",
        "broker_execution_attempts",
        ["result_status", "created_at"],
    )
    op.create_index(
        "ix_broker_execution_attempts_correlation",
        "broker_execution_attempts",
        ["correlation_id"],
    )

    op.add_column("fills", sa.Column("execution_attempt_id", sa.Uuid(), nullable=True))
    op.add_column("fills", sa.Column("command_id", sa.Uuid(), nullable=True))
    op.add_column("fills", sa.Column("sequence_number", sa.Integer(), nullable=True))
    op.add_column("fills", sa.Column("execution_reference", sa.String(160), nullable=True))
    op.create_foreign_key(
        op.f("fk_fills_execution_attempt_id_broker_execution_attempts"),
        "fills",
        "broker_execution_attempts",
        ["execution_attempt_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_fills_command_id_order_commands"),
        "fills",
        "order_commands",
        ["command_id"],
        ["command_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_fills_sequence_number_positive"),
        "fills",
        "sequence_number IS NULL OR sequence_number >= 1",
    )
    op.create_check_constraint(
        op.f("ck_fills_execution_link_fields_complete"),
        "fills",
        "(execution_attempt_id IS NULL AND command_id IS NULL "
        "AND sequence_number IS NULL AND execution_reference IS NULL) OR "
        "(execution_attempt_id IS NOT NULL AND command_id IS NOT NULL "
        "AND sequence_number IS NOT NULL AND execution_reference IS NOT NULL)",
    )
    op.create_unique_constraint(
        "uq_fills_execution_attempt_sequence",
        "fills",
        ["execution_attempt_id", "sequence_number"],
    )
    op.create_unique_constraint("uq_fills_execution_reference", "fills", ["execution_reference"])


def downgrade() -> None:
    op.drop_constraint("uq_fills_execution_reference", "fills", type_="unique")
    op.drop_constraint("uq_fills_execution_attempt_sequence", "fills", type_="unique")
    op.drop_constraint(op.f("ck_fills_execution_link_fields_complete"), "fills", type_="check")
    op.drop_constraint(op.f("ck_fills_sequence_number_positive"), "fills", type_="check")
    op.drop_constraint(op.f("fk_fills_command_id_order_commands"), "fills", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_fills_execution_attempt_id_broker_execution_attempts"),
        "fills",
        type_="foreignkey",
    )
    for name in (
        "execution_reference",
        "sequence_number",
        "command_id",
        "execution_attempt_id",
    ):
        op.drop_column("fills", name)

    op.drop_index(
        "ix_broker_execution_attempts_correlation",
        table_name="broker_execution_attempts",
    )
    op.drop_index(
        "ix_broker_execution_attempts_result_created",
        table_name="broker_execution_attempts",
    )
    op.drop_index(
        "ix_broker_execution_attempts_account_created",
        table_name="broker_execution_attempts",
    )
    op.drop_index("ix_broker_execution_attempts_command", table_name="broker_execution_attempts")
    op.drop_table("broker_execution_attempts")

    op.drop_constraint(
        op.f("ck_outbox_messages_suppressed_status_matches_fields"),
        "outbox_messages",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_outbox_messages_suppression_pair"), "outbox_messages", type_="check"
    )
    op.execute(
        "UPDATE outbox_messages SET status='PENDING', "
        "suppressed_at=NULL, suppression_reason=NULL WHERE status='SUPPRESSED'"
    )
    op.drop_column("outbox_messages", "suppression_reason")
    op.drop_column("outbox_messages", "suppressed_at")
    op.drop_constraint(
        op.f("ck_outbox_messages_outbox_status_valid"), "outbox_messages", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_outbox_messages_outbox_status_valid"),
        "outbox_messages",
        "status IN ('PENDING','PUBLISHED','FAILED')",
    )

    op.drop_constraint(
        op.f("ck_order_commands_consumed_status_matches_fields"),
        "order_commands",
        type_="check",
    )
    op.drop_constraint(op.f("ck_order_commands_consumption_pair"), "order_commands", type_="check")
    op.execute(
        "UPDATE order_commands SET status='ACKNOWLEDGED', "
        "consumed_at=NULL, consumed_by=NULL WHERE status='CONSUMED'"
    )
    op.drop_column("order_commands", "consumed_by")
    op.drop_column("order_commands", "consumed_at")
    op.drop_constraint(
        op.f("ck_order_commands_command_status_valid"), "order_commands", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_order_commands_command_status_valid"),
        "order_commands",
        "status IN ('CREATED','PENDING','QUEUED','ACKNOWLEDGED','EXPIRED','FAILED')",
    )
