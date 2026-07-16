"""Strategy-run facts and historical-bar port for S01-B."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.strategy import (
    StrategyBar,
    StrategyEnvironment,
    StrategyParameterValue,
)
from alphadesk_domain.values import as_utc, non_empty, utc_now


class StrategyRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


type StoredStrategyParameter = str | int | bool


@dataclass(slots=True, kw_only=True)
class StrategyRun:
    idempotency_key: str
    request_fingerprint: str
    strategy_key: str
    strategy_version: str
    environment: StrategyEnvironment
    timeframe: MarketTimeframe
    start_at: datetime
    end_at: datetime
    parameters: dict[str, StoredStrategyParameter]
    instrument_ids: tuple[UUID, ...]
    status: StrategyRunStatus
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    strategy_id: UUID | None = None
    strategy_version_id: UUID | None = None
    bars_processed: int = 0
    signals_generated: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.idempotency_key = non_empty(self.idempotency_key, "idempotency_key")
        if len(self.idempotency_key) > 128:
            raise ValueError("idempotency_key must not exceed 128 characters")
        self.request_fingerprint = non_empty(self.request_fingerprint, "request_fingerprint")
        self.strategy_key = non_empty(self.strategy_key, "strategy_key")
        self.strategy_version = non_empty(self.strategy_version, "strategy_version")
        if self.environment is not StrategyEnvironment.RESEARCH:
            raise ValueError("S01-B strategy runs only support RESEARCH")
        self.start_at = as_utc(self.start_at, "start_at")
        self.end_at = as_utc(self.end_at, "end_at")
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be earlier than end_at")
        unique_ids = tuple(sorted(set(self.instrument_ids), key=str))
        if not unique_ids:
            raise ValueError("instrument_ids must not be empty")
        self.instrument_ids = unique_ids
        if self.bars_processed < 0 or self.signals_generated < 0:
            raise ValueError("run counters must be non-negative")
        for name in ("started_at", "completed_at", "failed_at"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, as_utc(value, name))
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")
        if self.error_message is not None and len(self.error_message) > 512:
            raise ValueError("error_message must not exceed 512 characters")

    def mark_running(self, occurred_at: datetime) -> None:
        if self.status is not StrategyRunStatus.CREATED:
            raise ValueError("only CREATED strategy runs can start")
        now = as_utc(occurred_at, "started_at")
        self.status = StrategyRunStatus.RUNNING
        self.started_at = now
        self.updated_at = now

    def mark_completed(self, occurred_at: datetime, bars: int, signals: int) -> None:
        if self.status is not StrategyRunStatus.RUNNING:
            raise ValueError("only RUNNING strategy runs can complete")
        now = as_utc(occurred_at, "completed_at")
        self.status = StrategyRunStatus.COMPLETED
        self.bars_processed = bars
        self.signals_generated = signals
        self.completed_at = now
        self.updated_at = now

    def mark_failed(self, occurred_at: datetime, code: str, message: str) -> None:
        now = as_utc(occurred_at, "failed_at")
        self.status = StrategyRunStatus.FAILED
        self.bars_processed = 0
        self.signals_generated = 0
        self.failed_at = now
        self.error_code = non_empty(code, "error_code")[:64]
        self.error_message = non_empty(message, "error_message")[:512]
        self.updated_at = now


class HistoricalBarProvider(Protocol):
    async def list_bars(
        self,
        *,
        instrument_ids: tuple[UUID, ...],
        timeframe: MarketTimeframe,
        start_at: datetime,
        end_at: datetime,
    ) -> list[StrategyBar]: ...


def stored_parameters(
    parameters: Mapping[str, StrategyParameterValue],
) -> dict[str, StoredStrategyParameter]:
    """Convert validated parameters to stable JSON-safe persisted values."""

    result: dict[str, StoredStrategyParameter] = {}
    for name, value in parameters.items():
        if isinstance(value, Decimal):
            result[name] = format(value.normalize(), "f")
        elif isinstance(value, bool | int | str):
            result[name] = value
        else:
            raise TypeError(f"unsupported stored strategy parameter: {name}")
    return result
