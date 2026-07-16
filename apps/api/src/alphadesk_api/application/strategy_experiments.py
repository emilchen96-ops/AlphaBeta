"""S02-B1 synchronous batch research orchestration and read-only comparisons."""

from __future__ import annotations

import builtins
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.strategy_runner import StrategyRunner, StrategyRunRequest
from alphadesk_domain.entities import Signal
from alphadesk_domain.enums import MarketTimeframe, OrderSide
from alphadesk_domain.strategy import (
    StrategyEnvironment,
    StrategyError,
    StrategyParameterDefinition,
    StrategyParameterType,
    StrategyParameterValue,
    StrategyRegistry,
)
from alphadesk_domain.strategy_experiments import (
    NormalizedParameterSet,
    ParameterGrid,
    StrategyExperiment,
    StrategyExperimentRun,
    StrategyExperimentStatus,
    expand_parameter_grid,
    normalized_parameter_grid,
)
from alphadesk_domain.strategy_runs import StrategyRun, StrategyRunStatus
from alphadesk_domain.values import as_utc


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyExperimentRequest:
    idempotency_key: str
    strategy_key: str
    parameter_grid: ParameterGrid
    instrument_ids: tuple[UUID, ...]
    timeframe: MarketTimeframe
    start_at: datetime
    end_at: datetime
    correlation_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyExperimentResult:
    experiment: StrategyExperiment
    replayed: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ExperimentRunSummary:
    combination_index: int
    normalized_parameters: NormalizedParameterSet
    strategy_run_id: UUID
    run_status: str
    bars_processed: int
    total_signals: int
    buy_signals: int
    sell_signals: int
    first_signal_at: datetime | None
    last_signal_at: datetime | None
    signaled_instrument_count: int
    warning: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalOverlap:
    left_combination_index: int
    right_combination_index: int
    intersection_count: int
    union_count: int
    similarity: str


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyExperimentIntegrityReport:
    experiment_id: UUID
    issues: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(
    request: StrategyExperimentRequest,
    *,
    version: str,
    grid: Mapping[str, Sequence[str | int | bool]],
) -> str:
    payload = {
        "schema_version": 1,
        "strategy_key": request.strategy_key,
        "strategy_version": version,
        "timeframe": request.timeframe.value,
        "instrument_ids": sorted(str(item) for item in set(request.instrument_ids)),
        "start_at": as_utc(request.start_at, "start_at").isoformat(timespec="microseconds"),
        "end_at": as_utc(request.end_at, "end_at").isoformat(timespec="microseconds"),
        "parameter_grid": grid,
        "environment": StrategyEnvironment.RESEARCH.value,
    }
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _child_key(fingerprint: str, index: int, parameters: NormalizedParameterSet) -> str:
    parameter_hash = hashlib.sha256(_canonical_json(parameters).encode()).hexdigest()[:16]
    return f"s02:{fingerprint[:48]}:{index}:{parameter_hash}"


def _runtime_parameters(
    definitions: Sequence[StrategyParameterDefinition], stored: NormalizedParameterSet
) -> dict[str, StrategyParameterValue]:
    by_name = {item.name: item for item in definitions}
    result: dict[str, StrategyParameterValue] = {}
    for name, value in stored.items():
        definition = by_name[name]
        if definition.parameter_type is StrategyParameterType.DECIMAL:
            result[name] = Decimal(str(value))
        else:
            result[name] = value
    return result


def _translate_grid_error(exc: StrategyError) -> ApplicationError:
    code = (
        exc.code
        if exc.code.startswith("STRATEGY_EXPERIMENT_")
        else "STRATEGY_EXPERIMENT_INVALID_GRID"
    )
    return ApplicationError(code, str(exc))


class StrategyExperimentService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: StrategyRegistry,
        *,
        max_combinations: int = 50,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._runner = StrategyRunner(uow_factory, registry)
        self._max_combinations = max_combinations

    async def run(self, request: StrategyExperimentRequest) -> StrategyExperimentResult:
        try:
            metadata = self._registry.get(request.strategy_key)
        except StrategyError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        if request.timeframe not in metadata.supported_timeframes:
            raise ApplicationError(
                "STRATEGY_TIMEFRAME_NOT_SUPPORTED", "strategy does not support the timeframe"
            )
        if request.start_at.tzinfo is None or request.end_at.tzinfo is None:
            raise ApplicationError(
                "STRATEGY_INVALID_TIME_RANGE", "experiment timestamps must be timezone-aware"
            )
        if request.start_at >= request.end_at:
            raise ApplicationError(
                "STRATEGY_INVALID_TIME_RANGE", "start_at must be earlier than end_at"
            )
        definitions = self._registry.get_parameter_definitions(request.strategy_key)
        try:
            combinations = expand_parameter_grid(definitions, request.parameter_grid)
            grid = normalized_parameter_grid(definitions, request.parameter_grid)
            for combination in combinations:
                self._registry.create_instance(
                    request.strategy_key,
                    _runtime_parameters(definitions, combination),
                )
        except StrategyError as exc:
            raise _translate_grid_error(exc) from exc
        if len(combinations) > self._max_combinations:
            raise ApplicationError(
                "STRATEGY_EXPERIMENT_TOO_LARGE",
                "parameter grid exceeds the synchronous experiment limit",
                {"actual_count": len(combinations), "max_combinations": self._max_combinations},
            )
        fingerprint = _fingerprint(request, version=metadata.version, grid=grid)
        experiment = StrategyExperiment(
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            strategy_key=request.strategy_key,
            strategy_version=metadata.version,
            environment=StrategyEnvironment.RESEARCH,
            timeframe=request.timeframe,
            instrument_ids=request.instrument_ids,
            start_at=request.start_at,
            end_at=request.end_at,
            parameter_grid=grid,
            combination_count=len(combinations),
            status=StrategyExperimentStatus.CREATED,
            correlation_id=request.correlation_id or uuid4(),
        )
        async with self._uow_factory() as uow:
            existing = await uow.strategy_experiments.get_by_idempotency_key(
                request.idempotency_key
            )
            if existing is not None:
                return self._replay(existing, fingerprint)
            claimed = await uow.strategy_experiments.claim(experiment)
            if not claimed:
                existing = await uow.strategy_experiments.get_by_idempotency_key(
                    request.idempotency_key
                )
                if existing is None:
                    raise ApplicationError(
                        "STRATEGY_EXPERIMENT_RUN_FAILED", "experiment claim could not be resolved"
                    )
                return self._replay(existing, fingerprint)
            experiment.mark_running(datetime.now(UTC))
            await uow.strategy_experiments.update_status(experiment)
            await uow.commit()

        completed = failed = total_signals = 0
        for index, normalized in enumerate(combinations, start=1):
            child_key = _child_key(fingerprint, index, normalized)
            result = await self._runner.run(
                StrategyRunRequest(
                    idempotency_key=child_key,
                    strategy_key=request.strategy_key,
                    timeframe=request.timeframe,
                    start_at=request.start_at,
                    end_at=request.end_at,
                    instrument_ids=request.instrument_ids,
                    parameters=_runtime_parameters(definitions, normalized),
                    correlation_id=experiment.correlation_id,
                )
            )
            async with self._uow_factory() as link_uow:
                existing_link = await link_uow.strategy_experiment_runs.get_by_experiment_and_index(
                    experiment.id, index
                )
                if existing_link is None:
                    await link_uow.strategy_experiment_runs.append(
                        StrategyExperimentRun(
                            experiment_id=experiment.id,
                            strategy_run_id=result.run.id,
                            combination_index=index,
                            normalized_parameters=normalized,
                            child_idempotency_key=child_key,
                        )
                    )
                await link_uow.commit()
            if result.run.status is StrategyRunStatus.COMPLETED:
                completed += 1
                total_signals += result.run.signals_generated
            else:
                failed += 1

        async with self._uow_factory() as summary_uow:
            current = await summary_uow.strategy_experiments.get_for_update(experiment.id)
            if current is None:
                raise ApplicationError(
                    "STRATEGY_EXPERIMENT_NOT_FOUND", "strategy experiment does not exist"
                )
            current.finish(
                datetime.now(UTC), completed=completed, failed=failed, signals=total_signals
            )
            await summary_uow.strategy_experiments.update_status(current)
            await summary_uow.commit()
            return StrategyExperimentResult(experiment=current)

    @staticmethod
    def _replay(existing: StrategyExperiment, fingerprint: str) -> StrategyExperimentResult:
        if existing.request_fingerprint != fingerprint:
            raise ApplicationError(
                "STRATEGY_EXPERIMENT_IDEMPOTENCY_CONFLICT",
                "idempotency key was already used for another experiment",
            )
        return StrategyExperimentResult(experiment=existing, replayed=True)


class StrategyExperimentQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, experiment_id: UUID) -> StrategyExperiment:
        async with self._uow_factory() as uow:
            experiment = await uow.strategy_experiments.get_by_id(experiment_id)
        if experiment is None:
            raise ApplicationError(
                "STRATEGY_EXPERIMENT_NOT_FOUND", "strategy experiment does not exist"
            )
        return experiment

    async def list(
        self,
        *,
        strategy_key: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[builtins.list[StrategyExperiment], int]:
        async with self._uow_factory() as uow:
            return await uow.strategy_experiments.list(
                strategy_key=strategy_key,
                status=status,
                offset=offset,
                limit=limit,
            )

    async def list_runs(self, experiment_id: UUID) -> builtins.list[ExperimentRunSummary]:
        async with self._uow_factory() as uow:
            experiment = await uow.strategy_experiments.get_by_id(experiment_id)
            if experiment is None:
                raise ApplicationError(
                    "STRATEGY_EXPERIMENT_NOT_FOUND", "strategy experiment does not exist"
                )
            links = await uow.strategy_experiment_runs.list_by_experiment(experiment_id)
            summaries: builtins.list[ExperimentRunSummary] = []
            for link in links:
                run = await uow.strategy_runs.get_by_id(link.strategy_run_id)
                if run is None:
                    raise ApplicationError(
                        "STRATEGY_EXPERIMENT_INTEGRITY_MISMATCH",
                        "experiment references a missing strategy run",
                    )
                signals, _ = await uow.signals.list_by_run(run.id, 0, 10_000)
                summaries.append(_summary(link, run, signals))
            return summaries

    async def comparison(self, experiment_id: UUID) -> builtins.list[ExperimentRunSummary]:
        return await self.list_runs(experiment_id)

    async def signal_overlap(self, experiment_id: UUID) -> builtins.list[SignalOverlap]:
        summaries = await self.list_runs(experiment_id)
        async with self._uow_factory() as uow:
            sets: dict[int, set[tuple[UUID, datetime, str]]] = {}
            for summary in summaries:
                signals, _ = await uow.signals.list_by_run(summary.strategy_run_id, 0, 10_000)
                sets[summary.combination_index] = {
                    (item.instrument_id, item.bar_timestamp, item.signal_type.value)
                    for item in signals
                    if item.bar_timestamp is not None
                }
        result: builtins.list[SignalOverlap] = []
        indexes = sorted(sets)
        for left_position, left in enumerate(indexes):
            for right in indexes[left_position + 1 :]:
                intersection = len(sets[left] & sets[right])
                union = len(sets[left] | sets[right])
                similarity = Decimal("1") if union == 0 else Decimal(intersection) / Decimal(union)
                result.append(
                    SignalOverlap(
                        left_combination_index=left,
                        right_combination_index=right,
                        intersection_count=intersection,
                        union_count=union,
                        similarity=format(similarity.normalize(), "f"),
                    )
                )
        return result


def _summary(
    link: StrategyExperimentRun, run: StrategyRun, signals: Sequence[Signal]
) -> ExperimentRunSummary:
    timestamps = sorted(item.generated_at for item in signals)
    return ExperimentRunSummary(
        combination_index=link.combination_index,
        normalized_parameters=dict(link.normalized_parameters),
        strategy_run_id=run.id,
        run_status=run.status.value,
        bars_processed=run.bars_processed,
        total_signals=len(signals),
        buy_signals=sum(item.side is OrderSide.BUY for item in signals),
        sell_signals=sum(item.side is OrderSide.SELL for item in signals),
        first_signal_at=timestamps[0] if timestamps else None,
        last_signal_at=timestamps[-1] if timestamps else None,
        signaled_instrument_count=len({item.instrument_id for item in signals}),
        warning=run.error_code if run.status is StrategyRunStatus.FAILED else None,
    )


class StrategyExperimentIntegrityService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def check(self, experiment_id: UUID) -> StrategyExperimentIntegrityReport:
        async with self._uow_factory() as uow:
            experiment = await uow.strategy_experiments.get_by_id(experiment_id)
            if experiment is None:
                raise ApplicationError(
                    "STRATEGY_EXPERIMENT_NOT_FOUND", "strategy experiment does not exist"
                )
            links = await uow.strategy_experiment_runs.list_by_experiment(experiment_id)
            issues: list[str] = []
            if len(links) != experiment.combination_count:
                issues.append("COMBINATION_COUNT_MISMATCH")
            if [item.combination_index for item in links] != list(range(1, len(links) + 1)):
                issues.append("COMBINATION_INDEX_INVALID")
            if len({item.child_idempotency_key for item in links}) != len(links):
                issues.append("CHILD_IDEMPOTENCY_DUPLICATE")
            completed = failed = total_signals = 0
            for link in links:
                run = await uow.strategy_runs.get_by_id(link.strategy_run_id)
                if run is None:
                    issues.append("STRATEGY_RUN_MISSING")
                    continue
                if (
                    run.strategy_key != experiment.strategy_key
                    or run.strategy_version != experiment.strategy_version
                ):
                    issues.append("STRATEGY_IDENTITY_MISMATCH")
                if (
                    run.start_at != experiment.start_at
                    or run.end_at != experiment.end_at
                    or run.instrument_ids != experiment.instrument_ids
                ):
                    issues.append("STRATEGY_RUN_SCOPE_MISMATCH")
                if run.parameters != link.normalized_parameters:
                    issues.append("PARAMETER_ASSOCIATION_MISMATCH")
                if run.status is StrategyRunStatus.COMPLETED:
                    completed += 1
                    total_signals += await uow.signals.count_by_run(run.id)
                else:
                    failed += 1
            if completed + failed != experiment.combination_count:
                issues.append("RUN_COUNTER_SCOPE_MISMATCH")
            if (
                completed != experiment.runs_completed
                or failed != experiment.runs_failed
                or total_signals != experiment.total_signals
            ):
                issues.append("EXPERIMENT_SUMMARY_MISMATCH")
            expected_status = (
                StrategyExperimentStatus.COMPLETED
                if failed == 0
                else StrategyExperimentStatus.FAILED
                if completed == 0
                else StrategyExperimentStatus.PARTIAL_FAILED
            )
            if experiment.status != expected_status:
                issues.append("EXPERIMENT_STATUS_MISMATCH")
        return StrategyExperimentIntegrityReport(
            experiment_id=experiment_id, issues=tuple(dict.fromkeys(issues))
        )
