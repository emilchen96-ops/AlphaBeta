"""Pydantic contracts for the M04 simulated-account APIs."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from alphadesk_domain.enums import (
    AccountStatus,
    AccountValuationStatus,
    CashLedgerEntryType,
    LedgerTransactionStatus,
    LedgerTransactionType,
    PositionLedgerEntryType,
    ReconciliationStatus,
    SettlementPolicy,
)


class DomainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AccountCreateRequest(BaseModel):
    account_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    base_currency: str = Field(default="CNY", min_length=1, max_length=8)
    initial_cash: Decimal = Field(default=Decimal("0"), ge=0)
    settlement_policy: SettlementPolicy = SettlementPolicy.IMMEDIATE
    idempotency_key: str = Field(min_length=1, max_length=128)


class AccountUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    status: AccountStatus | None = None
    settlement_policy: SettlementPolicy | None = None


class FundingRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)


class AccountResponse(DomainResponse):
    id: UUID
    account_code: str
    name: str
    status: AccountStatus
    broker_type: str
    base_currency: str
    settlement_policy: SettlementPolicy
    created_at: datetime
    updated_at: datetime


class CashBalanceResponse(DomainResponse):
    id: UUID
    account_id: UUID
    currency: str
    total_cash: Decimal
    available_cash: Decimal
    frozen_cash: Decimal
    row_version: int
    as_of: datetime


class PositionResponse(DomainResponse):
    id: UUID
    instrument_id: UUID
    total_quantity: Decimal
    available_quantity: Decimal
    frozen_quantity: Decimal
    unsettled_quantity: Decimal
    cost_basis: Decimal
    average_cost: Decimal
    market_value: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    last_price: Decimal | None
    last_price_at: datetime | None
    valuation_status: AccountValuationStatus
    as_of: datetime


class AccountDetailResponse(AccountResponse):
    cash_balances: list[CashBalanceResponse]
    positions: list[PositionResponse]


class LedgerTransactionResponse(DomainResponse):
    id: UUID
    account_id: UUID
    transaction_type: LedgerTransactionType
    status: LedgerTransactionStatus
    business_key: str
    related_order_id: UUID | None
    related_fill_id: UUID | None
    correlation_id: UUID
    occurred_at: datetime
    posted_at: datetime | None
    description: str | None
    metadata: dict[str, Any]


class CashLedgerEntryResponse(DomainResponse):
    id: int
    ledger_transaction_id: UUID
    currency: str
    entry_type: CashLedgerEntryType
    total_delta: Decimal
    available_delta: Decimal
    frozen_delta: Decimal
    gross_amount: Decimal | None
    fee_amount: Decimal | None
    total_cash_after: Decimal
    available_cash_after: Decimal
    frozen_cash_after: Decimal
    related_fill_id: UUID | None
    occurred_at: datetime


class PositionLedgerEntryResponse(DomainResponse):
    id: int
    ledger_transaction_id: UUID
    instrument_id: UUID
    entry_type: PositionLedgerEntryType
    quantity_delta: Decimal
    cost_basis_delta: Decimal
    realized_pnl_delta: Decimal
    total_quantity_after: Decimal
    cost_basis_after: Decimal
    average_cost_after: Decimal
    realized_pnl_after: Decimal
    related_fill_id: UUID | None
    occurred_at: datetime


class AccountSnapshotResponse(DomainResponse):
    id: UUID
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
    latest_price_time: datetime | None
    metadata: dict[str, Any]


class ReconciliationResponse(DomainResponse):
    id: UUID
    account_id: UUID
    status: ReconciliationStatus
    started_at: datetime
    completed_at: datetime | None
    expected_cash: dict[str, Any]
    actual_cash: dict[str, Any]
    expected_positions: dict[str, Any]
    actual_positions: dict[str, Any]
    discrepancy_count: int
    discrepancies: list[dict[str, Any]]


class PageResponse(BaseModel):
    items: list[Any]
    page: int
    page_size: int
    total: int


class AccountSummaryResponse(BaseModel):
    account: AccountResponse
    cash_balances: list[CashBalanceResponse]
    positions: list[PositionResponse]
    latest_snapshot: AccountSnapshotResponse | None
    latest_reconciliation: ReconciliationResponse | None
