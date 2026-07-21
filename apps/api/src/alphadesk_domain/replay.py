"""Framework-independent RT01 historical daily replay contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from alphadesk_domain.backtest import (
    BacktestClock,
    BacktestConfiguration,
    BacktestSession,
    backtest_configuration_from_dict,
    backtest_configuration_to_dict,
)
from alphadesk_domain.values import as_utc, non_empty, utc_now


class ReplayError(ValueError):
    """Controlled replay error safe to expose through API and CLI adapters."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReplayRunStatus(StrEnum):
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


TERMINAL_REPLAY_STATUSES = frozenset(
    {ReplayRunStatus.COMPLETED, ReplayRunStatus.STOPPED, ReplayRunStatus.FAILED}
)


class ReplaySpeedMode(StrEnum):
    MANUAL = "MANUAL"
    X1 = "X1"
    X10 = "X10"
    X100 = "X100"


class ReplayControlActionType(StrEnum):
    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STEP = "STEP"
    SET_SPEED = "SET_SPEED"
    STOP = "STOP"


class ReplayActorType(StrEnum):
    LOCAL_USER = "LOCAL_USER"
    SYSTEM = "SYSTEM"


class ReplayEventType(StrEnum):
    RUN_CREATED = "RUN_CREATED"
    RUN_READY = "RUN_READY"
    RUN_STARTED = "RUN_STARTED"
    RUN_PAUSED = "RUN_PAUSED"
    RUN_RESUMED = "RUN_RESUMED"
    RUN_SPEED_CHANGED = "RUN_SPEED_CHANGED"
    SESSION_STARTED = "SESSION_STARTED"
    OPEN_PHASE_COMPLETED = "OPEN_PHASE_COMPLETED"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    RISK_EVALUATED = "RISK_EVALUATED"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    EXECUTION_COMPLETED = "EXECUTION_COMPLETED"
    FILL_CREATED = "FILL_CREATED"
    EQUITY_UPDATED = "EQUITY_UPDATED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_STOPPED = "RUN_STOPPED"
    RUN_FAILED = "RUN_FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


_TRANSITIONS: Mapping[ReplayRunStatus, frozenset[ReplayRunStatus]] = {
    ReplayRunStatus.CREATED: frozenset({ReplayRunStatus.READY}),
    ReplayRunStatus.READY: frozenset({ReplayRunStatus.RUNNING, ReplayRunStatus.STOPPED}),
    ReplayRunStatus.RUNNING: frozenset(
        {
            ReplayRunStatus.PAUSED,
            ReplayRunStatus.COMPLETED,
            ReplayRunStatus.STOPPED,
            ReplayRunStatus.FAILED,
        }
    ),
    ReplayRunStatus.PAUSED: frozenset(
        {ReplayRunStatus.RUNNING, ReplayRunStatus.STOPPED, ReplayRunStatus.FAILED}
    ),
    ReplayRunStatus.COMPLETED: frozenset(),
    ReplayRunStatus.STOPPED: frozenset(),
    ReplayRunStatus.FAILED: frozenset(),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayConfiguration:
    """Replay wrapper around the shared BT01 execution configuration."""

    execution: BacktestConfiguration
    speed_mode: ReplaySpeedMode = ReplaySpeedMode.MANUAL
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReplayError("REPLAY_INVALID_CONFIGURATION", "unsupported replay schema_version")


def replay_configuration_to_dict(configuration: ReplayConfiguration) -> dict[str, Any]:
    return {
        "execution": backtest_configuration_to_dict(configuration.execution),
        "speed_mode": configuration.speed_mode.value,
        "schema_version": configuration.schema_version,
    }


def replay_configuration_from_dict(value: Mapping[str, Any]) -> ReplayConfiguration:
    execution = value.get("execution")
    if not isinstance(execution, Mapping):
        raise ReplayError("REPLAY_INVALID_CONFIGURATION", "execution configuration is missing")
    return ReplayConfiguration(
        execution=backtest_configuration_from_dict(execution),
        speed_mode=ReplaySpeedMode(str(value["speed_mode"])),
        schema_version=int(value["schema_version"]),
    )


def replay_request_fingerprint(configuration: ReplayConfiguration) -> str:
    encoded = json.dumps(
        replay_configuration_to_dict(configuration),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def replay_action_fingerprint(
    run_id: UUID,
    action_type: ReplayControlActionType,
    expected_run_version: int,
    requested_speed: ReplaySpeedMode | None,
) -> str:
    encoded = json.dumps(
        {
            "action_type": action_type.value,
            "expected_run_version": expected_run_version,
            "replay_run_id": str(run_id),
            "requested_speed": None if requested_speed is None else requested_speed.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(slots=True, kw_only=True)
class ReplayRun:
    idempotency_key: str
    request_fingerprint: str
    configuration: ReplayConfiguration
    correlation_id: UUID
    total_sessions: int
    id: UUID = field(default_factory=uuid4)
    account_id: UUID | None = None
    strategy_run_id: UUID | None = None
    status: ReplayRunStatus = ReplayRunStatus.CREATED
    row_version: int = 0
    current_session_date: date | None = None
    current_session_index: int = 0
    speed_mode: ReplaySpeedMode = ReplaySpeedMode.MANUAL
    bars_processed: int = 0
    signals_generated: int = 0
    orders_created: int = 0
    fills_generated: int = 0
    started_at: datetime | None = None
    paused_at: datetime | None = None
    completed_at: datetime | None = None
    stopped_at: datetime | None = None
    failed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    last_heartbeat_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    final_summary: Mapping[str, Any] = field(default_factory=dict)
    integrity_summary: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.idempotency_key = non_empty(self.idempotency_key, "idempotency_key")
        if len(self.idempotency_key) > 128:
            raise ReplayError("REPLAY_INVALID_CONFIGURATION", "idempotency key is too long")
        if self.request_fingerprint != replay_request_fingerprint(self.configuration):
            raise ReplayError("REPLAY_INVALID_CONFIGURATION", "request fingerprint mismatch")
        if self.total_sessions < 1 or not 0 <= self.current_session_index <= self.total_sessions:
            raise ReplayError("REPLAY_INVALID_CONFIGURATION", "session counters are invalid")
        if (
            self.row_version < 0
            or min(
                self.bars_processed,
                self.signals_generated,
                self.orders_created,
                self.fills_generated,
            )
            < 0
        ):
            raise ReplayError("REPLAY_INVALID_CONFIGURATION", "run counters are invalid")
        self.speed_mode = ReplaySpeedMode(self.speed_mode)
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")
        for name in (
            "started_at",
            "paused_at",
            "completed_at",
            "stopped_at",
            "failed_at",
            "last_heartbeat_at",
            "lease_expires_at",
        ):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, as_utc(value, name))

    def transition(self, target: ReplayRunStatus, occurred_at: datetime) -> None:
        if target not in _TRANSITIONS[self.status]:
            code = (
                "REPLAY_TERMINAL_STATE"
                if self.status in TERMINAL_REPLAY_STATUSES
                else "REPLAY_INVALID_TRANSITION"
            )
            detail = (
                f"terminal replay {self.status.value} cannot transition to {target.value}"
                if self.status in TERMINAL_REPLAY_STATUSES
                else f"cannot transition {self.status.value} to {target.value}"
            )
            raise ReplayError(code, detail)
        now = as_utc(occurred_at, "occurred_at")
        self.status = target
        self.row_version += 1
        self.updated_at = now
        if target is ReplayRunStatus.RUNNING:
            self.started_at = self.started_at or now
            self.paused_at = None
        elif target is ReplayRunStatus.PAUSED:
            self.paused_at = now
        elif target is ReplayRunStatus.COMPLETED:
            self.completed_at = now
        elif target is ReplayRunStatus.STOPPED:
            self.stopped_at = now
        elif target is ReplayRunStatus.FAILED:
            self.failed_at = now


class ReplayClock:
    """Session-granular façade over BT01's deterministic phase clock."""

    __slots__ = ("_sessions",)

    def __init__(self, sessions: Sequence[BacktestSession]) -> None:
        # Constructing BacktestClock applies BT01 ordering and duplicate-date validation.
        clock = BacktestClock(sessions)
        ordered: list[BacktestSession] = []
        while not clock.is_complete:
            session = clock.current_session
            if not ordered or ordered[-1].trading_date != session.trading_date:
                ordered.append(session)
            clock.advance()
        self._sessions = tuple(ordered)

    @property
    def total_sessions(self) -> int:
        return len(self._sessions)

    def session_at(self, index: int) -> BacktestSession:
        if index < 0 or index >= len(self._sessions):
            raise ReplayError("REPLAY_INVALID_TRANSITION", "replay clock is complete")
        return self._sessions[index]


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayControlAction:
    replay_run_id: UUID
    action_type: ReplayControlActionType
    idempotency_key: str
    request_fingerprint: str
    expected_run_version: int
    applied_run_version: int
    actor_type: ReplayActorType
    occurred_at: datetime
    correlation_id: UUID
    requested_speed: ReplaySpeedMode | None = None
    actor_id: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))
        if self.expected_run_version < 0 or self.applied_run_version < 0:
            raise ReplayError("REPLAY_INVALID_CONFIGURATION", "versions must be non-negative")
        expected = replay_action_fingerprint(
            self.replay_run_id,
            self.action_type,
            self.expected_run_version,
            self.requested_speed,
        )
        if expected != self.request_fingerprint:
            raise ReplayError("REPLAY_INVALID_CONFIGURATION", "action fingerprint mismatch")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayEvent:
    replay_run_id: UUID
    sequence_number: int
    event_type: ReplayEventType
    business_time: datetime
    occurred_at: datetime
    summary: str
    correlation_id: UUID
    payload: Mapping[str, Any] = field(default_factory=dict)
    instrument_id: UUID | None = None
    related_entity_type: str | None = None
    related_entity_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.sequence_number < 1:
            raise ReplayError("REPLAY_INVALID_CONFIGURATION", "event sequence must be positive")
        object.__setattr__(self, "business_time", as_utc(self.business_time, "business_time"))
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))
        object.__setattr__(self, "summary", non_empty(self.summary, "summary")[:256])
        encoded = json.dumps(self.payload, default=str, ensure_ascii=True)
        if len(encoded) > 16_384:
            raise ReplayError("REPLAY_INVALID_CONFIGURATION", "event payload is too large")

    def envelope(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "replay_id": str(self.replay_run_id),
            "sequence_number": self.sequence_number,
            "event_type": self.event_type.value,
            "business_time": self.business_time.isoformat(),
            "occurred_at": self.occurred_at.isoformat(),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaySessionResult:
    replay_run_id: UUID
    session_index: int
    session_date: date
    bars_processed: int
    signals_generated: int
    orders_created: int
    fills_generated: int
    total_equity: str
    completed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayIntegrityReport:
    replay_run_id: UUID
    ok: bool
    checked_at: datetime
    issues: tuple[str, ...]
    facts: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked_at", as_utc(self.checked_at, "checked_at"))


def replay_run_asdict(run: ReplayRun) -> dict[str, Any]:
    """Typed helper used only by safe transport adapters."""

    return asdict(run)
