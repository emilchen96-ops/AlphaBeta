"""Framework-independent free realtime market-data domain types."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from alphadesk_domain.enums import (
    CircuitState,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketProviderUsage,
    ProviderCapabilityStatus,
    QuoteFreshnessStatus,
    QuoteUpdateType,
    RealtimeRunStatus,
    SubscriptionReason,
)
from alphadesk_domain.values import as_utc, decimal_value, non_empty, utc_now

JsonObject = dict[str, Any]


def _optional_decimal(value: Decimal | None, name: str, *, positive: bool = False) -> None:
    if value is None:
        return
    decimal_value(value, name)
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketQuote:
    instrument_id: UUID
    source_code: str
    symbol: str
    quote_time: datetime | None
    received_at: datetime
    last_price: Decimal
    previous_close: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    volume: Decimal | None = None
    amount: Decimal | None = None
    bid_price_1: Decimal | None = None
    bid_volume_1: Decimal | None = None
    ask_price_1: Decimal | None = None
    ask_volume_1: Decimal | None = None
    quality_status: MarketDataQualityStatus = MarketDataQualityStatus.UNKNOWN
    provider_tier: MarketProviderTier = MarketProviderTier.FREE_BEST_EFFORT
    usage: tuple[MarketProviderUsage, ...] = (
        MarketProviderUsage.RESEARCH_ONLY,
        MarketProviderUsage.NON_TRADING_GRADE,
    )
    quality_flags: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_code", non_empty(self.source_code, "source_code").upper())
        object.__setattr__(self, "symbol", non_empty(self.symbol, "symbol"))
        decimal_value(self.last_price, "last_price")
        if self.last_price <= 0:
            raise ValueError("last_price must be positive")
        for name in ("previous_close", "open", "high", "low", "bid_price_1", "ask_price_1"):
            _optional_decimal(getattr(self, name), name, positive=True)
        for name in ("volume", "amount", "bid_volume_1", "ask_volume_1"):
            _optional_decimal(getattr(self, name), name)
        object.__setattr__(self, "received_at", as_utc(self.received_at, "received_at"))
        if self.quote_time is not None:
            object.__setattr__(self, "quote_time", as_utc(self.quote_time, "quote_time"))


@dataclass(frozen=True, slots=True, kw_only=True)
class QuoteRevision:
    instrument_id: UUID
    revision: int
    payload_hash: str
    quote_time: datetime | None

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("revision must be positive")
        object.__setattr__(self, "payload_hash", non_empty(self.payload_hash, "payload_hash"))
        if self.quote_time is not None:
            object.__setattr__(self, "quote_time", as_utc(self.quote_time, "quote_time"))


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketQuoteSnapshot:
    quote: MarketQuote
    revision: QuoteRevision


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketQuoteUpdate:
    snapshot: MarketQuoteSnapshot
    update_type: QuoteUpdateType


@dataclass(frozen=True, slots=True, kw_only=True)
class QuoteFreshness:
    status: QuoteFreshnessStatus
    age_seconds: int | None
    calculated_at: datetime

    def __post_init__(self) -> None:
        if self.age_seconds is not None and self.age_seconds < 0:
            raise ValueError("age_seconds must be non-negative")
        object.__setattr__(self, "calculated_at", as_utc(self.calculated_at, "calculated_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataSourceHealth:
    source_code: str
    status: MarketDataSourceStatus
    capability_status: ProviderCapabilityStatus
    circuit_state: CircuitState
    checked_at: datetime
    consecutive_failures: int = 0
    message: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_code", non_empty(self.source_code, "source_code").upper())
        if self.consecutive_failures < 0:
            raise ValueError("consecutive_failures must be non-negative")
        object.__setattr__(self, "checked_at", as_utc(self.checked_at, "checked_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataSourceCapability:
    source_code: str
    supports_quotes: bool
    supports_recent_minute_bars: bool
    supported_historical_timeframes: tuple[str, ...]
    provider_tier: MarketProviderTier
    usage: tuple[MarketProviderUsage, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketSubscription:
    instrument_id: UUID
    symbol: str
    reasons: tuple[SubscriptionReason, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketSubscriptionSet:
    items: tuple[MarketSubscription, ...]
    revision: int
    generated_at: datetime

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("revision must be non-negative")
        object.__setattr__(self, "generated_at", as_utc(self.generated_at, "generated_at"))


@dataclass(slots=True, kw_only=True)
class MarketRealtimeRun:
    source_id: UUID
    status: RealtimeRunStatus
    started_at: datetime
    id: UUID = field(default_factory=uuid4)
    completed_at: datetime | None = None
    requested_count: int = 0
    received_count: int = 0
    changed_count: int = 0
    rejected_count: int = 0
    error_summary: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("requested_count", "received_count", "changed_count", "rejected_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        self.started_at = as_utc(self.started_at, "started_at")
        if self.completed_at is not None:
            self.completed_at = as_utc(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at must not precede started_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionLiveValuation:
    instrument_id: UUID
    symbol: str
    quantity: Decimal
    price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    price_source: str | None
    quote_time: datetime | None
    freshness: QuoteFreshnessStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountLiveValuation:
    account_id: UUID
    cash_balance: Decimal
    positions_market_value: Decimal
    total_equity: Decimal
    status: str
    calculated_at: datetime
    positions: tuple[PositionLiveValuation, ...]
