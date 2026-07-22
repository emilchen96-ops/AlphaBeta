"""Framework-independent market-data entities and validation rules."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataIssueSeverity,
    MarketDataQualityRunStatus,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketSyncStatus,
    MarketTimeframe,
    SyncTriggerType,
)
from alphadesk_domain.values import as_utc, decimal_value, non_empty, utc_now

JsonObject = dict[str, Any]


@dataclass(slots=True, kw_only=True)
class MarketDataSource:
    source_code: str
    name: str
    status: MarketDataSourceStatus
    priority: int
    supports_realtime: bool
    supported_timeframes: tuple[MarketTimeframe, ...]
    provider_tier: MarketProviderTier = MarketProviderTier.DEMO
    supports_quotes: bool = False
    supports_recent_minute_bars: bool = False
    last_health_check_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.source_code = non_empty(self.source_code, "source_code").upper()
        self.name = non_empty(self.name, "name")
        if self.priority < 0:
            raise ValueError("priority must be non-negative")
        if not self.supported_timeframes:
            raise ValueError("supported_timeframes must not be empty")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")
        if self.last_health_check_at is not None:
            self.last_health_check_at = as_utc(self.last_health_check_at, "last_health_check_at")


@dataclass(slots=True, kw_only=True)
class InstrumentMapping:
    instrument_id: UUID
    source_id: UUID
    external_symbol: str
    id: UUID = field(default_factory=uuid4)
    external_exchange: str | None = None
    is_primary: bool = True
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.external_symbol = non_empty(self.external_symbol, "external_symbol")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class MarketBar:
    instrument_id: UUID
    source_id: UUID
    timeframe: MarketTimeframe
    adjustment_type: AdjustmentType
    bar_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    received_at: datetime
    quality_status: MarketDataQualityStatus
    id: int | None = None
    amount: Decimal | None = None
    vwap: Decimal | None = None
    open_interest: Decimal | None = None
    source_updated_at: datetime | None = None
    quality_flags: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close", "volume"):
            decimal_value(getattr(self, name), name)
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("OHLC prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is below another OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is above another OHLC value")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")
        for name in ("amount", "vwap", "open_interest"):
            value = getattr(self, name)
            if value is not None:
                decimal_value(value, name)
        if self.amount is not None and self.amount < 0:
            raise ValueError("amount must be non-negative")
        if self.vwap is not None and self.vwap <= 0:
            raise ValueError("vwap must be positive")
        if self.open_interest is not None and self.open_interest < 0:
            raise ValueError("open_interest must be non-negative")
        self.bar_time = as_utc(self.bar_time, "bar_time")
        self.received_at = as_utc(self.received_at, "received_at")
        if self.source_updated_at is not None:
            self.source_updated_at = as_utc(self.source_updated_at, "source_updated_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")
        if self.timeframe is MarketTimeframe.DAY_1 and any(
            (
                self.bar_time.hour,
                self.bar_time.minute,
                self.bar_time.second,
                self.bar_time.microsecond,
            )
        ):
            raise ValueError("DAY_1 bar_time must align to UTC midnight")
        if self.timeframe is MarketTimeframe.MINUTE_1 and any(
            (self.bar_time.second, self.bar_time.microsecond)
        ):
            raise ValueError("MINUTE_1 bar_time must align to a minute")


@dataclass(slots=True, kw_only=True)
class MarketSyncRun:
    source_id: UUID
    trigger_type: SyncTriggerType
    status: MarketSyncStatus
    timeframe: MarketTimeframe
    adjustment_type: AdjustmentType
    requested_symbols: tuple[str, ...]
    started_at: datetime
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    requested_start: datetime | None = None
    requested_end: datetime | None = None
    completed_at: datetime | None = None
    total_received: int = 0
    total_inserted: int = 0
    total_updated: int = 0
    total_rejected: int = 0
    error_summary: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        counts = (
            self.total_received,
            self.total_inserted,
            self.total_updated,
            self.total_rejected,
        )
        if any(value < 0 for value in counts):
            raise ValueError("sync counters must be non-negative")
        if self.error_summary is not None and len(self.error_summary) > 1000:
            raise ValueError("error_summary exceeds 1000 characters")
        self.started_at = as_utc(self.started_at, "started_at")
        for name in ("requested_start", "requested_end", "completed_at"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, as_utc(value, name))
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataFreshness:
    source_code: str
    status: MarketDataQualityStatus
    latest_bar_time: datetime | None
    latest_received_at: datetime | None
    calculated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_code", non_empty(self.source_code, "source_code"))
        object.__setattr__(self, "calculated_at", as_utc(self.calculated_at, "calculated_at"))
        if self.latest_bar_time is not None:
            object.__setattr__(
                self, "latest_bar_time", as_utc(self.latest_bar_time, "latest_bar_time")
            )
        if self.latest_received_at is not None:
            object.__setattr__(
                self,
                "latest_received_at",
                as_utc(self.latest_received_at, "latest_received_at"),
            )


@dataclass(frozen=True, slots=True)
class MarketBarUpsertResult:
    inserted: int
    updated: int
    unchanged: int
    conflicts: int = 0


@dataclass(slots=True, kw_only=True)
class MarketDataQualityRun:
    timeframe: MarketTimeframe
    status: MarketDataQualityRunStatus
    started_at: datetime
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    universe_key: str | None = None
    provider: str | None = None
    instruments_checked: int = 0
    bars_checked: int = 0
    issues_found: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    completed_at: datetime | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        counts = (
            self.instruments_checked,
            self.bars_checked,
            self.issues_found,
            self.error_count,
            self.warning_count,
            self.info_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("quality-run counters must be non-negative")
        if self.issues_found != self.error_count + self.warning_count + self.info_count:
            raise ValueError("issues_found must equal severity counters")
        self.started_at = as_utc(self.started_at, "started_at")
        if self.completed_at is not None:
            self.completed_at = as_utc(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at must not precede started_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataQualityIssue:
    quality_run_id: UUID
    issue_type: str
    severity: MarketDataIssueSeverity
    timeframe: MarketTimeframe
    message: str
    id: UUID = field(default_factory=uuid4)
    instrument_id: UUID | None = None
    first_affected_at: datetime | None = None
    last_affected_at: datetime | None = None
    observed_value: str | None = None
    expected_value: str | None = None
    required_action: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "issue_type", non_empty(self.issue_type, "issue_type").upper())
        object.__setattr__(self, "message", non_empty(self.message, "message"))
        for name in ("first_affected_at", "last_affected_at", "created_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, as_utc(value, name))
        if (
            self.first_affected_at is not None
            and self.last_affected_at is not None
            and self.first_affected_at > self.last_affected_at
        ):
            raise ValueError("quality issue affected range is inverted")


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataCoverage:
    instrument_id: UUID
    source_id: UUID
    timeframe: MarketTimeframe
    adjustment_type: AdjustmentType
    bar_count: int
    earliest_bar: datetime | None
    latest_bar: datetime | None

    def __post_init__(self) -> None:
        if self.bar_count < 0:
            raise ValueError("bar_count must be non-negative")
        for name in ("earliest_bar", "latest_bar"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, as_utc(value, name))
