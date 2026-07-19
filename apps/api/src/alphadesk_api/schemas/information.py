"""N01 public API schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, StrictStr


class ThemeInputBody(BaseModel):
    theme_key: str = Field(min_length=1, max_length=128)
    theme_name: str = Field(min_length=1, max_length=256)


class ManualInformationBody(BaseModel):
    source_name: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=1024)
    content: str = Field(min_length=1, max_length=200_000)
    source_url: str | None = Field(default=None, max_length=2048)
    published_at: datetime | None = None
    instrument_ids: list[UUID] = Field(default_factory=list, max_length=100)
    themes: list[ThemeInputBody] = Field(default_factory=list, max_length=50)
    event_type: str = "OTHER"
    direction: str = "UNKNOWN"
    summary: str | None = Field(default=None, max_length=4000)
    importance: StrictStr | None = None


class InformationSourceResponse(BaseModel):
    source_id: UUID
    source_key: str
    display_name: str
    source_type: str
    base_url: str | None
    enabled: bool
    configuration: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class InformationIngestionRunResponse(BaseModel):
    ingestion_run_id: UUID
    source_id: UUID
    status: str
    fetched_count: int
    inserted_count: int
    duplicate_count: int
    failed_count: int
    started_at: datetime
    completed_at: datetime | None
    error_summary: str | None
    correlation_id: UUID


class InformationDetailResponse(BaseModel):
    item_id: UUID
    raw_document_id: UUID
    event_id: UUID
    source: InformationSourceResponse
    title: str
    content: str
    raw_title: str
    raw_content: str
    source_url: str | None
    published_at: datetime
    received_at: datetime
    event_type: str
    direction: str
    summary: str | None
    importance: str | None
    status: str
    instruments: list[dict[str, str]]
    themes: list[dict[str, str]]
    duplicate: bool = False
    capabilities: dict[str, bool]


class InformationPageResponse(BaseModel):
    items: list[InformationDetailResponse]
    page: int
    page_size: int
    total: int


class InformationIntegrityResponse(BaseModel):
    item_id: UUID
    valid: bool
    issues: list[dict[str, str]]
