"""m04 simulated account ledgers and projections

Revision ID: 0004_m04
Revises: 0003_m03
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_m04"
down_revision: str | None = "0003_m03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AMOUNT = sa.Numeric(24, 8)
PRICE = sa.Numeric(20, 8)
QUANTITY = sa.Numeric(24, 8)
NOW = sa.text("timezone('utc', now())")
JSON_OBJECT = sa.text("'{}'::jsonb")


def timestamps(*, mutable: bool = False) -> list[sa.Column[object]]:
    columns: list[sa.Column[object]] = []
    if mutable:
        columns.append(
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)
        )
    columns.append(
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False)
    )
    return columns


def upgrade() -> None:
    op.add_column(
        "trading_accounts",
        sa.Column("settlement_policy", sa.String(32), server_default="IMMEDIATE", nullable=False),
    )
    op.add_column(
        "trading_accounts", sa.Column("creation_idempotency_key", sa.String(128), nullable=True)
    )
    op.create_check_constraint(
        "settlement_policy_valid",
        "trading_accounts",
        "settlement_policy IN ('IMMEDIATE', 'T_PLUS_ONE')",
    )
    op.create_unique_constraint(
        "uq_trading_accounts_creation_idempotency_key",
        "trading_accounts",
        ["creation_idempotency_key"],
    )
    op.add_column(
        "orders",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=JSON_OBJECT,
            nullable=False,
        ),
    )

    op.drop_constraint(
        op.f("ck_positions_available_frozen_within_total"), "positions", type_="check"
    )
    op.add_column(
        "positions", sa.Column("unsettled_quantity", QUANTITY, server_default="0", nullable=False)
    )
    op.add_column("positions", sa.Column("cost_basis", AMOUNT, nullable=True))
    op.add_column("positions", sa.Column("last_price", PRICE, nullable=True))
    op.add_column(
        "positions", sa.Column("last_price_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "positions",
        sa.Column("valuation_status", sa.String(32), server_default="UNAVAILABLE", nullable=False),
    )
    op.execute(
        "UPDATE positions SET unsettled_quantity = total_quantity - available_quantity - frozen_quantity, "
        "cost_basis = average_cost * total_quantity"
    )
    op.alter_column("positions", "cost_basis", existing_type=AMOUNT, nullable=False)
    op.alter_column("positions", "market_value", existing_type=AMOUNT, nullable=True)
    op.alter_column("positions", "unrealized_pnl", existing_type=AMOUNT, nullable=True)
    op.create_check_constraint(
        "quantity_components_equal_total",
        "positions",
        "available_quantity + frozen_quantity + unsettled_quantity = total_quantity",
    )
    op.create_check_constraint(
        "unsettled_quantity_non_negative", "positions", "unsettled_quantity >= 0"
    )
    op.create_check_constraint("cost_basis_non_negative", "positions", "cost_basis >= 0")
    op.create_check_constraint("average_cost_non_negative", "positions", "average_cost >= 0")
    op.create_check_constraint(
        "closed_position_cost_zero",
        "positions",
        "total_quantity <> 0 OR (cost_basis = 0 AND average_cost = 0)",
    )
    op.create_check_constraint(
        "last_price_positive", "positions", "last_price IS NULL OR last_price > 0"
    )
    op.create_check_constraint(
        "valuation_status_valid",
        "positions",
        "valuation_status IN ('COMPLETE', 'PARTIAL', 'STALE', 'UNAVAILABLE')",
    )

    op.create_table(
        "account_cash_balances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("total_cash", AMOUNT, nullable=False),
        sa.Column("available_cash", AMOUNT, nullable=False),
        sa.Column("frozen_cash", AMOUNT, nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        *timestamps(mutable=True),
        sa.CheckConstraint(
            "total_cash >= 0", name=op.f("ck_account_cash_balances_total_cash_non_negative")
        ),
        sa.CheckConstraint(
            "available_cash >= 0", name=op.f("ck_account_cash_balances_available_cash_non_negative")
        ),
        sa.CheckConstraint(
            "frozen_cash >= 0", name=op.f("ck_account_cash_balances_frozen_cash_non_negative")
        ),
        sa.CheckConstraint(
            "total_cash = available_cash + frozen_cash",
            name=op.f("ck_account_cash_balances_cash_components_equal_total"),
        ),
        sa.CheckConstraint(
            "row_version >= 1", name=op.f("ck_account_cash_balances_row_version_positive")
        ),
        sa.CheckConstraint(
            "length(trim(currency)) > 0", name=op.f("ck_account_cash_balances_currency_non_empty")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            ondelete="RESTRICT",
            name=op.f("fk_account_cash_balances_account_id_trading_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_cash_balances")),
        sa.UniqueConstraint(
            "account_id", "currency", name="uq_account_cash_balances_account_currency"
        ),
    )
    op.create_index("ix_account_cash_balances_account", "account_cash_balances", ["account_id"])

    op.create_table(
        "ledger_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("business_key", sa.String(160), nullable=False),
        sa.Column("related_order_id", sa.Uuid(), nullable=True),
        sa.Column("related_fill_id", sa.Uuid(), nullable=True),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=JSON_OBJECT,
            nullable=False,
        ),
        *timestamps(mutable=True),
        sa.CheckConstraint(
            "transaction_type IN ('INITIAL_DEPOSIT','DEPOSIT','WITHDRAWAL','BUY_FILL','SELL_FILL','CASH_ADJUSTMENT','POSITION_ADJUSTMENT','REVERSAL')",
            name=op.f("ck_ledger_transactions_transaction_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','POSTED','FAILED','REVERSED')",
            name=op.f("ck_ledger_transactions_status_valid"),
        ),
        sa.CheckConstraint(
            "posted_at IS NULL OR posted_at >= occurred_at",
            name=op.f("ck_ledger_transactions_posted_not_before_occurred"),
        ),
        sa.CheckConstraint(
            "reversal_of_id IS NULL OR reversal_of_id <> id",
            name=op.f("ck_ledger_transactions_not_self_reversal"),
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 500",
            name=op.f("ck_ledger_transactions_description_length"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            ondelete="RESTRICT",
            name=op.f("fk_ledger_transactions_account_id_trading_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["related_order_id"],
            ["orders.id"],
            ondelete="RESTRICT",
            name=op.f("fk_ledger_transactions_related_order_id_orders"),
        ),
        sa.ForeignKeyConstraint(
            ["related_fill_id"],
            ["fills.id"],
            ondelete="RESTRICT",
            name=op.f("fk_ledger_transactions_related_fill_id_fills"),
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of_id"],
            ["ledger_transactions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_ledger_transactions_reversal_of_id_ledger_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_transactions")),
        sa.UniqueConstraint("business_key", name="uq_ledger_transactions_business_key"),
    )
    op.create_index(
        "ix_ledger_transactions_account_occurred",
        "ledger_transactions",
        ["account_id", "occurred_at"],
    )
    op.create_index("ix_ledger_transactions_order", "ledger_transactions", ["related_order_id"])
    op.create_index("ix_ledger_transactions_correlation", "ledger_transactions", ["correlation_id"])
    op.create_index(
        "ix_ledger_transactions_status_created", "ledger_transactions", ["status", "created_at"]
    )
    op.create_index(
        "uq_ledger_transactions_related_fill",
        "ledger_transactions",
        ["related_fill_id"],
        unique=True,
        postgresql_where=sa.text("related_fill_id IS NOT NULL"),
    )

    op.create_table(
        "cash_ledger_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("ledger_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("total_delta", AMOUNT, nullable=False),
        sa.Column("available_delta", AMOUNT, nullable=False),
        sa.Column("frozen_delta", AMOUNT, nullable=False),
        sa.Column("gross_amount", AMOUNT, nullable=True),
        sa.Column("fee_amount", AMOUNT, nullable=True),
        sa.Column("total_cash_after", AMOUNT, nullable=False),
        sa.Column("available_cash_after", AMOUNT, nullable=False),
        sa.Column("frozen_cash_after", AMOUNT, nullable=False),
        sa.Column("related_fill_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=JSON_OBJECT,
            nullable=False,
        ),
        *timestamps(),
        sa.CheckConstraint(
            "entry_type IN ('INITIAL_DEPOSIT','DEPOSIT','WITHDRAWAL','BUY_SETTLEMENT','SELL_SETTLEMENT','COMMISSION','TAX','OTHER_FEE','FREEZE','RELEASE','ADJUSTMENT','REVERSAL')",
            name=op.f("ck_cash_ledger_entries_entry_type_valid"),
        ),
        sa.CheckConstraint(
            "total_delta = available_delta + frozen_delta",
            name=op.f("ck_cash_ledger_entries_delta_components_equal_total"),
        ),
        sa.CheckConstraint(
            "total_cash_after >= 0",
            name=op.f("ck_cash_ledger_entries_total_cash_after_non_negative"),
        ),
        sa.CheckConstraint(
            "available_cash_after >= 0",
            name=op.f("ck_cash_ledger_entries_available_cash_after_non_negative"),
        ),
        sa.CheckConstraint(
            "frozen_cash_after >= 0",
            name=op.f("ck_cash_ledger_entries_frozen_cash_after_non_negative"),
        ),
        sa.CheckConstraint(
            "total_cash_after = available_cash_after + frozen_cash_after",
            name=op.f("ck_cash_ledger_entries_balance_components_equal_total"),
        ),
        sa.CheckConstraint(
            "gross_amount IS NULL OR gross_amount >= 0",
            name=op.f("ck_cash_ledger_entries_gross_non_negative"),
        ),
        sa.CheckConstraint(
            "fee_amount IS NULL OR fee_amount >= 0",
            name=op.f("ck_cash_ledger_entries_fee_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["ledger_transaction_id"],
            ["ledger_transactions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_cash_ledger_entries_ledger_transaction_id_ledger_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            ondelete="RESTRICT",
            name=op.f("fk_cash_ledger_entries_account_id_trading_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["related_fill_id"],
            ["fills.id"],
            ondelete="RESTRICT",
            name=op.f("fk_cash_ledger_entries_related_fill_id_fills"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cash_ledger_entries")),
    )
    op.create_index(
        "ix_cash_ledger_entries_account_occurred",
        "cash_ledger_entries",
        ["account_id", "occurred_at"],
    )
    op.create_index(
        "ix_cash_ledger_entries_transaction", "cash_ledger_entries", ["ledger_transaction_id"]
    )
    op.create_index("ix_cash_ledger_entries_fill", "cash_ledger_entries", ["related_fill_id"])
    op.create_index("ix_cash_ledger_entries_correlation", "cash_ledger_entries", ["correlation_id"])

    op.create_table(
        "position_ledger_entries",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("ledger_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("quantity_delta", QUANTITY, nullable=False),
        sa.Column("available_quantity_delta", QUANTITY, nullable=False),
        sa.Column("frozen_quantity_delta", QUANTITY, nullable=False),
        sa.Column("unsettled_quantity_delta", QUANTITY, nullable=False),
        sa.Column("cost_basis_delta", AMOUNT, nullable=False),
        sa.Column("realized_pnl_delta", AMOUNT, nullable=False),
        sa.Column("total_quantity_after", QUANTITY, nullable=False),
        sa.Column("available_quantity_after", QUANTITY, nullable=False),
        sa.Column("frozen_quantity_after", QUANTITY, nullable=False),
        sa.Column("unsettled_quantity_after", QUANTITY, nullable=False),
        sa.Column("cost_basis_after", AMOUNT, nullable=False),
        sa.Column("average_cost_after", PRICE, nullable=False),
        sa.Column("realized_pnl_after", AMOUNT, nullable=False),
        sa.Column("related_fill_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=JSON_OBJECT,
            nullable=False,
        ),
        *timestamps(),
        sa.CheckConstraint(
            "entry_type IN ('BUY','SELL','FREEZE','RELEASE','SETTLEMENT','ADJUSTMENT','REVERSAL')",
            name=op.f("ck_position_ledger_entries_entry_type_valid"),
        ),
        sa.CheckConstraint(
            "quantity_delta = available_quantity_delta + frozen_quantity_delta + unsettled_quantity_delta",
            name=op.f("ck_position_ledger_entries_delta_components_equal_total"),
        ),
        sa.CheckConstraint(
            "total_quantity_after >= 0",
            name=op.f("ck_position_ledger_entries_total_after_non_negative"),
        ),
        sa.CheckConstraint(
            "available_quantity_after >= 0",
            name=op.f("ck_position_ledger_entries_available_after_non_negative"),
        ),
        sa.CheckConstraint(
            "frozen_quantity_after >= 0",
            name=op.f("ck_position_ledger_entries_frozen_after_non_negative"),
        ),
        sa.CheckConstraint(
            "unsettled_quantity_after >= 0",
            name=op.f("ck_position_ledger_entries_unsettled_after_non_negative"),
        ),
        sa.CheckConstraint(
            "total_quantity_after = available_quantity_after + frozen_quantity_after + unsettled_quantity_after",
            name=op.f("ck_position_ledger_entries_balance_components_equal_total"),
        ),
        sa.CheckConstraint(
            "cost_basis_after >= 0",
            name=op.f("ck_position_ledger_entries_cost_basis_after_non_negative"),
        ),
        sa.CheckConstraint(
            "average_cost_after >= 0",
            name=op.f("ck_position_ledger_entries_average_cost_after_non_negative"),
        ),
        sa.CheckConstraint(
            "total_quantity_after <> 0 OR (cost_basis_after = 0 AND average_cost_after = 0)",
            name=op.f("ck_position_ledger_entries_closed_position_cost_zero"),
        ),
        sa.ForeignKeyConstraint(
            ["ledger_transaction_id"],
            ["ledger_transactions.id"],
            ondelete="RESTRICT",
            name=op.f("fk_position_ledger_entries_ledger_transaction_id_ledger_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            ondelete="RESTRICT",
            name=op.f("fk_position_ledger_entries_account_id_trading_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            ondelete="RESTRICT",
            name=op.f("fk_position_ledger_entries_instrument_id_instruments"),
        ),
        sa.ForeignKeyConstraint(
            ["related_fill_id"],
            ["fills.id"],
            ondelete="RESTRICT",
            name=op.f("fk_position_ledger_entries_related_fill_id_fills"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_position_ledger_entries")),
    )
    op.create_index(
        "ix_position_ledger_entries_account_instrument_occurred",
        "position_ledger_entries",
        ["account_id", "instrument_id", "occurred_at"],
    )
    op.create_index(
        "ix_position_ledger_entries_transaction",
        "position_ledger_entries",
        ["ledger_transaction_id"],
    )
    op.create_index(
        "ix_position_ledger_entries_fill", "position_ledger_entries", ["related_fill_id"]
    )
    op.create_index(
        "ix_position_ledger_entries_correlation", "position_ledger_entries", ["correlation_id"]
    )

    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash_total", AMOUNT, nullable=False),
        sa.Column("cash_available", AMOUNT, nullable=False),
        sa.Column("cash_frozen", AMOUNT, nullable=False),
        sa.Column("positions_cost_basis", AMOUNT, nullable=False),
        sa.Column("positions_market_value", AMOUNT, nullable=True),
        sa.Column("total_equity", AMOUNT, nullable=True),
        sa.Column("realized_pnl", AMOUNT, nullable=False),
        sa.Column("unrealized_pnl", AMOUNT, nullable=True),
        sa.Column("valuation_status", sa.String(32), nullable=False),
        sa.Column("priced_position_count", sa.Integer(), nullable=False),
        sa.Column("unpriced_position_count", sa.Integer(), nullable=False),
        sa.Column("latest_price_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=JSON_OBJECT,
            nullable=False,
        ),
        *timestamps(),
        sa.CheckConstraint(
            "cash_total >= 0 AND cash_available >= 0 AND cash_frozen >= 0 AND positions_cost_basis >= 0",
            name=op.f("ck_account_snapshots_amounts_non_negative"),
        ),
        sa.CheckConstraint(
            "total_equity IS NULL OR total_equity >= 0",
            name=op.f("ck_account_snapshots_equity_non_negative"),
        ),
        sa.CheckConstraint(
            "priced_position_count >= 0 AND unpriced_position_count >= 0",
            name=op.f("ck_account_snapshots_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "valuation_status IN ('COMPLETE','PARTIAL','STALE','UNAVAILABLE')",
            name=op.f("ck_account_snapshots_valuation_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            ondelete="RESTRICT",
            name=op.f("fk_account_snapshots_account_id_trading_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_snapshots")),
    )
    op.create_index(
        "ix_account_snapshots_account_as_of", "account_snapshots", ["account_id", "as_of"]
    )
    op.create_index(
        "ix_account_snapshots_status_as_of", "account_snapshots", ["valuation_status", "as_of"]
    )
    op.create_index("ix_account_snapshots_correlation", "account_snapshots", ["correlation_id"])

    op.create_table(
        "account_reconciliation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_cash", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actual_cash", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_positions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actual_positions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("discrepancy_count", sa.Integer(), nullable=False),
        sa.Column("discrepancies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('MATCHED','MISMATCHED','FAILED')",
            name=op.f("ck_account_reconciliation_runs_status_valid"),
        ),
        sa.CheckConstraint(
            "discrepancy_count >= 0",
            name=op.f("ck_account_reconciliation_runs_discrepancy_count_non_negative"),
        ),
        sa.CheckConstraint(
            "status <> 'MATCHED' OR discrepancy_count = 0",
            name=op.f("ck_account_reconciliation_runs_matched_has_no_discrepancy"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name=op.f("ck_account_reconciliation_runs_completion_not_before_start"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(discrepancies) = 'array' AND jsonb_array_length(discrepancies) <= 100",
            name=op.f("ck_account_reconciliation_runs_discrepancies_bounded_array"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            ondelete="RESTRICT",
            name=op.f("fk_account_reconciliation_runs_account_id_trading_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_reconciliation_runs")),
    )
    op.create_index(
        "ix_account_reconciliation_runs_account_started",
        "account_reconciliation_runs",
        ["account_id", "started_at"],
    )
    op.create_index(
        "ix_account_reconciliation_runs_status_started",
        "account_reconciliation_runs",
        ["status", "started_at"],
    )
    op.create_index(
        "ix_account_reconciliation_runs_correlation",
        "account_reconciliation_runs",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_table("account_reconciliation_runs")
    op.drop_table("account_snapshots")
    op.drop_table("position_ledger_entries")
    op.drop_table("cash_ledger_entries")
    op.drop_table("ledger_transactions")
    op.drop_table("account_cash_balances")

    for name in (
        "valuation_status_valid",
        "last_price_positive",
        "closed_position_cost_zero",
        "average_cost_non_negative",
        "cost_basis_non_negative",
        "unsettled_quantity_non_negative",
        "quantity_components_equal_total",
    ):
        op.drop_constraint(op.f(f"ck_positions_{name}"), "positions", type_="check")
    op.execute(
        "UPDATE positions SET market_value = COALESCE(market_value, 0), unrealized_pnl = COALESCE(unrealized_pnl, 0)"
    )
    op.alter_column("positions", "unrealized_pnl", existing_type=AMOUNT, nullable=False)
    op.alter_column("positions", "market_value", existing_type=AMOUNT, nullable=False)
    op.drop_column("positions", "valuation_status")
    op.drop_column("positions", "last_price_at")
    op.drop_column("positions", "last_price")
    op.drop_column("positions", "cost_basis")
    op.drop_column("positions", "unsettled_quantity")
    op.create_check_constraint(
        "available_frozen_within_total",
        "positions",
        "available_quantity + frozen_quantity <= total_quantity",
    )
    op.drop_column("orders", "metadata")
    op.drop_constraint(
        op.f("uq_trading_accounts_creation_idempotency_key"),
        "trading_accounts",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_trading_accounts_settlement_policy_valid"),
        "trading_accounts",
        type_="check",
    )
    op.drop_column("trading_accounts", "creation_idempotency_key")
    op.drop_column("trading_accounts", "settlement_policy")
