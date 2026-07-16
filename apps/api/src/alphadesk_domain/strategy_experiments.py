"""S02-B1 batch research experiment facts and deterministic parameter grids."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from itertools import product
from uuid import UUID, uuid4

from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.strategy import (
    StrategyEnvironment,
    StrategyError,
    StrategyParameterDefinition,
    StrategyParameterValue,
    validate_strategy_parameters,
)
from alphadesk_domain.strategy_runs import StoredStrategyParameter, stored_parameters
from alphadesk_domain.values import as_utc, non_empty, utc_now


class StrategyExperimentStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"


type ParameterGrid = Mapping[str, Sequence[StrategyParameterValue]]
type StoredParameterGrid = dict[str, list[StoredStrategyParameter]]
type NormalizedParameterSet = dict[str, StoredStrategyParameter]


def _candidate_key(value: StrategyParameterValue) -> tuple[str, str]:
    if isinstance(value, Decimal):
        return ("decimal", format(value.normalize(), "f"))
    return (type(value).__name__, str(value))


def expand_parameter_grid(
    definitions: Sequence[StrategyParameterDefinition], supplied_grid: ParameterGrid
) -> list[NormalizedParameterSet]:
    """Expand candidates in definition order and validate every complete combination."""

    defined_names = {item.name for item in definitions}
    unknown = set(supplied_grid) - defined_names
    if unknown:
        raise StrategyError(
            "STRATEGY_EXPERIMENT_INVALID_GRID",
            f"unknown parameter '{sorted(unknown)[0]}'",
        )
    ordered_names: list[str] = []
    ordered_values: list[list[StrategyParameterValue]] = []
    for definition in definitions:
        if definition.name not in supplied_grid:
            continue
        candidates = supplied_grid[definition.name]
        if not isinstance(candidates, Sequence) or isinstance(candidates, str | bytes):
            raise StrategyError(
                "STRATEGY_EXPERIMENT_INVALID_GRID",
                f"parameter '{definition.name}' candidates must be a list",
            )
        if not candidates:
            raise StrategyError(
                "STRATEGY_EXPERIMENT_EMPTY_GRID",
                f"parameter '{definition.name}' candidates must not be empty",
            )
        unique: list[StrategyParameterValue] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            key = _candidate_key(candidate)
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        ordered_names.append(definition.name)
        ordered_values.append(unique)
    raw_combinations = product(*ordered_values) if ordered_values else [()]
    combinations: list[NormalizedParameterSet] = []
    for values in raw_combinations:
        supplied = dict(zip(ordered_names, values, strict=True))
        validated = validate_strategy_parameters(definitions, supplied)
        normalized = stored_parameters(validated)
        if not normalized:
            raise StrategyError(
                "STRATEGY_EXPERIMENT_NO_PARAMETER_COMBINATIONS",
                "strategy has no usable parameter combination",
            )
        combinations.append(normalized)
    if not combinations:
        raise StrategyError(
            "STRATEGY_EXPERIMENT_NO_PARAMETER_COMBINATIONS",
            "parameter grid produced no combinations",
        )
    return combinations


def normalized_parameter_grid(
    definitions: Sequence[StrategyParameterDefinition], supplied_grid: ParameterGrid
) -> StoredParameterGrid:
    """Persist only supplied candidates, deduplicated in definition order."""

    combinations = expand_parameter_grid(definitions, supplied_grid)
    result: StoredParameterGrid = {}
    for definition in definitions:
        if definition.name not in supplied_grid:
            continue
        seen: list[StoredStrategyParameter] = []
        for combination in combinations:
            value = combination[definition.name]
            if value not in seen:
                seen.append(value)
        result[definition.name] = seen
    return result


@dataclass(slots=True, kw_only=True)
class StrategyExperiment:
    idempotency_key: str
    request_fingerprint: str
    strategy_key: str
    strategy_version: str
    environment: StrategyEnvironment
    timeframe: MarketTimeframe
    instrument_ids: tuple[UUID, ...]
    start_at: datetime
    end_at: datetime
    parameter_grid: StoredParameterGrid
    combination_count: int
    status: StrategyExperimentStatus
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    runs_completed: int = 0
    runs_failed: int = 0
    total_signals: int = 0
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
            raise ValueError("strategy experiments only support RESEARCH")
        self.start_at = as_utc(self.start_at, "start_at")
        self.end_at = as_utc(self.end_at, "end_at")
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be earlier than end_at")
        self.instrument_ids = tuple(sorted(set(self.instrument_ids), key=str))
        if not self.instrument_ids:
            raise ValueError("instrument_ids must not be empty")
        if self.combination_count <= 0:
            raise ValueError("combination_count must be positive")
        if min(self.runs_completed, self.runs_failed, self.total_signals) < 0:
            raise ValueError("experiment counters must be non-negative")
        for name in ("started_at", "completed_at", "failed_at"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, as_utc(value, name))
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")
        if self.error_message is not None and len(self.error_message) > 512:
            raise ValueError("error_message must not exceed 512 characters")

    def mark_running(self, occurred_at: datetime) -> None:
        if self.status is not StrategyExperimentStatus.CREATED:
            raise ValueError("only CREATED experiments can start")
        now = as_utc(occurred_at, "started_at")
        self.status = StrategyExperimentStatus.RUNNING
        self.started_at = now
        self.updated_at = now

    def finish(self, occurred_at: datetime, *, completed: int, failed: int, signals: int) -> None:
        if self.status is not StrategyExperimentStatus.RUNNING:
            raise ValueError("only RUNNING experiments can finish")
        now = as_utc(occurred_at, "completed_at")
        self.runs_completed = completed
        self.runs_failed = failed
        self.total_signals = signals
        self.status = (
            StrategyExperimentStatus.COMPLETED
            if failed == 0
            else StrategyExperimentStatus.FAILED
            if completed == 0
            else StrategyExperimentStatus.PARTIAL_FAILED
        )
        if self.status is StrategyExperimentStatus.FAILED:
            self.failed_at = now
        else:
            self.completed_at = now
        self.updated_at = now


@dataclass(slots=True, kw_only=True)
class StrategyExperimentRun:
    experiment_id: UUID
    strategy_run_id: UUID
    combination_index: int
    normalized_parameters: NormalizedParameterSet
    child_idempotency_key: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.combination_index < 1:
            raise ValueError("combination_index must start at one")
        if not self.normalized_parameters:
            raise ValueError("normalized_parameters must not be empty")
        self.child_idempotency_key = non_empty(self.child_idempotency_key, "child_idempotency_key")
        if len(self.child_idempotency_key) > 128:
            raise ValueError("child_idempotency_key must not exceed 128 characters")
        self.created_at = as_utc(self.created_at, "created_at")
