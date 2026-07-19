"""SC01 public API contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr


class ScannerParameterResponse(BaseModel):
    name: str
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


class ScanRunCreateBody(BaseModel):
    scanner_key: str = Field(min_length=2, max_length=64)
    parameters: dict[str, StrictStr | StrictInt | StrictBool | None] = Field(default_factory=dict)
    instrument_ids: list[UUID] = Field(min_length=1, max_length=100)
    timeframe: str = "DAY_1"
    as_of: datetime
    idempotency_key: str = Field(min_length=1, max_length=128)


class ScanRunResponse(BaseModel):
    scan_run_id: UUID
    scanner_key: str
    scanner_version: str
    parameters: dict[str, str | int | bool | None]
    universe_type: str
    instrument_ids: list[UUID]
    timeframe: str
    as_of: datetime
    status: str
    instruments_scanned: int
    matches_found: int
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    error: dict[str, str] | None
    correlation_id: UUID
    created_at: datetime
    replayed: bool = False
    capabilities: dict[str, bool]


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


class ScannerIntegrityResponse(BaseModel):
    scan_run_id: UUID
    valid: bool
    issues: list[dict[str, str]]
