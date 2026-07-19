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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from alphadesk_api.infrastructure.database import Base
from alphadesk_domain.ai_research import AIAnalysisStatus, AIAnalysisType, AIImpactDirection
from alphadesk_domain.broker import BrokerExecutionMode, BrokerExecutionStatus
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
    MarketDataIssueSeverity,
    MarketDataQualityRunStatus,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketSyncStatus,
    MarketTimeframe,
    OrderActionType,
    OrderActorType,
    OrderIntentSource,
    OrderSide,
    OrderStatus,
    OrderType,
    OutboxStatus,
    PositionLedgerEntryType,
    RealtimeRunStatus,
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
from alphadesk_domain.information import (
    InformationIngestionStatus,
    InformationSourceType,
    InformationStatus,
    MarketEventDirection,
    MarketEventStatus,
    MarketEventType,
)
from alphadesk_domain.scanners import ScanRunStatus
from alphadesk_domain.strategy import StrategyEnvironment
from alphadesk_domain.strategy_experiments import StrategyExperimentStatus
from alphadesk_domain.strategy_runs import StrategyRunStatus

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
        CheckConstraint(
            "target_quantity IS NULL OR target_weight IS NULL",
            name="signal_target_mutually_exclusive",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="signal_confidence_range",
        ),
        CheckConstraint(
            "sequence_number IS NULL OR sequence_number >= 1",
            name="signal_sequence_positive",
        ),
        CheckConstraint("schema_version >= 1", name="signal_schema_version_positive"),
        UniqueConstraint("strategy_run_id", "sequence_number", name="uq_signals_run_sequence"),
        Index("ix_signals_strategy_generated", "strategy_id", "generated_at"),
        Index("ix_signals_account_instrument", "account_id", "instrument_id"),
        Index("ix_signals_strategy_run_id", "strategy_run_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    strategy_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("strategies.id", ondelete="RESTRICT")
    )
    strategy_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("strategy_versions.id", ondelete="RESTRICT")
    )
    account_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT")
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
    strategy_run_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("strategy_runs.id", ondelete="RESTRICT")
    )
    sequence_number: Mapped[int | None] = mapped_column(Integer)
    strategy_key: Mapped[str | None] = mapped_column(String(64))
    strategy_version: Mapped[str | None] = mapped_column(String(32))
    bar_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[Decimal | None] = mapped_column(RATIO)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class StrategyRunModel(MutableTimestampedModel, Base):
    __tablename__ = "strategy_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_strategy_runs_idempotency_key"),
        CheckConstraint(
            f"status IN ({enum_values(StrategyRunStatus)})", name="strategy_run_status_valid"
        ),
        CheckConstraint(
            f"environment IN ({enum_values(StrategyEnvironment)})",
            name="strategy_run_environment_valid",
        ),
        CheckConstraint(
            f"timeframe IN ({enum_values(MarketTimeframe)})", name="run_timeframe_valid"
        ),
        CheckConstraint("start_at < end_at", name="strategy_run_time_window"),
        CheckConstraint(
            "bars_processed >= 0 AND signals_generated >= 0",
            name="strategy_run_counters_non_negative",
        ),
        Index("ix_strategy_runs_status_created", "status", "created_at"),
        Index("ix_strategy_runs_strategy_created", "strategy_key", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("strategies.id", ondelete="RESTRICT")
    )
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("strategy_versions.id", ondelete="RESTRICT")
    )
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    instrument_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    bars_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class StrategyExperimentModel(MutableTimestampedModel, Base):
    __tablename__ = "strategy_experiments"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_strategy_experiments_idempotency_key"),
        CheckConstraint(
            f"status IN ({enum_values(StrategyExperimentStatus)})",
            name="strategy_experiment_status_valid",
        ),
        CheckConstraint(
            "environment = 'RESEARCH'", name="strategy_experiment_environment_research"
        ),
        CheckConstraint(
            f"timeframe IN ({enum_values(MarketTimeframe)})",
            name="strategy_experiment_timeframe_valid",
        ),
        CheckConstraint("start_at < end_at", name="strategy_experiment_time_window"),
        CheckConstraint("combination_count > 0", name="strategy_experiment_combination_positive"),
        CheckConstraint(
            "runs_completed >= 0 AND runs_failed >= 0 AND total_signals >= 0",
            name="strategy_experiment_counters_non_negative",
        ),
        Index("ix_strategy_experiments_strategy_created", "strategy_key", "created_at"),
        Index("ix_strategy_experiments_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_key: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parameter_grid: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    combination_count: Mapped[int] = mapped_column(Integer, nullable=False)
    runs_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_signals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class StrategyExperimentRunModel(TimestampedModel, Base):
    __tablename__ = "strategy_experiment_runs"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "combination_index",
            name="uq_strategy_experiment_runs_experiment_index",
        ),
        UniqueConstraint("strategy_run_id", name="uq_strategy_experiment_runs_strategy_run"),
        UniqueConstraint(
            "child_idempotency_key",
            name="uq_strategy_experiment_runs_child_idempotency_key",
        ),
        CheckConstraint("combination_index >= 1", name="strategy_experiment_run_index_positive"),
        Index(
            "ix_strategy_experiment_runs_experiment_index",
            "experiment_id",
            "combination_index",
        ),
        Index("ix_strategy_experiment_runs_strategy_run", "strategy_run_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    experiment_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("strategy_experiments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    strategy_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("strategy_runs.id", ondelete="RESTRICT"), nullable=False
    )
    combination_index: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    child_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)


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
        CheckConstraint(
            f"intent_source IN ({enum_values(OrderIntentSource)})", name="ck_orders_intent_source"
        ),
        CheckConstraint("row_version >= 1", name="ck_orders_row_version_positive"),
        CheckConstraint("requested_quantity > 0", name="requested_quantity_positive"),
        CheckConstraint("filled_quantity >= 0", name="filled_quantity_non_negative"),
        CheckConstraint("filled_quantity <= requested_quantity", name="filled_within_requested"),
        CheckConstraint("limit_price IS NULL OR limit_price > 0", name="limit_price_positive"),
        CheckConstraint(
            "order_type <> 'LIMIT' OR limit_price IS NOT NULL", name="limit_order_has_price"
        ),
        Index("ix_orders_account_created", "account_id", "created_at"),
        Index("ix_orders_account_status_created", "account_id", "status", text("created_at DESC")),
        Index("ix_orders_instrument_created", "instrument_id", text("created_at DESC")),
        Index("ix_orders_intent_created", "intent_source", text("created_at DESC")),
        Index("ix_orders_request_fingerprint", "request_fingerprint"),
        Index(
            "ix_orders_expires_pending",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
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
    intent_source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="MANUAL")
    request_fingerprint: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="legacy"
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    confirmation_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    broker_order_id: Mapped[str | None] = mapped_column(String(128))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_actor_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="LOCAL_USER"
    )
    created_by_actor_id: Mapped[str | None] = mapped_column(String(128))
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
        CheckConstraint("order_version >= 1", name="ck_order_state_transitions_version_positive"),
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
    order_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # This is the authoritative foreign-key direction.  `OrderAction` keeps
    # `applied_transition_id` as a nullable lookup value to avoid a cycle.
    action_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "order_actions.id",
            name="fk_order_state_transitions_action",
            ondelete="RESTRICT",
        ),
    )
    command_id: Mapped[UUID | None] = mapped_column(Uuid)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class OrderActionModel(TimestampedModel, Base):
    __tablename__ = "order_actions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_order_actions_idempotency_key"),
        CheckConstraint(
            f"action_type IN ({enum_values(OrderActionType)})", name="ck_order_actions_action_type"
        ),
        CheckConstraint(
            f"actor_type IN ({enum_values(OrderActorType)})", name="ck_order_actions_actor_type"
        ),
        CheckConstraint(
            "expected_order_version >= 1", name="order_action_expected_version_positive"
        ),
        CheckConstraint(
            "applied_order_version >= expected_order_version",
            name="order_action_applied_version_valid",
        ),
        Index("ix_order_actions_order_occurred", "order_id", "occurred_at"),
        Index("ix_order_actions_correlation", "correlation_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    expected_order_version: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_order_version: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_transition_id: Mapped[int | None] = mapped_column(BigInteger)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    note: Mapped[str | None] = mapped_column(String(1024))
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
        CheckConstraint(
            "(consumed_at IS NULL) = (consumed_by IS NULL)",
            name="consumption_pair",
        ),
        CheckConstraint(
            "(status = 'CONSUMED') = (consumed_at IS NOT NULL)",
            name="consumed_status_matches_fields",
        ),
        Index("ix_order_commands_order_sequence", "order_id", "sequence_number"),
        Index(
            "uq_order_commands_submit_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("command_type = 'SUBMIT_ORDER'"),
        ),
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
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_by: Mapped[str | None] = mapped_column(String(64))


class FillModel(TimestampedModel, Base):
    __tablename__ = "fills"
    __table_args__ = (
        UniqueConstraint("broker_type", "broker_fill_id", name="uq_fills_broker_fill"),
        UniqueConstraint(
            "execution_attempt_id",
            "sequence_number",
            name="uq_fills_execution_attempt_sequence",
        ),
        UniqueConstraint("execution_reference", name="uq_fills_execution_reference"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price > 0", name="price_positive"),
        CheckConstraint("commission >= 0", name="commission_non_negative"),
        CheckConstraint("tax >= 0", name="tax_non_negative"),
        CheckConstraint("other_fee >= 0", name="other_fee_non_negative"),
        CheckConstraint(
            "sequence_number IS NULL OR sequence_number >= 1",
            name="sequence_number_positive",
        ),
        CheckConstraint(
            "(execution_attempt_id IS NULL AND command_id IS NULL "
            "AND sequence_number IS NULL AND execution_reference IS NULL) OR "
            "(execution_attempt_id IS NOT NULL AND command_id IS NOT NULL "
            "AND sequence_number IS NOT NULL AND execution_reference IS NOT NULL)",
            name="execution_link_fields_complete",
        ),
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
    execution_attempt_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("broker_execution_attempts.id", ondelete="RESTRICT"),
    )
    command_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("order_commands.command_id", ondelete="RESTRICT"),
    )
    sequence_number: Mapped[int | None] = mapped_column(Integer)
    execution_reference: Mapped[str | None] = mapped_column(String(160))
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


class BrokerExecutionAttemptModel(TimestampedModel, Base):
    __tablename__ = "broker_execution_attempts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_broker_execution_attempts_idempotency"),
        UniqueConstraint(
            "order_id", "attempt_number", name="uq_broker_execution_attempts_order_attempt"
        ),
        UniqueConstraint(
            "command_id", "attempt_number", name="uq_broker_execution_attempts_command_attempt"
        ),
        CheckConstraint(
            f"execution_mode IN ({enum_values(BrokerExecutionMode)})",
            name="execution_mode_valid",
        ),
        CheckConstraint(
            f"result_status IN ({enum_values(BrokerExecutionStatus)})",
            name="result_status_valid",
        ),
        CheckConstraint(
            f"input_order_status IN ({enum_values(OrderStatus)})",
            name="input_order_status_valid",
        ),
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
        CheckConstraint(
            "requested_quantity > 0 AND previously_filled_quantity >= 0 "
            "AND attempted_quantity > 0 AND filled_quantity >= 0 "
            "AND remaining_quantity >= 0",
            name="quantities_non_negative",
        ),
        CheckConstraint(
            "previously_filled_quantity + attempted_quantity = requested_quantity",
            name="attempted_quantity_balances",
        ),
        CheckConstraint(
            "previously_filled_quantity + filled_quantity + remaining_quantity "
            "= requested_quantity",
            name="result_quantities_balance",
        ),
        CheckConstraint("filled_quantity <= attempted_quantity", name="filled_within_attempted"),
        CheckConstraint(
            "(filled_quantity = 0 AND average_fill_price IS NULL) OR "
            "(filled_quantity > 0 AND average_fill_price > 0)",
            name="average_price_matches_fill",
        ),
        CheckConstraint("completed_at >= started_at", name="completion_after_start"),
        CheckConstraint("length(request_fingerprint) = 64", name="fingerprint_length"),
        Index("ix_broker_execution_attempts_command", "command_id"),
        Index("ix_broker_execution_attempts_account_created", "account_id", "created_at"),
        Index("ix_broker_execution_attempts_result_created", "result_status", "created_at"),
        Index("ix_broker_execution_attempts_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_key: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_version: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    order_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    command_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("order_commands.command_id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    input_order_status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    previously_filled_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    attempted_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    filled_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    average_fill_price: Mapped[Decimal | None] = mapped_column(PRICE)
    rejection_code: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    market_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    account_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fee_model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    slippage_model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RiskDecisionModel(TimestampedModel, Base):
    __tablename__ = "risk_decisions"
    __table_args__ = (
        CheckConstraint(f"layer IN ({enum_values(RiskLayer)})", name="risk_layer_valid"),
        CheckConstraint(
            f"overall_decision IN ({enum_values(RiskDecisionType)})", name="risk_decision_valid"
        ),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        UniqueConstraint("idempotency_key", name="uq_risk_decisions_idempotency_key"),
        UniqueConstraint("request_id", name="uq_risk_decisions_request_id"),
        Index("ix_risk_decisions_signal", "signal_id"),
        Index("ix_risk_decisions_order", "order_id"),
        Index("ix_risk_decisions_account_evaluated", "account_id", "evaluated_at"),
        Index("ix_risk_decisions_instrument_evaluated", "instrument_id", "evaluated_at"),
        Index("ix_risk_decisions_source", "source_type", "source_id"),
        Index("ix_risk_decisions_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(Uuid)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("trading_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    signal_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("signals.id", ondelete="RESTRICT")
    )
    order_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("orders.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
    )
    layer: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    estimated_notional: Mapped[Decimal | None] = mapped_column(AMOUNT)
    projected_instrument_weight: Mapped[Decimal | None] = mapped_column(RATIO)
    projected_total_exposure: Mapped[Decimal | None] = mapped_column(RATIO)
    limits_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    account_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    instrument_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class RiskRuleEvaluationModel(TimestampedModel, Base):
    __tablename__ = "risk_rule_evaluations"
    __table_args__ = (
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint(f"decision IN ({enum_values(RiskDecisionType)})", name="decision_valid"),
        UniqueConstraint("risk_decision_id", "seq", name="uq_risk_rule_evaluations_decision_seq"),
        UniqueConstraint(
            "risk_decision_id", "rule_key", name="uq_risk_rule_evaluations_decision_rule"
        ),
        Index("ix_risk_rule_evaluations_decision_seq", "risk_decision_id", "seq"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    risk_decision_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("risk_decisions.id", ondelete="RESTRICT"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_value: Mapped[str | int | bool | None] = mapped_column(JSONB)
    limit_value: Mapped[str | int | bool | None] = mapped_column(JSONB)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
        CheckConstraint(
            "(suppressed_at IS NULL) = (suppression_reason IS NULL)",
            name="suppression_pair",
        ),
        CheckConstraint(
            "(status = 'SUPPRESSED') = (suppressed_at IS NOT NULL)",
            name="suppressed_status_matches_fields",
        ),
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
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suppression_reason: Mapped[str | None] = mapped_column(String(64))
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
    provider_tier: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MarketProviderTier.DEMO.value
    )
    supports_quotes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_recent_minute_bars: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class MarketDataQualityRunModel(MutableTimestampedModel, Base):
    __tablename__ = "market_data_quality_runs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({enum_values(MarketDataQualityRunStatus)})", name="status_valid"
        ),
        CheckConstraint(f"timeframe IN ({enum_values(MarketTimeframe)})", name="timeframe_valid"),
        CheckConstraint(
            "instruments_checked >= 0 AND bars_checked >= 0 AND issues_found >= 0 "
            "AND error_count >= 0 AND warning_count >= 0 AND info_count >= 0",
            name="counters_non_negative",
        ),
        CheckConstraint(
            "issues_found = error_count + warning_count + info_count",
            name="severity_counts_match",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="completion_not_early"
        ),
        Index("ix_market_data_quality_runs_status_created", "status", "created_at"),
        Index("ix_market_data_quality_runs_universe_created", "universe_key", "created_at"),
        Index("ix_market_data_quality_runs_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    universe_key: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str | None] = mapped_column(String(64))
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    instruments_checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bars_checked: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    issues_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class MarketDataQualityIssueModel(TimestampedModel, Base):
    __tablename__ = "market_data_quality_issues"
    __table_args__ = (
        CheckConstraint(
            f"severity IN ({enum_values(MarketDataIssueSeverity)})", name="severity_valid"
        ),
        CheckConstraint(f"timeframe IN ({enum_values(MarketTimeframe)})", name="timeframe_valid"),
        CheckConstraint("length(trim(issue_type)) > 0", name="issue_type_non_empty"),
        CheckConstraint("length(trim(message)) > 0", name="message_non_empty"),
        CheckConstraint(
            "last_affected_at IS NULL OR first_affected_at IS NULL "
            "OR last_affected_at >= first_affected_at",
            name="affected_range_valid",
        ),
        Index("ix_market_data_quality_issues_run", "quality_run_id", "created_at"),
        Index("ix_market_data_quality_issues_severity_created", "severity", "created_at"),
        Index("ix_market_data_quality_issues_instrument_type", "instrument_id", "issue_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    quality_run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("market_data_quality_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    instrument_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    first_affected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_affected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_value: Mapped[str | None] = mapped_column(String(512))
    expected_value: Mapped[str | None] = mapped_column(String(512))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    required_action: Mapped[str | None] = mapped_column(String(512))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class MarketRealtimeRunModel(MutableTimestampedModel, Base):
    __tablename__ = "market_realtime_runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({enum_values(RealtimeRunStatus)})", name="status_valid"),
        CheckConstraint(
            "requested_count >= 0 AND received_count >= 0 AND changed_count >= 0 "
            "AND rejected_count >= 0",
            name="counters_non_negative",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="completion_not_early"
        ),
        CheckConstraint(
            "error_summary IS NULL OR length(error_summary) <= 1000",
            name="error_summary_length",
        ),
        Index("ix_market_realtime_runs_source_started", "source_id", "started_at"),
        Index("ix_market_realtime_runs_status_started", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("market_data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    received_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(String(1000))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class ScanRunModel(MutableTimestampedModel, Base):
    __tablename__ = "scan_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_scan_runs_idempotency_key"),
        CheckConstraint(f"status IN ({enum_values(ScanRunStatus)})", name="scan_run_status_valid"),
        CheckConstraint("timeframe = 'DAY_1'", name="scan_run_timeframe_daily"),
        CheckConstraint(
            "instruments_scanned >= 0 AND matches_found >= 0 "
            "AND matches_found <= instruments_scanned",
            name="scan_run_counters_valid",
        ),
        CheckConstraint("length(request_fingerprint) = 64", name="scan_run_fingerprint_sha256"),
        Index("ix_scan_runs_scanner_created", "scanner_key", "created_at"),
        Index("ix_scan_runs_status_created", "status", "created_at"),
        Index("ix_scan_runs_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    scanner_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scanner_version: Mapped[str] = mapped_column(String(32), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    universe_type: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    instruments_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matches_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class ScanResultModel(TimestampedModel, Base):
    __tablename__ = "scan_results"
    __table_args__ = (
        UniqueConstraint("scan_run_id", "instrument_id", name="uq_scan_results_run_instrument"),
        UniqueConstraint("scan_run_id", "rank", name="uq_scan_results_run_rank"),
        CheckConstraint("rank >= 1", name="scan_result_rank_positive"),
        CheckConstraint("score >= 0", name="scan_result_score_non_negative"),
        CheckConstraint("reference_price > 0", name="scan_result_reference_price_positive"),
        CheckConstraint("schema_version >= 1", name="scan_result_schema_version_positive"),
        Index("ix_scan_results_run_rank", "scan_run_id", "rank"),
        Index("ix_scan_results_instrument_matched", "instrument_id", "matched_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    scan_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("scan_runs.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[Decimal] = mapped_column(AMOUNT, nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class InformationSourceModel(MutableTimestampedModel, Base):
    __tablename__ = "information_sources"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_information_sources_source_key"),
        CheckConstraint(
            f"source_type IN ({enum_values(InformationSourceType)})",
            name="information_source_type_valid",
        ),
        Index("ix_information_sources_type_enabled", "source_type", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(2048))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )


class InformationIngestionRunModel(MutableTimestampedModel, Base):
    __tablename__ = "information_ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({enum_values(InformationIngestionStatus)})",
            name="information_ingestion_status_valid",
        ),
        CheckConstraint(
            "fetched_count >= 0 AND inserted_count >= 0 AND duplicate_count >= 0 "
            "AND failed_count >= 0",
            name="information_ingestion_counters_non_negative",
        ),
        Index("ix_information_ingestion_source_started", "source_id", "started_at"),
        Index("ix_information_ingestion_status_started", "status", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("information_sources.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_summary: Mapped[str | None] = mapped_column(String(512))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class RawDocumentModel(TimestampedModel, Base):
    __tablename__ = "raw_documents"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_documents_source_external_id"),
        UniqueConstraint("content_hash", name="uq_raw_documents_content_hash"),
        CheckConstraint("length(content_hash) = 64", name="raw_document_hash_sha256"),
        Index("ix_raw_documents_source_received", "source_id", "received_at"),
        Index("ix_raw_documents_published", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("information_sources.id", ondelete="RESTRICT"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(512))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=JSON_DEFAULT
    )
    ingestion_run_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("information_ingestion_runs.id", ondelete="RESTRICT")
    )


class InformationItemModel(TimestampedModel, Base):
    __tablename__ = "information_items"
    __table_args__ = (
        UniqueConstraint("raw_document_id", name="uq_information_items_raw_document"),
        CheckConstraint(
            f"status IN ({enum_values(InformationStatus)})", name="information_item_status_valid"
        ),
        Index("ix_information_items_published", "published_at"),
        Index("ix_information_items_received", "received_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    raw_document_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("raw_documents.id", ondelete="RESTRICT"), nullable=False
    )
    normalized_title: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


class MarketEventModel(TimestampedModel, Base):
    __tablename__ = "market_events"
    __table_args__ = (
        UniqueConstraint("information_item_id", name="uq_market_events_information_item"),
        CheckConstraint(
            f"event_type IN ({enum_values(MarketEventType)})", name="market_event_type_valid"
        ),
        CheckConstraint(
            f"direction IN ({enum_values(MarketEventDirection)})",
            name="market_event_direction_valid",
        ),
        CheckConstraint(
            f"status IN ({enum_values(MarketEventStatus)})", name="market_event_status_valid"
        ),
        CheckConstraint(
            "importance IS NULL OR (importance >= 0 AND importance <= 1)",
            name="market_event_importance_range",
        ),
        CheckConstraint("schema_version >= 1", name="market_event_schema_version_positive"),
        Index("ix_market_events_type_time", "event_type", "event_at"),
        Index("ix_market_events_direction_time", "direction", "event_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    information_item_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("information_items.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    importance: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class EventInstrumentLinkModel(Base):
    __tablename__ = "event_instrument_links"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="event_instrument_confidence_range",
        ),
        Index("ix_event_instrument_links_instrument", "instrument_id", "event_id"),
    )

    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("market_events.id", ondelete="RESTRICT"), primary_key=True
    )
    instrument_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("instruments.id", ondelete="RESTRICT"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    )


class EventThemeLinkModel(Base):
    __tablename__ = "event_theme_links"
    __table_args__ = (Index("ix_event_theme_links_theme", "theme_key", "event_id"),)

    event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("market_events.id", ondelete="RESTRICT"), primary_key=True
    )
    theme_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    theme_name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=UTC_NOW
    )


class AIAnalysisRunModel(MutableTimestampedModel, Base):
    __tablename__ = "ai_analysis_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ai_analysis_runs_idempotency_key"),
        CheckConstraint(
            f"analysis_type IN ({enum_values(AIAnalysisType)})", name="ai_analysis_type_valid"
        ),
        CheckConstraint(
            f"status IN ({enum_values(AIAnalysisStatus)})", name="ai_analysis_status_valid"
        ),
        CheckConstraint("length(request_fingerprint) = 64", name="ai_analysis_fingerprint_sha256"),
        CheckConstraint(
            "input_token_count IS NULL OR input_token_count >= 0",
            name="ai_analysis_input_tokens_non_negative",
        ),
        CheckConstraint(
            "output_token_count IS NULL OR output_token_count >= 0",
            name="ai_analysis_output_tokens_non_negative",
        ),
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="ai_analysis_cost_non_negative",
        ),
        Index("ix_ai_analysis_type_created", "analysis_type", "created_at"),
        Index("ix_ai_analysis_status_created", "status", "created_at"),
        Index("ix_ai_analysis_correlation", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_document_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), nullable=False)
    input_event_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), nullable=False)
    instrument_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), nullable=False)
    user_question: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    input_token_count: Mapped[int | None] = mapped_column(Integer)
    output_token_count: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(512))
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class ResearchInsightModel(TimestampedModel, Base):
    __tablename__ = "research_insights"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", name="uq_research_insights_analysis_run"),
        CheckConstraint(
            f"impact_direction IN ({enum_values(AIImpactDirection)})",
            name="research_insight_direction_valid",
        ),
        CheckConstraint(
            "importance_score >= 0 AND importance_score <= 100",
            name="research_insight_importance_range",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="research_insight_confidence_range"
        ),
        CheckConstraint("schema_version >= 1", name="research_insight_schema_positive"),
        Index("ix_research_insights_type_created", "insight_type", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    analysis_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    insight_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    impact_direction: Mapped[str] = mapped_column(String(16), nullable=False)
    importance_score: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    time_horizon: Mapped[str | None] = mapped_column(String(128))
    key_facts: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    uncertainties: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    research_questions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    structured_output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ResearchEvidenceModel(TimestampedModel, Base):
    __tablename__ = "research_evidence"
    __table_args__ = (
        CheckConstraint(
            "(information_item_id IS NOT NULL)::integer + "
            "(market_event_id IS NOT NULL)::integer = 1",
            name="research_evidence_exactly_one_source",
        ),
        CheckConstraint("length(evidence_text) <= 2000", name="research_evidence_text_length"),
        Index("ix_research_evidence_insight", "insight_id", "created_at"),
        Index("ix_research_evidence_item", "information_item_id"),
        Index("ix_research_evidence_event", "market_event_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    insight_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("research_insights.id", ondelete="RESTRICT"), nullable=False
    )
    information_item_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("information_items.id", ondelete="RESTRICT")
    )
    market_event_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("market_events.id", ondelete="RESTRICT")
    )
    evidence_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    evidence_location: Mapped[str | None] = mapped_column(String(512))
