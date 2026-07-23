"""SC01 public API contracts."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr

from alphadesk_domain.market_reference import PriceAdjustmentMode


class ScannerParameterResponse(BaseModel):
    name: str
    display_name: str
    unit: str | None
    type: str
    description: str
    required: bool
    nullable: bool
    default: str | int | bool | None
    min_value: str | int | None
    max_value: str | int | None


class ScannerCatalogResponse(BaseModel):
    scanner_key: str
    display_name: str
    description: str
    version: str
    supported_timeframes: list[str]
    schema_version: int
    parameters: list[ScannerParameterResponse]
    data_source: str
    default_universe: str
    execution_mode: str


class ScanUniverseFiltersBody(BaseModel):
    exclude_st: bool = True
    exclude_suspended: bool = True
    exclude_insufficient_history: bool = True
    exclude_bse: bool = False
    exclude_star_market: bool = False
    exclude_chinext: bool = False
    minimum_listing_trading_days: int | None = Field(default=None, ge=1, le=5000)
    excluded_instrument_ids: list[UUID] = Field(default_factory=list, max_length=500)


class ScanRunCreateBody(BaseModel):
    scanner_key: str = Field(min_length=2, max_length=64)
    parameters: dict[str, StrictStr | StrictInt | StrictBool | None] = Field(default_factory=dict)
    universe_type: str = "ALL_ACTIVE_A_SHARES"
    universe_filters: ScanUniverseFiltersBody = Field(default_factory=ScanUniverseFiltersBody)
    instrument_ids: list[UUID] = Field(default_factory=list, max_length=100)
    timeframe: str = "DAY_1"
    scan_date: date | None = None
    as_of: datetime | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW


class ScanRunResponse(BaseModel):
    scan_run_id: UUID
    scanner_key: str
    scanner_version: str
    parameters: dict[str, str | int | bool | None]
    universe_type: str
    instrument_ids: list[UUID]
    universe_filters: dict[str, Any]
    source_code: str
    timeframe: str
    as_of: datetime
    status: str
    current_phase: str
    progress_percent: int
    total_instruments: int
    excluded_instruments: int
    data_ready_instruments: int
    backfill_requested: int
    backfill_failed: int
    insufficient_history: int
    instruments_scanned: int
    matches_found: int
    failed_instruments: int
    cancel_requested: bool
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    error: dict[str, str] | None
    correlation_id: UUID
    created_at: datetime
    replayed: bool = False
    capabilities: dict[str, bool]
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW


class ScanRunPageResponse(BaseModel):
    items: list[ScanRunResponse]
    page: int
    page_size: int
    total: int


class ScanResultResponse(BaseModel):
    scan_result_id: UUID
    scan_run_id: UUID
    instrument_id: UUID
    instrument: dict[str, str]
    rank: int
    score: str
    matched_at: datetime
    reference_price: str
    reason_code: str
    reason: str
    metrics: dict[str, Any]
    schema_version: int
    created_at: datetime


class ScanResultListResponse(BaseModel):
    items: list[ScanResultResponse]
    total: int
    page: int = 1
    page_size: int = 50


class ScannerIntegrityResponse(BaseModel):
    scan_run_id: UUID
    valid: bool
    issues: list[dict[str, str]]


class ScannerSessionDefaultResponse(BaseModel):
    scan_date: date
    data_source: str = "MINIQMT"
    timeframe: str = "DAY_1"


class ScanRunMemberResponse(BaseModel):
    instrument_id: UUID
    symbol: str
    exchange: str
    instrument_name: str
    status: str
    reason_code: str | None
    reason: str | None
    bars_available: int
    required_bars: int


class ScanRunMemberListResponse(BaseModel):
    items: list[ScanRunMemberResponse]
    summary: dict[str, int]
    total: int


class ScanDataPreparationResponse(BaseModel):
    scan_run_id: UUID
    status: str
    data_source: str
    required_instruments: int
    ready_instruments: int
    backfill_requested: int
    backfill_failed: int
    insufficient_history: int
    member_summary: dict[str, int]
