"""Pydantic contracts for M03 instruments, watchlists, and market data."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataQualityStatus,
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
