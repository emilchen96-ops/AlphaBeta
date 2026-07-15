"""Pure accounting entities and moving-average calculation rules for M04."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from alphadesk_domain.enums import (
    AccountValuationStatus,
    CashLedgerEntryType,
    LedgerTransactionStatus,
    LedgerTransactionType,
    PositionLedgerEntryType,
    ReconciliationStatus,
)
from alphadesk_domain.values import as_utc, decimal_value, non_empty, utc_now

JsonObject = dict[str, Any]
ZERO = Decimal("0")


def _non_negative(value: Decimal, name: str) -> Decimal:
    decimal_value(value, name)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


@dataclass(slots=True, kw_only=True)
class CashBalance:
    account_id: UUID
    currency: str
    total_cash: Decimal
    available_cash: Decimal
    frozen_cash: Decimal
    as_of: datetime
    id: UUID = field(default_factory=uuid4)
    row_version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.currency = non_empty(self.currency, "currency").upper()
        for name in ("total_cash", "available_cash", "frozen_cash"):
            _non_negative(getattr(self, name), name)
        if self.total_cash != self.available_cash + self.frozen_cash:
            raise ValueError("total_cash must equal available_cash plus frozen_cash")
        if self.row_version < 1:
            raise ValueError("row_version must be at least one")
        self.as_of = as_utc(self.as_of, "as_of")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class LedgerTransaction:
    account_id: UUID
    transaction_type: LedgerTransactionType
    status: LedgerTransactionStatus
    business_key: str
    correlation_id: UUID
    occurred_at: datetime
    id: UUID = field(default_factory=uuid4)
    related_order_id: UUID | None = None
    related_fill_id: UUID | None = None
    reversal_of_id: UUID | None = None
    posted_at: datetime | None = None
    description: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.business_key = non_empty(self.business_key, "business_key")
        if len(self.business_key) > 160:
            raise ValueError("business_key exceeds 160 characters")
        if self.reversal_of_id == self.id:
            raise ValueError("reversal transaction cannot reference itself")
        if self.description is not None and len(self.description) > 500:
            raise ValueError("description exceeds 500 characters")
        self.occurred_at = as_utc(self.occurred_at, "occurred_at")
        if self.posted_at is not None:
            self.posted_at = as_utc(self.posted_at, "posted_at")
            if self.posted_at < self.occurred_at:
                raise ValueError("posted_at must not precede occurred_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class CashLedgerEntry:
    ledger_transaction_id: UUID
    account_id: UUID
    currency: str
    entry_type: CashLedgerEntryType
    total_delta: Decimal
    available_delta: Decimal
    frozen_delta: Decimal
    total_cash_after: Decimal
    available_cash_after: Decimal
    frozen_cash_after: Decimal
    correlation_id: UUID
    occurred_at: datetime
    id: int | None = None
    gross_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    related_fill_id: UUID | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.currency = non_empty(self.currency, "currency").upper()
        for name in ("total_delta", "available_delta", "frozen_delta"):
            decimal_value(getattr(self, name), name)
        if self.total_delta != self.available_delta + self.frozen_delta:
            raise ValueError("cash ledger deltas do not balance")
        for name in ("total_cash_after", "available_cash_after", "frozen_cash_after"):
            _non_negative(getattr(self, name), name)
        if self.total_cash_after != self.available_cash_after + self.frozen_cash_after:
            raise ValueError("cash ledger balances do not reconcile")
        for name in ("gross_amount", "fee_amount"):
            value = getattr(self, name)
            if value is not None:
                _non_negative(value, name)
        self.occurred_at = as_utc(self.occurred_at, "occurred_at")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class PositionLedgerEntry:
    ledger_transaction_id: UUID
    account_id: UUID
    instrument_id: UUID
    entry_type: PositionLedgerEntryType
    quantity_delta: Decimal
    available_quantity_delta: Decimal
    frozen_quantity_delta: Decimal
    unsettled_quantity_delta: Decimal
    cost_basis_delta: Decimal
    realized_pnl_delta: Decimal
    total_quantity_after: Decimal
    available_quantity_after: Decimal
    frozen_quantity_after: Decimal
    unsettled_quantity_after: Decimal
    cost_basis_after: Decimal
    average_cost_after: Decimal
    realized_pnl_after: Decimal
    correlation_id: UUID
    occurred_at: datetime
    id: int | None = None
    related_fill_id: UUID | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in (
            "quantity_delta",
            "available_quantity_delta",
            "frozen_quantity_delta",
            "unsettled_quantity_delta",
            "cost_basis_delta",
            "realized_pnl_delta",
            "realized_pnl_after",
        ):
            decimal_value(getattr(self, name), name)
        if self.quantity_delta != (
            self.available_quantity_delta
            + self.frozen_quantity_delta
            + self.unsettled_quantity_delta
        ):
            raise ValueError("position ledger quantity deltas do not balance")
        for name in (
            "total_quantity_after",
            "available_quantity_after",
            "frozen_quantity_after",
            "unsettled_quantity_after",
            "cost_basis_after",
            "average_cost_after",
        ):
            _non_negative(getattr(self, name), name)
        if self.total_quantity_after != (
            self.available_quantity_after
            + self.frozen_quantity_after
            + self.unsettled_quantity_after
        ):
            raise ValueError("position ledger balances do not reconcile")
        if self.total_quantity_after == 0 and (
            self.cost_basis_after != 0 or self.average_cost_after != 0
        ):
            raise ValueError("closed position cost must be zero")
        self.occurred_at = as_utc(self.occurred_at, "occurred_at")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class AccountSnapshot:
    account_id: UUID
    as_of: datetime
    cash_total: Decimal
    cash_available: Decimal
    cash_frozen: Decimal
    positions_cost_basis: Decimal
    positions_market_value: Decimal | None
    total_equity: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    valuation_status: AccountValuationStatus
    priced_position_count: int
    unpriced_position_count: int
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    latest_price_time: datetime | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("cash_total", "cash_available", "cash_frozen", "positions_cost_basis"):
            _non_negative(getattr(self, name), name)
        decimal_value(self.realized_pnl, "realized_pnl")
        for name in ("positions_market_value", "total_equity", "unrealized_pnl"):
            value = getattr(self, name)
            if value is not None:
                decimal_value(value, name)
        if self.total_equity is not None and self.total_equity < 0:
            raise ValueError("total_equity must be non-negative")
        if self.priced_position_count < 0 or self.unpriced_position_count < 0:
            raise ValueError("valuation counts must be non-negative")
        if self.valuation_status in (
            AccountValuationStatus.COMPLETE,
            AccountValuationStatus.STALE,
        ) and any(
            value is None
            for value in (self.positions_market_value, self.total_equity, self.unrealized_pnl)
        ):
            raise ValueError("complete or stale valuation requires numeric totals")
        self.as_of = as_utc(self.as_of, "as_of")
        if self.latest_price_time is not None:
            self.latest_price_time = as_utc(self.latest_price_time, "latest_price_time")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class AccountReconciliationRun:
    account_id: UUID
    status: ReconciliationStatus
    started_at: datetime
    expected_cash: JsonObject
    actual_cash: JsonObject
    expected_positions: JsonObject
    actual_positions: JsonObject
    discrepancy_count: int
    discrepancies: list[JsonObject]
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.discrepancy_count < 0:
            raise ValueError("discrepancy_count must be non-negative")
        if self.status is ReconciliationStatus.MATCHED and self.discrepancy_count != 0:
            raise ValueError("matched reconciliation cannot contain discrepancies")
        if self.discrepancy_count != len(self.discrepancies):
            raise ValueError("discrepancy_count does not match discrepancy details")
        if len(self.discrepancies) > 100:
            raise ValueError("reconciliation discrepancy limit exceeded")
        self.started_at = as_utc(self.started_at, "started_at")
        if self.completed_at is not None:
            self.completed_at = as_utc(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at must not precede started_at")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountReconciliationResult:
    run: AccountReconciliationRun


@dataclass(frozen=True, slots=True, kw_only=True)
class FillAccountingResult:
    ledger_transaction_id: UUID
    fill_id: UUID
    cash_delta: Decimal
    quantity_delta: Decimal
    cost_basis_delta: Decimal
    realized_pnl_delta: Decimal
    total_cash_after: Decimal
    total_quantity_after: Decimal
    average_cost_after: Decimal
    realized_pnl_after: Decimal
    idempotent: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountValuationResult:
    snapshot: AccountSnapshot
    unpriced_instrument_ids: tuple[UUID, ...]
    source_code: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class FillAmounts:
    gross_amount: Decimal
    fee_total: Decimal
    net_amount: Decimal


def calculate_fill_amounts(
    *,
    quantity: Decimal,
    price: Decimal,
    commission: Decimal,
    tax: Decimal,
    other_fee: Decimal,
    is_buy: bool,
) -> FillAmounts:
    for name, value in (
        ("quantity", quantity),
        ("price", price),
        ("commission", commission),
        ("tax", tax),
        ("other_fee", other_fee),
    ):
        decimal_value(value, name)
    if quantity <= 0 or price <= 0:
        raise ValueError("fill quantity and price must be positive")
    if min(commission, tax, other_fee) < 0:
        raise ValueError("fill fees must be non-negative")
    gross = quantity * price
    fees = commission + tax + other_fee
    return FillAmounts(
        gross_amount=gross,
        fee_total=fees,
        net_amount=gross + fees if is_buy else gross - fees,
    )


def assert_fill_amounts(
    *,
    calculated: FillAmounts,
    stored_gross: Decimal,
    stored_net: Decimal,
    tolerance: Decimal,
) -> None:
    _non_negative(tolerance, "tolerance")
    decimal_value(stored_gross, "stored_gross")
    decimal_value(stored_net, "stored_net")
    if abs(calculated.gross_amount - stored_gross) > tolerance:
        raise ValueError("fill gross amount mismatch")
    if abs(calculated.net_amount - stored_net) > tolerance:
        raise ValueError("fill net amount mismatch")
