"""SQLAlchemy persistence models kept separate from domain entities."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from alphadesk_api.infrastructure.database import Base
from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    AccountValuationStatus,
    AdjustmentType,
    CashLedgerEntryType,
    CommandStatus,
    CommandType,
    ExecutorDeviceStatus,
    ExecutorPermission,
    LedgerTransactionStatus,
    LedgerTransactionType,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketSyncStatus,
    MarketTimeframe,
    OrderSide,
    OrderStatus,
    OrderType,
    OutboxStatus,
    PositionLedgerEntryType,
    ReconciliationStatus,
    RiskDecisionType,
    RiskLayer,
    SettlementPolicy,
    SignalStatus,
    SignalType,
    StrategyStatus,
    SyncTriggerType,
    TimeInForce,
)

PRICE = Numeric(20, 8)
QUANTITY = Numeric(24, 8)
AMOUNT = Numeric(24, 8)
RATIO = Numeric(12, 8)
JSON_DEFAULT = text("'{}'::jsonb")
UTC_NOW = text("timezone('utc', now())")


def enum_values(enum_type: Any) -> str:
    return ", ".join(f"'{item.value}'" for item in enum_type)


class TimestampedModel:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    )


class MutableTimestampedModel(TimestampedModel):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    )


class InstrumentModel(MutableTimestampedModel, Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("exchange", "symbol", name="uq_instruments_exchange_symbol"),
        CheckConstraint("lot_size > 0", name="lot_size_positive"),
        CheckConstraint("price_tick > 0", name="price_tick_positive"),
        Index("ix_instruments_market_active", "market", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    lot_size: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    price_tick: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class WatchlistModel(MutableTimestampedModel, Base):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("name", name="uq_watchlists_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class WatchlistItemModel(TimestampedModel, Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint(
            "watchlist_id", "instrument_id", name="uq_watchlist_items_watchlist_instrument"
        ),
        CheckConstraint("sort_order >= 0", name="sort_order_non_negative"),
        Index("ix_watchlist_items_watchlist_sort", "watchlist_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    watchlist_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)


class TradingAccountModel(MutableTimestampedModel, Base):
    __tablename__ = "trading_accounts"
    __table_args__ = (
        UniqueConstraint("account_code", name="uq_trading_accounts_account_code"),
        CheckConstraint(f"account_type IN ({enum_values(AccountType)})", name="account_type_valid"),
        CheckConstraint(f"status IN ({enum_values(AccountStatus)})", name="account_status_valid"),
        CheckConstraint(
            f"settlement_policy IN ({enum_values(SettlementPolicy)})",
            name="settlement_policy_valid",
        ),
        UniqueConstraint(
            "creation_idempotency_key",
            name="uq_trading_accounts_creation_idempotency_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    broker_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    settlement_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SettlementPolicy.IMMEDIATE.value
    )
    creation_idempotency_key: Mapped[str | None] = mapped_column(String(128))
    external_account_reference: Mapped[str | None] = mapped_column(String(256))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class PositionModel(MutableTimestampedModel, Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id", name="uq_positions_account_instrument"),
        CheckConstraint("total_quantity >= 0", name="total_quantity_non_negative"),
        CheckConstraint("available_quantity >= 0", name="available_quantity_non_negative"),
        CheckConstraint("frozen_quantity >= 0", name="frozen_quantity_non_negative"),
        CheckConstraint("unsettled_quantity >= 0", name="unsettled_quantity_non_negative"),
        CheckConstraint(
            "available_quantity + frozen_quantity + unsettled_quantity = total_quantity",
            name="quantity_components_equal_total",
        ),
        CheckConstraint("cost_basis >= 0", name="cost_basis_non_negative"),
        CheckConstraint("average_cost >= 0", name="average_cost_non_negative"),
        CheckConstraint(
            "total_quantity <> 0 OR (cost_basis = 0 AND average_cost = 0)",
            name="closed_position_cost_zero",
        ),
        CheckConstraint("last_price IS NULL OR last_price > 0", name="last_price_positive"),
        CheckConstraint(
            f"valuation_status IN ({enum_values(AccountValuationStatus)})",
            name="valuation_status_valid",
        ),
        CheckConstraint("row_version >= 1", name="row_version_positive"),
        Index("ix_positions_account", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    total_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    available_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    frozen_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unsettled_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    market_value: Mapped[Decimal | None] = mapped_column(AMOUNT)
    realized_pnl: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(AMOUNT)
    last_price: Mapped[Decimal | None] = mapped_column(PRICE)
    last_price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valuation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AccountCashBalanceModel(MutableTimestampedModel, Base):
    __tablename__ = "account_cash_balances"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "currency", name="uq_account_cash_balances_account_currency"
        ),
        CheckConstraint("total_cash >= 0", name="total_cash_non_negative"),
        CheckConstraint("available_cash >= 0", name="available_cash_non_negative"),
        CheckConstraint("frozen_cash >= 0", name="frozen_cash_non_negative"),
        CheckConstraint(
            "total_cash = available_cash + frozen_cash",
            name="cash_components_equal_total",
        ),
        CheckConstraint("row_version >= 1", name="row_version_positive"),
        CheckConstraint("length(trim(currency)) > 0", name="currency_non_empty"),
        Index("ix_account_cash_balances_account", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    total_cash: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    available_cash: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    frozen_cash: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LedgerTransactionModel(MutableTimestampedModel, Base):
    __tablename__ = "ledger_transactions"
    __table_args__ = (
        UniqueConstraint("business_key", name="uq_ledger_transactions_business_key"),
        CheckConstraint(
            f"transaction_type IN ({enum_values(LedgerTransactionType)})",
            name="transaction_type_valid",
        ),
        CheckConstraint(f"status IN ({enum_values(LedgerTransactionStatus)})", name="status_valid"),
        CheckConstraint(
            "posted_at IS NULL OR posted_at >= occurred_at", name="posted_not_before_occurred"
        ),
        CheckConstraint("reversal_of_id IS NULL OR reversal_of_id <> id", name="not_self_reversal"),
        CheckConstraint(
            "description IS NULL OR length(description) <= 500", name="description_length"
        ),
        Index("ix_ledger_transactions_account_occurred", "account_id", "occurred_at"),
        Index("ix_ledger_transactions_order", "related_order_id"),
        Index("ix_ledger_transactions_correlation", "correlation_id"),
        Index("ix_ledger_transactions_status_created", "status", "created_at"),
        Index(
            "uq_ledger_transactions_related_fill",
            "related_fill_id",
            unique=True,
            postgresql_where=text("related_fill_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    business_key: Mapped[str] = mapped_column(String(160), nullable=False)
    related_order_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("orders.id", ondelete="RESTRICT")
    )
    related_fill_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("fills.id", ondelete="RESTRICT")
    )
    reversal_of_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("ledger_transactions.id", ondelete="RESTRICT")
    )
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class CashLedgerEntryModel(TimestampedModel, Base):
    __tablename__ = "cash_ledger_entries"
    __table_args__ = (
        CheckConstraint(
            f"entry_type IN ({enum_values(CashLedgerEntryType)})", name="entry_type_valid"
        ),
        CheckConstraint(
            "total_delta = available_delta + frozen_delta", name="delta_components_equal_total"
        ),
        CheckConstraint("total_cash_after >= 0", name="total_cash_after_non_negative"),
        CheckConstraint("available_cash_after >= 0", name="available_cash_after_non_negative"),
        CheckConstraint("frozen_cash_after >= 0", name="frozen_cash_after_non_negative"),
        CheckConstraint(
            "total_cash_after = available_cash_after + frozen_cash_after",
            name="balance_components_equal_total",
        ),
        CheckConstraint("gross_amount IS NULL OR gross_amount >= 0", name="gross_non_negative"),
        CheckConstraint("fee_amount IS NULL OR fee_amount >= 0", name="fee_non_negative"),
        Index("ix_cash_ledger_entries_account_occurred", "account_id", "occurred_at"),
        Index("ix_cash_ledger_entries_transaction", "ledger_transaction_id"),
        Index("ix_cash_ledger_entries_fill", "related_fill_id"),
        Index("ix_cash_ledger_entries_correlation", "correlation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ledger_transaction_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    total_delta: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    available_delta: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    frozen_delta: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    gross_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    fee_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    total_cash_after: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    available_cash_after: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    frozen_cash_after: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    related_fill_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("fills.id", ondelete="RESTRICT")
    )
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class PositionLedgerEntryModel(TimestampedModel, Base):
    __tablename__ = "position_ledger_entries"
    __table_args__ = (
        CheckConstraint(
            f"entry_type IN ({enum_values(PositionLedgerEntryType)})", name="entry_type_valid"
        ),
        CheckConstraint(
            "quantity_delta = available_quantity_delta + frozen_quantity_delta "
            "+ unsettled_quantity_delta",
            name="delta_components_equal_total",
        ),
        CheckConstraint("total_quantity_after >= 0", name="total_after_non_negative"),
        CheckConstraint("available_quantity_after >= 0", name="available_after_non_negative"),
        CheckConstraint("frozen_quantity_after >= 0", name="frozen_after_non_negative"),
        CheckConstraint("unsettled_quantity_after >= 0", name="unsettled_after_non_negative"),
        CheckConstraint(
            "total_quantity_after = available_quantity_after + frozen_quantity_after "
            "+ unsettled_quantity_after",
            name="balance_components_equal_total",
        ),
        CheckConstraint("cost_basis_after >= 0", name="cost_basis_after_non_negative"),
        CheckConstraint("average_cost_after >= 0", name="average_cost_after_non_negative"),
        CheckConstraint(
            "total_quantity_after <> 0 OR (cost_basis_after = 0 AND average_cost_after = 0)",
            name="closed_position_cost_zero",
        ),
        Index(
            "ix_position_ledger_entries_account_instrument_occurred",
            "account_id",
            "instrument_id",
            "occurred_at",
        ),
        Index("ix_position_ledger_entries_transaction", "ledger_transaction_id"),
        Index("ix_position_ledger_entries_fill", "related_fill_id"),
        Index("ix_position_ledger_entries_correlation", "correlation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ledger_transaction_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ledger_transactions.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    available_quantity_delta: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    frozen_quantity_delta: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unsettled_quantity_delta: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    cost_basis_delta: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    realized_pnl_delta: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    total_quantity_after: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    available_quantity_after: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    frozen_quantity_after: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unsettled_quantity_after: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    cost_basis_after: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    average_cost_after: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    realized_pnl_after: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    related_fill_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("fills.id", ondelete="RESTRICT")
    )
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class AccountSnapshotModel(TimestampedModel, Base):
    __tablename__ = "account_snapshots"
    __table_args__ = (
        CheckConstraint(
            "cash_total >= 0 AND cash_available >= 0 AND cash_frozen >= 0 "
            "AND positions_cost_basis >= 0",
            name="amounts_non_negative",
        ),
        CheckConstraint("total_equity IS NULL OR total_equity >= 0", name="equity_non_negative"),
        CheckConstraint(
            "priced_position_count >= 0 AND unpriced_position_count >= 0",
            name="counts_non_negative",
        ),
        CheckConstraint(
            f"valuation_status IN ({enum_values(AccountValuationStatus)})",
            name="valuation_status_valid",
        ),
        Index("ix_account_snapshots_account_as_of", "account_id", "as_of"),
        Index("ix_account_snapshots_status_as_of", "valuation_status", "as_of"),
        Index("ix_account_snapshots_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cash_total: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    cash_available: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    cash_frozen: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    positions_cost_basis: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    positions_market_value: Mapped[Decimal | None] = mapped_column(AMOUNT)
    total_equity: Mapped[Decimal | None] = mapped_column(AMOUNT)
    realized_pnl: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(AMOUNT)
    valuation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    priced_position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unpriced_position_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_price_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class AccountReconciliationRunModel(TimestampedModel, Base):
    __tablename__ = "account_reconciliation_runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({enum_values(ReconciliationStatus)})", name="status_valid"),
        CheckConstraint("discrepancy_count >= 0", name="discrepancy_count_non_negative"),
        CheckConstraint(
            "status <> 'MATCHED' OR discrepancy_count = 0", name="matched_has_no_discrepancy"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="completion_not_before_start",
        ),
        CheckConstraint(
            "jsonb_typeof(discrepancies) = 'array' AND jsonb_array_length(discrepancies) <= 100",
            name="discrepancies_bounded_array",
        ),
        Index("ix_account_reconciliation_runs_account_started", "account_id", "started_at"),
        Index("ix_account_reconciliation_runs_status_started", "status", "started_at"),
        Index("ix_account_reconciliation_runs_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_cash: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actual_cash: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expected_positions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actual_positions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False)
    discrepancies: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class StrategyModel(MutableTimestampedModel, Base):
    __tablename__ = "strategies"
    __table_args__ = (
        UniqueConstraint("strategy_code", name="uq_strategies_strategy_code"),
        CheckConstraint(f"status IN ({enum_values(StrategyStatus)})", name="strategy_status_valid"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    strategy_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class StrategyVersionModel(TimestampedModel, Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint(
            "strategy_id", "version_number", name="uq_strategy_versions_strategy_version"
        ),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        Index(
            "uq_strategy_versions_one_active",
            "strategy_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    strategy_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    code_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    parameter_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    default_parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SignalModel(TimestampedModel, Base):
    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(f"signal_type IN ({enum_values(SignalType)})", name="signal_type_valid"),
        CheckConstraint(f"side IN ({enum_values(OrderSide)})", name="signal_side_valid"),
        CheckConstraint(f"status IN ({enum_values(SignalStatus)})", name="signal_status_valid"),
        CheckConstraint(
            "target_quantity IS NULL OR target_quantity > 0", name="target_quantity_positive"
        ),
        CheckConstraint(
            "target_weight IS NULL OR (target_weight >= 0 AND target_weight <= 1)",
            name="target_weight_range",
        ),
        CheckConstraint("valid_until > generated_at", name="validity_window"),
        Index("ix_signals_strategy_generated", "strategy_id", "generated_at"),
        Index("ix_signals_account_instrument", "account_id", "instrument_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    strategy_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("strategies.id", ondelete="RESTRICT"), nullable=False
    )
    strategy_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("strategy_versions.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    target_quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    target_weight: Mapped[Decimal | None] = mapped_column(RATIO)
    reference_price: Mapped[Decimal | None] = mapped_column(PRICE)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class ExecutorDeviceModel(MutableTimestampedModel, Base):
    __tablename__ = "executor_devices"
    __table_args__ = (
        UniqueConstraint("device_code", name="uq_executor_devices_device_code"),
        CheckConstraint(
            f"status IN ({enum_values(ExecutorDeviceStatus)})", name="device_status_valid"
        ),
        Index("ix_executor_devices_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    device_code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    public_key_fingerprint: Mapped[str] = mapped_column(String(256), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderModel(MutableTimestampedModel, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_orders_idempotency_key"),
        CheckConstraint(f"side IN ({enum_values(OrderSide)})", name="order_side_valid"),
        CheckConstraint(f"order_type IN ({enum_values(OrderType)})", name="order_type_valid"),
        CheckConstraint(
            f"time_in_force IN ({enum_values(TimeInForce)})", name="time_in_force_valid"
        ),
        CheckConstraint(f"status IN ({enum_values(OrderStatus)})", name="order_status_valid"),
        CheckConstraint("requested_quantity > 0", name="requested_quantity_positive"),
        CheckConstraint("filled_quantity >= 0", name="filled_quantity_non_negative"),
        CheckConstraint("filled_quantity <= requested_quantity", name="filled_within_requested"),
        CheckConstraint("limit_price IS NULL OR limit_price > 0", name="limit_price_positive"),
        CheckConstraint(
            "order_type <> 'LIMIT' OR limit_price IS NOT NULL", name="limit_order_has_price"
        ),
        Index("ix_orders_account_created", "account_id", "created_at"),
        Index("ix_orders_status_created", "status", "created_at"),
        Index("ix_orders_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    strategy_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("strategies.id", ondelete="RESTRICT")
    )
    strategy_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("strategy_versions.id", ondelete="RESTRICT")
    )
    signal_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("signals.id", ondelete="RESTRICT")
    )
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    filled_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, default=Decimal("0"))
    limit_price: Mapped[Decimal | None] = mapped_column(PRICE)
    average_fill_price: Mapped[Decimal | None] = mapped_column(PRICE)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    broker_type: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(128))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class OrderStateTransitionModel(Base):
    __tablename__ = "order_state_transitions"
    __table_args__ = (
        CheckConstraint(
            f"from_status IS NULL OR from_status IN ({enum_values(OrderStatus)})",
            name="from_status_valid",
        ),
        CheckConstraint(f"to_status IN ({enum_values(OrderStatus)})", name="to_status_valid"),
        Index("ix_order_state_transitions_order_occurred", "order_id", "occurred_at"),
        Index("ix_order_state_transitions_correlation", "correlation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class OrderCommandModel(MutableTimestampedModel, Base):
    __tablename__ = "order_commands"
    __table_args__ = (
        UniqueConstraint("command_id", name="uq_order_commands_command_id"),
        CheckConstraint(f"command_type IN ({enum_values(CommandType)})", name="command_type_valid"),
        CheckConstraint(f"status IN ({enum_values(CommandStatus)})", name="command_status_valid"),
        CheckConstraint("sequence_number >= 0", name="sequence_number_non_negative"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index("ix_order_commands_order_sequence", "order_id", "sequence_number"),
        Index("ix_order_commands_target_status", "target_device_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    command_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    command_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    target_device_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("executor_devices.id", ondelete="RESTRICT")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    signature_reference: Mapped[str | None] = mapped_column(String(256))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FillModel(TimestampedModel, Base):
    __tablename__ = "fills"
    __table_args__ = (
        UniqueConstraint("broker_type", "broker_fill_id", name="uq_fills_broker_fill"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("commission >= 0", name="commission_non_negative"),
        CheckConstraint("tax >= 0", name="tax_non_negative"),
        CheckConstraint("other_fee >= 0", name="other_fee_non_negative"),
        Index("ix_fills_order_executed", "order_id", "executed_at"),
        Index("ix_fills_account_instrument", "account_id", "instrument_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    broker_type: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_fill_id: Mapped[str | None] = mapped_column(String(128))
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    commission: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    tax: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    other_fee: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class RiskDecisionModel(TimestampedModel, Base):
    __tablename__ = "risk_decisions"
    __table_args__ = (
        CheckConstraint("signal_id IS NOT NULL OR order_id IS NOT NULL", name="target_required"),
        CheckConstraint(f"layer IN ({enum_values(RiskLayer)})", name="risk_layer_valid"),
        CheckConstraint(
            f"decision IN ({enum_values(RiskDecisionType)})", name="risk_decision_valid"
        ),
        Index("ix_risk_decisions_signal", "signal_id"),
        Index("ix_risk_decisions_order", "order_id"),
        Index("ix_risk_decisions_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    signal_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("signals.id", ondelete="RESTRICT")
    )
    order_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("orders.id", ondelete="RESTRICT")
    )
    layer: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DomainEventModel(TimestampedModel, Base):
    __tablename__ = "domain_events"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        Index("ix_domain_events_entity_sequence", "entity_type", "entity_id", "sequence"),
        Index("ix_domain_events_correlation", "correlation_id"),
        Index("ix_domain_events_event_time", "event_time"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(Uuid)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class AuditLogModel(TimestampedModel, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_resource_occurred", "resource_type", "resource_id", "occurred_at"),
        Index("ix_audit_logs_correlation", "correlation_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class OutboxMessageModel(MutableTimestampedModel, Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint("event_id", "topic", name="uq_outbox_messages_event_topic"),
        CheckConstraint(f"status IN ({enum_values(OutboxStatus)})", name="outbox_status_valid"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index(
            "ix_outbox_messages_pending_available",
            "available_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_outbox_messages_aggregate", "aggregate_type", "aggregate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("domain_events.event_id", ondelete="RESTRICT"), nullable=False
    )
    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ExecutorDeviceAccountModel(TimestampedModel, Base):
    __tablename__ = "executor_device_accounts"
    __table_args__ = (
        CheckConstraint(
            f"permission IN ({enum_values(ExecutorPermission)})", name="permission_valid"
        ),
        Index("ix_executor_device_accounts_account", "account_id"),
    )

    device_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("executor_devices.id", ondelete="RESTRICT"), primary_key=True
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), primary_key=True
    )
    permission: Mapped[str] = mapped_column(String(32), nullable=False)


class MarketDataSourceModel(MutableTimestampedModel, Base):
    __tablename__ = "market_data_sources"
    __table_args__ = (
        UniqueConstraint("source_code", name="uq_market_data_sources_source_code"),
        CheckConstraint("priority >= 0", name="priority_non_negative"),
        CheckConstraint(f"status IN ({enum_values(MarketDataSourceStatus)})", name="status_valid"),
        CheckConstraint(
            "jsonb_typeof(supported_timeframes) = 'array' "
            "AND jsonb_array_length(supported_timeframes) > 0",
            name="supported_timeframes_non_empty_array",
        ),
        Index("ix_market_data_sources_status", "status"),
        Index("ix_market_data_sources_priority", "priority"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    supports_realtime: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supported_timeframes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class InstrumentMappingModel(MutableTimestampedModel, Base):
    __tablename__ = "instrument_mappings"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "external_symbol", name="uq_instrument_mappings_source_symbol"
        ),
        UniqueConstraint(
            "source_id", "instrument_id", name="uq_instrument_mappings_source_instrument"
        ),
        CheckConstraint("length(trim(external_symbol)) > 0", name="external_symbol_non_empty"),
        Index("ix_instrument_mappings_instrument", "instrument_id"),
        Index("ix_instrument_mappings_source", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("market_data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    external_symbol: Mapped[str] = mapped_column(String(128), nullable=False)
    external_exchange: Mapped[str | None] = mapped_column(String(64))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class MarketBarModel(MutableTimestampedModel, Base):
    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "source_id",
            "timeframe",
            "adjustment_type",
            "bar_time",
            name="uq_market_bars_identity",
        ),
        CheckConstraint(f"timeframe IN ({enum_values(MarketTimeframe)})", name="timeframe_valid"),
        CheckConstraint(
            f"adjustment_type IN ({enum_values(AdjustmentType)})",
            name="adjustment_type_valid",
        ),
        CheckConstraint(
            f"quality_status IN ({enum_values(MarketDataQualityStatus)})",
            name="quality_status_valid",
        ),
        CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="ohlc_positive"),
        CheckConstraint(
            "high >= open AND high >= close AND high >= low",
            name="high_not_below_ohlc",
        ),
        CheckConstraint("low <= open AND low <= close AND low <= high", name="low_not_above_ohlc"),
        CheckConstraint("volume >= 0", name="volume_non_negative"),
        CheckConstraint("amount IS NULL OR amount >= 0", name="amount_non_negative"),
        CheckConstraint("vwap IS NULL OR vwap > 0", name="vwap_positive"),
        CheckConstraint(
            "open_interest IS NULL OR open_interest >= 0", name="open_interest_non_negative"
        ),
        Index("ix_market_bars_source_received", "source_id", "received_at"),
        Index("ix_market_bars_quality_received", "quality_status", "received_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("market_data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    volume: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    vwap: Mapped[Decimal | None] = mapped_column(PRICE)
    open_interest: Mapped[Decimal | None] = mapped_column(QUANTITY)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


Index(
    "ix_market_bars_instrument_timeframe_time",
    MarketBarModel.instrument_id,
    MarketBarModel.timeframe,
    MarketBarModel.bar_time.desc(),
)
Index(
    "ix_market_bars_instrument_source_timeframe_time",
    MarketBarModel.instrument_id,
    MarketBarModel.source_id,
    MarketBarModel.timeframe,
    MarketBarModel.bar_time.desc(),
)


class MarketSyncRunModel(MutableTimestampedModel, Base):
    __tablename__ = "market_sync_runs"
    __table_args__ = (
        CheckConstraint(
            f"trigger_type IN ({enum_values(SyncTriggerType)})", name="trigger_type_valid"
        ),
        CheckConstraint(f"status IN ({enum_values(MarketSyncStatus)})", name="status_valid"),
        CheckConstraint(f"timeframe IN ({enum_values(MarketTimeframe)})", name="timeframe_valid"),
        CheckConstraint(
            f"adjustment_type IN ({enum_values(AdjustmentType)})",
            name="adjustment_type_valid",
        ),
        CheckConstraint(
            "total_received >= 0 AND total_inserted >= 0 AND total_updated >= 0 "
            "AND total_rejected >= 0",
            name="counters_non_negative",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="completion_not_early"
        ),
        CheckConstraint(
            "error_summary IS NULL OR length(error_summary) <= 1000",
            name="error_summary_length",
        ),
        CheckConstraint(
            "jsonb_typeof(requested_symbols) = 'array'", name="requested_symbols_array"
        ),
        Index("ix_market_sync_runs_source_started", "source_id", "started_at"),
        Index("ix_market_sync_runs_status_started", "status", "started_at"),
        Index("ix_market_sync_runs_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("market_data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_symbols: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    requested_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
