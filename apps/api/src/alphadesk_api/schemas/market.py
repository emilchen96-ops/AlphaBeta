"""Pydantic contracts for M03 instruments, watchlists, and market data."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataIssueSeverity,
    MarketDataQualityRunStatus,
    MarketDataQualityStatus,
    MarketDataReadinessStatus,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketSyncStatus,
    MarketTimeframe,
    SyncTriggerType,
)


class InstrumentResponse(BaseModel):
    id: UUID
    symbol: str
    exchange: str
    market: str
    name: str
    asset_type: str
    currency: str
    lot_size: Decimal
    price_tick: Decimal
    timezone: str
    is_active: bool
    updated_at: datetime


class InstrumentMappingResponse(BaseModel):
    source_id: UUID
    external_symbol: str
    external_exchange: str | None
    is_primary: bool


class InstrumentPageResponse(BaseModel):
    items: list[InstrumentResponse]
    page: int
    page_size: int
    total: int


class InstrumentDetailResponse(InstrumentResponse):
    mappings: list[InstrumentMappingResponse]


class WatchlistCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)


class WatchlistUpdateRequest(WatchlistCreateRequest):
    pass


class WatchlistItemCreateRequest(BaseModel):
    instrument_id: UUID
    note: str | None = Field(default=None, max_length=500)


class WatchlistItemUpdateRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class WatchlistReorderRequest(BaseModel):
    item_ids: list[UUID] = Field(min_length=1, max_length=2000)


class WatchlistResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class WatchlistItemResponse(BaseModel):
    id: UUID
    watchlist_id: UUID
    instrument: InstrumentResponse
    sort_order: int
    note: str | None
    created_at: datetime


class WatchlistDetailResponse(WatchlistResponse):
    items: list[WatchlistItemResponse]


class MarketDataSourceResponse(BaseModel):
    id: UUID
    source_code: str
    name: str
    status: MarketDataSourceStatus
    priority: int
    supports_realtime: bool
    provider_tier: MarketProviderTier
    supports_quotes: bool
    supports_recent_minute_bars: bool
    last_health_check_at: datetime | None
    supported_timeframes: tuple[MarketTimeframe, ...]
    updated_at: datetime


class MarketBarResponse(BaseModel):
    instrument_id: UUID
    source_code: str
    timeframe: MarketTimeframe
    adjustment_type: AdjustmentType
    bar_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Decimal | None
    vwap: Decimal | None
    received_at: datetime
    quality_status: MarketDataQualityStatus


class MarketFreshnessResponse(BaseModel):
    source_code: str
    freshness_status: MarketDataQualityStatus
    latest_bar_time: datetime | None
    latest_received_at: datetime | None
    calculated_at: datetime


class MarketBarsResponse(BaseModel):
    source_code: str
    items: list[MarketBarResponse]
    freshness: MarketFreshnessResponse


class MarketLatestItemResponse(BaseModel):
    bar: MarketBarResponse
    freshness: MarketFreshnessResponse


class MarketLatestResponse(BaseModel):
    source_code: str
    items: list[MarketLatestItemResponse]


class MarketSyncRunResponse(BaseModel):
    id: UUID
    source_id: UUID
    trigger_type: SyncTriggerType
    status: MarketSyncStatus
    timeframe: MarketTimeframe
    adjustment_type: AdjustmentType
    requested_symbols: tuple[str, ...]
    started_at: datetime
    requested_start: datetime | None
    requested_end: datetime | None
    completed_at: datetime | None
    total_received: int
    total_inserted: int
    total_updated: int
    total_rejected: int
    error_summary: str | None
    correlation_id: UUID
    metadata: dict[str, object]


class DailyUpdateRequest(BaseModel):
    provider: str = Field(default="baostock", max_length=64)
    universe_key: str = Field(default="research", max_length=64)
    instrument_ids: list[UUID] = Field(default_factory=list, max_length=500)
    target_date: date | None = None
    max_instruments: int | None = Field(default=None, ge=1, le=500)
    dry_run: bool = True
    continue_on_error: bool = True


class DailyInstrumentPlanResponse(BaseModel):
    instrument_id: UUID
    symbol: str
    start_date: date
    target_date: date
    state: str


class DailyUpdateResponse(BaseModel):
    run: MarketSyncRunResponse | None
    target_date: date
    requested: int
    up_to_date: int
    completed: int
    failed: int
    unprocessed: int
    bars_fetched: int
    bars_inserted: int
    bars_updated: int
    bars_skipped: int
    invalid_bars: int
    retry_count: int
    failures: tuple[dict[str, str], ...]
    plans: tuple[DailyInstrumentPlanResponse, ...]
    dry_run: bool
    idempotent_replay: bool


class QualityRunRequest(BaseModel):
    universe_key: str = Field(default="research", max_length=64)
    provider: str = Field(default="baostock", max_length=64)
    max_instruments: int | None = Field(default=None, ge=1, le=500)
    range_start: datetime | None = None
    range_end: datetime | None = None


class MarketDataQualityRunResponse(BaseModel):
    id: UUID
    universe_key: str | None
    provider: str | None
    timeframe: MarketTimeframe
    status: MarketDataQualityRunStatus
    instruments_checked: int
    bars_checked: int
    issues_found: int
    error_count: int
    warning_count: int
    info_count: int
    started_at: datetime
    completed_at: datetime | None
    correlation_id: UUID
    metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class MarketDataQualityIssueResponse(BaseModel):
    id: UUID
    quality_run_id: UUID
    instrument_id: UUID | None
    issue_type: str
    severity: MarketDataIssueSeverity
    timeframe: MarketTimeframe
    first_affected_at: datetime | None
    last_affected_at: datetime | None
    observed_value: str | None
    expected_value: str | None
    message: str
    required_action: str | None
    metadata: dict[str, object]
    created_at: datetime


class QualityRunPageResponse(BaseModel):
    items: list[MarketDataQualityRunResponse]
    page: int
    page_size: int
    total: int


class QualityRunDetailResponse(BaseModel):
    run: MarketDataQualityRunResponse
    issues: list[MarketDataQualityIssueResponse]
    issue_page: int
    issue_page_size: int
    issue_total: int
    integrity_mismatches: tuple[str, ...]


class InstrumentCoverageResponse(BaseModel):
    instrument_id: UUID
    symbol: str
    name: str
    exchange: str
    bar_count: int
    earliest_bar: datetime | None
    latest_bar: datetime | None
    mapping_status: str
    missing_requirements: tuple[str, ...]


class UniverseCoverageResponse(BaseModel):
    universe_key: str
    name: str
    instrument_count: int
    instruments_with_data: int
    sufficient_instruments: int
    insufficient_instruments: int
    earliest_bar: datetime | None
    latest_bar: datetime | None
    latest_sync_at: datetime | None
    items: tuple[InstrumentCoverageResponse, ...]


class ReadinessCapabilityResponse(BaseModel):
    capability_key: str
    display_name: str
    status: MarketDataReadinessStatus
    ready_instrument_count: int
    total_instrument_count: int
    minimum_bars_required: int
    latest_data_date: date | None
    blocking_issue_count: int
    warning_count: int
    reason: str
    required_action: str
    code_status: str


class MarketDataOverviewResponse(BaseModel):
    instrument_count: int
    active_a_share_count: int
    research_universe_count: int
    market_bar_count: int
    earliest_bar: datetime | None
    latest_bar: datetime | None
    latest_sync_at: datetime | None
    provider: str
    timeframe: MarketTimeframe
    adjustment_type: AdjustmentType
    scanner_ready: bool
    strategy_ready: bool
    backtest_data_ready: bool
    backtest_code_status: str
