"""HTTP contracts for free realtime market data and live valuation."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from alphadesk_domain.enums import (
    MarketDataQualityStatus,
    MarketProviderTier,
    MarketProviderUsage,
    QuoteFreshnessStatus,
)


class QuoteResponse(BaseModel):
    instrument_id: UUID
    source_code: str
    symbol: str
    quote_time: datetime | None
    received_at: datetime
    last_price: Decimal
    previous_close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    volume: Decimal | None
    amount: Decimal | None
    quality_status: MarketDataQualityStatus
    provider_tier: MarketProviderTier
    usage: tuple[MarketProviderUsage, ...]
    quality_flags: dict[str, Any]
    revision: int
    freshness: QuoteFreshnessStatus
    age_seconds: int


class LatestQuotesResponse(BaseModel):
    schema_version: int = 1
    items: list[QuoteResponse]
    missing_instrument_ids: list[UUID]
    calculated_at: datetime


class RealtimeStatusResponse(BaseModel):
    enabled: bool
    state: str
    source_code: str | None = None
    circuit_state: str | None = None
    consecutive_failures: int = 0
    requested_count: int = 0
    received_count: int = 0
    changed_count: int = 0
    rejected_count: int = 0
    checked_at: datetime | None = None
    error_summary: str | None = None
    worker_heartbeat: dict[str, Any] | None = None


class SubscriptionItemResponse(BaseModel):
    instrument_id: UUID
    symbol: str
    reasons: list[str]


class SubscriptionSummaryResponse(BaseModel):
    revision: int = 0
    generated_at: datetime | None = None
    count: int = 0
    items: list[SubscriptionItemResponse] = Field(default_factory=list)


class PositionLiveValuationResponse(BaseModel):
    instrument_id: UUID
    symbol: str
    quantity: Decimal
    price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    price_source: str | None
    quote_time: datetime | None
    freshness: QuoteFreshnessStatus


class AccountLiveValuationResponse(BaseModel):
    account_id: UUID
    cash_balance: Decimal
    positions_market_value: Decimal
    total_equity: Decimal
    status: str
    calculated_at: datetime
    positions: list[PositionLiveValuationResponse]
