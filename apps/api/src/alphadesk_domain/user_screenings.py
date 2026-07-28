"""Versioned user-owned screening definitions for the SC02-C research workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class UserScreeningStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


@dataclass(slots=True, kw_only=True)
class UserScreeningDefinition:
    name: str
    origin: str
    id: UUID = field(default_factory=uuid4)
    description: str | None = None
    source_text: str | None = None
    current_version: int = 1
    status: UserScreeningStatus = UserScreeningStatus.ACTIVE
    last_used_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class UserScreeningVersion:
    screening_id: UUID
    version_number: int
    screening_spec: dict[str, object]
    summary: str
    id: UUID = field(default_factory=uuid4)
    source_text: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True, kw_only=True)
class UserScreeningRunLink:
    scan_run_id: UUID
    screening_id: UUID
    screening_version_id: UUID
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
