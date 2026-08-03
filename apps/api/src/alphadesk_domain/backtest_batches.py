"""Durable orchestration model for independent per-instrument backtests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from alphadesk_domain.values import as_utc, non_empty, utc_now


class BacktestBatchScope(StrEnum):
    WATCHLIST = "WATCHLIST"
    ALL_A_SHARES = "ALL_A_SHARES"


class BacktestBatchStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BacktestBatchItemStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_BATCH_STATUSES = frozenset(
    {
        BacktestBatchStatus.COMPLETED,
        BacktestBatchStatus.PARTIAL_FAILED,
        BacktestBatchStatus.FAILED,
        BacktestBatchStatus.CANCELLED,
    }
)


@dataclass(slots=True, kw_only=True)
class BacktestBatch:
    idempotency_key: str
    request_fingerprint: str
    scope: BacktestBatchScope
    name: str
    configuration: dict[str, Any]
    total_count: int
    id: UUID = field(default_factory=uuid4)
    watchlist_id: UUID | None = None
    status: BacktestBatchStatus = BacktestBatchStatus.CREATED
    pending_count: int = 0
    running_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    correlation_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.idempotency_key = non_empty(self.idempotency_key, "idempotency_key")
        self.request_fingerprint = non_empty(self.request_fingerprint, "request_fingerprint")
        self.name = non_empty(self.name, "name")
        if len(self.request_fingerprint) != 64:
            raise ValueError("request_fingerprint must be a SHA-256 digest")
        if self.total_count < 1:
            raise ValueError("total_count must be positive")
        counters = (
            self.pending_count,
            self.running_count,
            self.completed_count,
            self.failed_count,
            self.cancelled_count,
        )
        if any(value < 0 for value in counters):
            raise ValueError("batch counters must be non-negative")
        if sum(counters) != self.total_count:
            raise ValueError("batch counters must equal total_count")
        if self.scope is BacktestBatchScope.WATCHLIST and self.watchlist_id is None:
            raise ValueError("watchlist_id is required for WATCHLIST scope")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")
        if self.started_at is not None:
            self.started_at = as_utc(self.started_at, "started_at")
        if self.completed_at is not None:
            self.completed_at = as_utc(self.completed_at, "completed_at")

    @property
    def progress_percent(self) -> int:
        finished = self.completed_count + self.failed_count + self.cancelled_count
        return min(100, int(finished * 100 / self.total_count))


@dataclass(slots=True, kw_only=True)
class BacktestBatchItem:
    batch_id: UUID
    instrument_id: UUID
    ordinal: int
    id: UUID = field(default_factory=uuid4)
    status: BacktestBatchItemStatus = BacktestBatchItemStatus.PENDING
    backtest_run_id: UUID | None = None
    attempt_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        if self.attempt_count < 0:
            raise ValueError("attempt_count must be non-negative")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")
        if self.started_at is not None:
            self.started_at = as_utc(self.started_at, "started_at")
        if self.completed_at is not None:
            self.completed_at = as_utc(self.completed_at, "completed_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class BacktestBatchResultRow:
    item_id: UUID
    instrument_id: UUID
    symbol: str
    exchange: str
    name: str
    status: BacktestBatchItemStatus
    backtest_run_id: UUID | None
    total_return: str | None
    annualized_return: str | None
    maximum_drawdown: str | None
    sharpe_ratio: str | None
    fill_count: int | None
    bars_processed: int | None
    signals_generated: int | None
    candidate_session_count: int | None
    minute_replay_session_count: int | None
    processed_minute_bar_count: int | None
    data_preparation_summary: dict[str, Any] | None
    performance_summary: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
