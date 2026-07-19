"""Framework-independent N01 information facts and normalization rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from alphadesk_domain.values import as_utc, non_empty, utc_now


class InformationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InformationSourceType(StrEnum):
    MANUAL = "MANUAL"
    RSS = "RSS"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    OTHER = "OTHER"


class InformationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class InformationIngestionStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MarketEventType(StrEnum):
    COMPANY_ANNOUNCEMENT = "COMPANY_ANNOUNCEMENT"
    COMPANY_NEWS = "COMPANY_NEWS"
    INDUSTRY = "INDUSTRY"
    MACRO = "MACRO"
    REGULATION = "REGULATION"
    PRODUCT = "PRODUCT"
    EARNINGS = "EARNINGS"
    OTHER = "OTHER"


class MarketEventDirection(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class MarketEventStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str, field_name: str) -> str:
    normalized = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip()
    return non_empty(normalized, field_name)


def normalized_content_hash(title: str, content: str) -> str:
    canonical = f"{normalize_text(title, 'title')}\n{normalize_text(content, 'content')}"
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(slots=True, kw_only=True)
class InformationSource:
    source_key: str
    display_name: str
    source_type: InformationSourceType
    id: UUID = field(default_factory=uuid4)
    base_url: str | None = None
    enabled: bool = True
    configuration: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.source_key = non_empty(self.source_key, "source_key")
        self.display_name = non_empty(self.display_name, "display_name")
        if self.base_url is not None:
            self.base_url = non_empty(self.base_url, "base_url")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class RawDocument:
    source_id: UUID
    title: str
    raw_content: str
    received_at: datetime
    content_hash: str
    id: UUID = field(default_factory=uuid4)
    external_id: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    language: str = "zh-CN"
    metadata: dict[str, Any] = field(default_factory=dict)
    ingestion_run_id: UUID | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("title must not be empty")
        if not self.raw_content.strip():
            raise ValueError("raw_content must not be empty")
        if len(self.content_hash) != 64:
            raise ValueError("content_hash must be SHA-256 hex")
        if self.external_id is not None:
            object.__setattr__(self, "external_id", non_empty(self.external_id, "external_id"))
        if self.source_url is not None:
            object.__setattr__(self, "source_url", non_empty(self.source_url, "source_url"))
        object.__setattr__(self, "received_at", as_utc(self.received_at, "received_at"))
        if self.published_at is not None:
            object.__setattr__(self, "published_at", as_utc(self.published_at, "published_at"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class InformationItem:
    raw_document_id: UUID
    normalized_title: str
    normalized_content: str
    published_at: datetime
    received_at: datetime
    status: InformationStatus = InformationStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_title", normalize_text(self.normalized_title, "title"))
        object.__setattr__(
            self, "normalized_content", normalize_text(self.normalized_content, "content")
        )
        object.__setattr__(self, "published_at", as_utc(self.published_at, "published_at"))
        object.__setattr__(self, "received_at", as_utc(self.received_at, "received_at"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketEvent:
    information_item_id: UUID
    event_type: MarketEventType
    title: str
    event_at: datetime
    direction: MarketEventDirection = MarketEventDirection.UNKNOWN
    status: MarketEventStatus = MarketEventStatus.ACTIVE
    id: UUID = field(default_factory=uuid4)
    summary: str | None = None
    importance: Decimal | None = None
    schema_version: int = 1
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", normalize_text(self.title, "title"))
        if self.summary is not None:
            object.__setattr__(self, "summary", normalize_text(self.summary, "summary"))
        if self.importance is not None and (
            not isinstance(self.importance, Decimal)
            or not self.importance.is_finite()
            or not Decimal("0") <= self.importance <= Decimal("1")
        ):
            raise ValueError("importance must be a finite Decimal between zero and one")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        object.__setattr__(self, "event_at", as_utc(self.event_at, "event_at"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class EventInstrumentLink:
    event_id: UUID
    instrument_id: UUID
    relation_type: str = "RELATED"
    confidence: Decimal | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "relation_type", non_empty(self.relation_type, "relation_type"))
        if self.confidence is not None and (
            not isinstance(self.confidence, Decimal)
            or not self.confidence.is_finite()
            or not Decimal("0") <= self.confidence <= Decimal("1")
        ):
            raise ValueError("confidence must be a finite Decimal between zero and one")
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class EventThemeLink:
    event_id: UUID
    theme_key: str
    theme_name: str
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "theme_key", non_empty(self.theme_key, "theme_key"))
        object.__setattr__(self, "theme_name", non_empty(self.theme_name, "theme_name"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))


@dataclass(slots=True, kw_only=True)
class InformationIngestionRun:
    source_id: UUID
    status: InformationIngestionStatus
    started_at: datetime
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    fetched_count: int = 0
    inserted_count: int = 0
    duplicate_count: int = 0
    failed_count: int = 0
    completed_at: datetime | None = None
    error_summary: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if any(
            value < 0
            for value in (
                self.fetched_count,
                self.inserted_count,
                self.duplicate_count,
                self.failed_count,
            )
        ):
            raise ValueError("ingestion counters must be non-negative")
        self.started_at = as_utc(self.started_at, "started_at")
        if self.completed_at is not None:
            self.completed_at = as_utc(self.completed_at, "completed_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")

    def complete(
        self,
        occurred_at: datetime,
        *,
        inserted: int,
        duplicates: int,
        failed: int,
    ) -> None:
        now = as_utc(occurred_at, "occurred_at")
        self.status = InformationIngestionStatus.COMPLETED
        self.inserted_count = inserted
        self.duplicate_count = duplicates
        self.failed_count = failed
        self.completed_at = now
        self.updated_at = now

    def fail(self, occurred_at: datetime, message: str) -> None:
        now = as_utc(occurred_at, "occurred_at")
        self.status = InformationIngestionStatus.FAILED
        self.failed_count = max(1, self.failed_count)
        self.completed_at = now
        self.error_summary = non_empty(message, "error_summary")[:512]
        self.updated_at = now


@dataclass(frozen=True, slots=True, kw_only=True)
class RawDocumentDraft:
    title: str
    content: str
    external_id: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    language: str = "zh-CN"
    metadata: dict[str, Any] = field(default_factory=dict)
