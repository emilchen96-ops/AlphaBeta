"""S01-B synchronous historical strategy runner and read-only query services."""

from __future__ import annotations

import builtins
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_domain.entities import Instrument, Signal
from alphadesk_domain.enums import MarketTimeframe, SignalStatus
from alphadesk_domain.strategy import (
    SignalDraft,
    StrategyContext,
    StrategyEnvironment,
    StrategyError,
    StrategyParameterValue,
    StrategyRegistry,
)
from alphadesk_domain.strategy_runs import (
    StrategyRun,
    StrategyRunStatus,
    stored_parameters,
)
from alphadesk_domain.values import as_utc


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyRunRequest:
    idempotency_key: str
    strategy_key: str
    timeframe: MarketTimeframe
    start_at: datetime
    end_at: datetime
    instrument_ids: tuple[UUID, ...]
    parameters: Mapping[str, StrategyParameterValue]
    correlation_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyRunResult:
    run: StrategyRun
    signals: tuple[Signal, ...]
    replayed: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyRunIntegrityReport:
    run_id: UUID
    persisted_signal_count: int
    expected_signal_count: int
    issues: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyRunDto:
    id: UUID
    idempotency_key: str
    strategy_key: str
    strategy_version: str
    timeframe: MarketTimeframe
    start_at: datetime
    end_at: datetime
    status: StrategyRunStatus
    bars_processed: int
    signals_generated: int
    correlation_id: UUID
    instrument_ids: tuple[UUID, ...]
    parameters: dict[str, str | int | bool]
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    error_code: str | None
    error_message: str | None
    instruments: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategySignalDto:
    id: UUID
    run_id: UUID
    sequence_number: int
    instrument_id: UUID
    strategy_key: str
    strategy_version: str
    generated_at: datetime
    bar_timestamp: datetime
    signal_type: str
    side: str
    symbol: str | None
    exchange: str | None
    instrument_name: str | None
    quantity: str | None
    target_weight: str | None
    reference_price: str | None
    confidence: str | None
    reason: str | None
    schema_version: int


def _run_dto(run: StrategyRun, instruments: Sequence[Instrument] | None = None) -> StrategyRunDto:
    return StrategyRunDto(
        id=run.id,
        idempotency_key=run.idempotency_key,
        strategy_key=run.strategy_key,
        strategy_version=run.strategy_version,
        timeframe=run.timeframe,
        start_at=run.start_at,
        end_at=run.end_at,
        status=run.status,
        bars_processed=run.bars_processed,
        signals_generated=run.signals_generated,
        correlation_id=run.correlation_id,
        instrument_ids=run.instrument_ids,
        parameters=dict(run.parameters),
        started_at=run.started_at,
        completed_at=run.completed_at,
        failed_at=run.failed_at,
        created_at=run.created_at,
        error_code=run.error_code,
        error_message=run.error_message,
        instruments=tuple(
            {
                "id": str(item.id),
                "symbol": item.symbol,
                "exchange": item.exchange,
                "name": item.name,
            }
            for item in (instruments or [])
        ),
    )


def _signal_dto(signal: Signal, instrument: Instrument | None = None) -> StrategySignalDto:
    if (
        signal.strategy_run_id is None
        or signal.sequence_number is None
        or signal.strategy_key is None
        or signal.strategy_version is None
        or signal.bar_timestamp is None
    ):
        raise ApplicationError(
            "STRATEGY_RUN_INTEGRITY_INVALID", "persisted strategy signal lacks provenance"
        )
    return StrategySignalDto(
        id=signal.id,
        run_id=signal.strategy_run_id,
        sequence_number=signal.sequence_number,
        instrument_id=signal.instrument_id,
        strategy_key=signal.strategy_key,
        strategy_version=signal.strategy_version,
        generated_at=signal.generated_at,
        bar_timestamp=signal.bar_timestamp,
        signal_type=signal.signal_type.value,
        side=signal.side.value,
        symbol=getattr(instrument, "symbol", None),
        exchange=getattr(instrument, "exchange", None),
        instrument_name=getattr(instrument, "name", None),
        quantity=None if signal.target_quantity is None else str(signal.target_quantity),
        target_weight=None if signal.target_weight is None else str(signal.target_weight),
        reference_price=None if signal.reference_price is None else str(signal.reference_price),
        confidence=None if signal.confidence is None else str(signal.confidence),
        reason=signal.reason,
        schema_version=signal.schema_version,
    )


def _fingerprint_payload(
    request: StrategyRunRequest,
    *,
    version: str,
    parameters: Mapping[str, StrategyParameterValue],
) -> str:
    payload = {
        "strategy_key": request.strategy_key,
        "strategy_version": version,
        "timeframe": request.timeframe.value,
        "start_at": as_utc(request.start_at, "start_at").isoformat(timespec="microseconds"),
        "end_at": as_utc(request.end_at, "end_at").isoformat(timespec="microseconds"),
        "instrument_ids": sorted(str(item) for item in set(request.instrument_ids)),
        "parameters": stored_parameters(parameters),
        "environment": StrategyEnvironment.RESEARCH.value,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_signal_draft(
    draft: SignalDraft,
    *,
    run: StrategyRun,
    current_bar_instrument_id: UUID,
    current_bar_timestamp: datetime,
    expected_generated_at: datetime | None = None,
) -> None:
    if draft.strategy_key != run.strategy_key or draft.strategy_version != run.strategy_version:
        raise StrategyError("STRATEGY_INVALID_SIGNAL", "signal strategy identity differs from run")
    if draft.instrument_id != current_bar_instrument_id:
        raise StrategyError("STRATEGY_INVALID_SIGNAL", "signal instrument differs from current bar")
    if draft.bar_timestamp != current_bar_timestamp:
        raise StrategyError("STRATEGY_INVALID_SIGNAL", "signal bar time differs from current bar")
    if draft.generated_at != (expected_generated_at or current_bar_timestamp):
        raise StrategyError("STRATEGY_INVALID_SIGNAL", "signal generation time is invalid")


def persisted_signal_from_draft(
    run: StrategyRun,
    draft: SignalDraft,
    sequence: int,
    *,
    account_id: UUID | None = None,
) -> Signal:
    return Signal(
        strategy_id=run.strategy_id,
        strategy_version_id=run.strategy_version_id,
        account_id=account_id,
        instrument_id=draft.instrument_id,
        signal_type=draft.signal_type,
        side=draft.side,
        target_quantity=draft.quantity,
        target_weight=draft.target_weight,
        reference_price=draft.reference_price,
        generated_at=draft.generated_at,
        valid_until=run.end_at,
        reason=draft.reason,
        status=SignalStatus.CREATED,
        correlation_id=run.correlation_id,
        payload={},
        strategy_run_id=run.id,
        sequence_number=sequence,
        strategy_key=run.strategy_key,
        strategy_version=run.strategy_version,
        bar_timestamp=draft.bar_timestamp,
        confidence=draft.confidence,
        metadata=dict(draft.metadata),
        schema_version=draft.schema_version,
    )


def _safe_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, StrategyError):
        return exc.code, str(exc)[:512]
    if isinstance(exc, ApplicationError):
        return exc.code, exc.message[:512]
    return "STRATEGY_EXECUTION_ERROR", "strategy run failed"


class StrategyRunner:
    def __init__(self, uow_factory: UnitOfWorkFactory, registry: StrategyRegistry) -> None:
        self._uow_factory = uow_factory
        self._registry = registry

    async def run(self, request: StrategyRunRequest) -> StrategyRunResult:
        metadata = self._registry.get(request.strategy_key)
        if request.timeframe not in metadata.supported_timeframes:
            raise ApplicationError(
                "STRATEGY_TIMEFRAME_NOT_SUPPORTED", "strategy does not support the timeframe"
            )
        parameters = self._registry.validate_parameters(request.strategy_key, request.parameters)
        fingerprint = _fingerprint_payload(request, version=metadata.version, parameters=parameters)
        run = StrategyRun(
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            strategy_key=request.strategy_key,
            strategy_version=metadata.version,
            environment=StrategyEnvironment.RESEARCH,
            timeframe=request.timeframe,
            start_at=request.start_at,
            end_at=request.end_at,
            parameters=stored_parameters(parameters),
            instrument_ids=request.instrument_ids,
            status=StrategyRunStatus.CREATED,
            correlation_id=request.correlation_id or uuid4(),
        )

        try:
            async with self._uow_factory() as uow:
                existing = await uow.strategy_runs.get_by_idempotency_key(request.idempotency_key)
                if existing is not None:
                    if existing.request_fingerprint != fingerprint:
                        raise ApplicationError(
                            "STRATEGY_RUN_IDEMPOTENCY_CONFLICT",
                            "idempotency key was already used for another strategy run",
                        )
                    existing_signals, _ = await uow.signals.list_by_run(existing.id, 0, 10_000)
                    return StrategyRunResult(
                        run=existing,
                        signals=tuple(existing_signals),
                        replayed=True,
                        warnings=("NO_MARKET_DATA",)
                        if existing.status is StrategyRunStatus.COMPLETED
                        and existing.bars_processed == 0
                        else (),
                    )

                strategy_record = await uow.strategies.get_by_business_key(request.strategy_key)
                run.strategy_id = None if strategy_record is None else strategy_record.id
                await uow.strategy_runs.add(run)
                now = datetime.now(UTC)
                run.mark_running(now)
                await uow.strategy_runs.update(run)

                strategy = self._registry.create_instance(request.strategy_key, parameters)
                context = StrategyContext(
                    strategy_key=run.strategy_key,
                    strategy_version=run.strategy_version,
                    run_id=run.id,
                    current_time=run.start_at,
                    parameters=parameters,
                    environment=StrategyEnvironment.RESEARCH,
                )
                strategy.initialize(context)
                bars = await uow.historical_bars.list_bars(
                    instrument_ids=run.instrument_ids,
                    timeframe=run.timeframe,
                    start_at=run.start_at,
                    end_at=run.end_at,
                )
                signals: list[Signal] = []
                for bar in bars:
                    context.advance_time(bar.timestamp)
                    for draft in strategy.on_bar(context, bar):
                        validate_signal_draft(
                            draft,
                            run=run,
                            current_bar_instrument_id=bar.instrument_id,
                            current_bar_timestamp=bar.timestamp,
                        )
                        signals.append(persisted_signal_from_draft(run, draft, len(signals) + 1))
                strategy.finalize(context)
                await uow.signals.append_many(signals)
                run.mark_completed(datetime.now(UTC), len(bars), len(signals))
                await uow.strategy_runs.update(run)
                await uow.commit()
                return StrategyRunResult(
                    run=run,
                    signals=tuple(signals),
                    warnings=("NO_MARKET_DATA",) if not bars else (),
                )
        except ApplicationError:
            raise
        except Exception as exc:
            code, message = _safe_failure(exc)
            run.mark_failed(datetime.now(UTC), code, message)
            async with self._uow_factory() as failure_uow:
                existing = await failure_uow.strategy_runs.get_by_idempotency_key(
                    run.idempotency_key
                )
                if existing is not None:
                    if existing.request_fingerprint != fingerprint:
                        raise ApplicationError(
                            "STRATEGY_RUN_IDEMPOTENCY_CONFLICT",
                            "idempotency key was already used for another strategy run",
                        ) from exc
                    signals, _ = await failure_uow.signals.list_by_run(existing.id, 0, 10_000)
                    return StrategyRunResult(run=existing, signals=tuple(signals), replayed=True)
                await failure_uow.strategy_runs.add(run)
                await failure_uow.commit()
            return StrategyRunResult(run=run, signals=())


class StrategyRunQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, run_id: UUID) -> StrategyRunDto | None:
        async with self._uow_factory() as uow:
            run = await uow.strategy_runs.get_by_id(run_id)
            if run is None:
                return None
            instruments = await uow.instruments.get_many(list(run.instrument_ids))
            return _run_dto(run, instruments)

    async def list(
        self,
        *,
        strategy_key: str | None = None,
        status: str | None = None,
        instrument_id: UUID | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[builtins.list[StrategyRunDto], int]:
        async with self._uow_factory() as uow:
            runs, total = await uow.strategy_runs.list(
                strategy_key=strategy_key,
                status=status,
                instrument_id=instrument_id,
                created_from=created_from,
                created_to=created_to,
                offset=offset,
                limit=limit,
            )
            return [_run_dto(item) for item in runs], total

    async def list_signals(
        self,
        run_id: UUID,
        offset: int = 0,
        limit: int = 100,
        signal_type: str | None = None,
    ) -> tuple[builtins.list[StrategySignalDto], int]:
        async with self._uow_factory() as uow:
            run = await uow.strategy_runs.get_by_id(run_id)
            if run is None:
                raise ApplicationError("STRATEGY_RUN_NOT_FOUND", "strategy run does not exist")
            signals, total = await uow.signals.list_by_run(run_id, offset, limit, signal_type)
            instruments = await uow.instruments.get_many(
                list({item.instrument_id for item in signals})
            )
            by_id = {item.id: item for item in instruments}
            return [_signal_dto(item, by_id.get(item.instrument_id)) for item in signals], total

    async def list_all_signals(
        self,
        *,
        strategy_run_id: UUID | None = None,
        strategy_key: str | None = None,
        instrument_id: UUID | None = None,
        signal_type: str | None = None,
        generated_from: datetime | None = None,
        generated_to: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[builtins.list[StrategySignalDto], int]:
        async with self._uow_factory() as uow:
            signals, total = await uow.signals.list_filtered(
                strategy_run_id=strategy_run_id,
                strategy_key=strategy_key,
                instrument_id=instrument_id,
                signal_type=signal_type,
                generated_from=generated_from,
                generated_to=generated_to,
                offset=offset,
                limit=limit,
            )
            instruments = await uow.instruments.get_many(
                list({item.instrument_id for item in signals})
            )
            by_id = {item.id: item for item in instruments}
            return [_signal_dto(item, by_id.get(item.instrument_id)) for item in signals], total

    async def check_integrity(self, run_id: UUID) -> StrategyRunIntegrityReport:
        async with self._uow_factory() as uow:
            run = await uow.strategy_runs.get_by_id(run_id)
            if run is None:
                raise ApplicationError("STRATEGY_RUN_NOT_FOUND", "strategy run does not exist")
            signals, count = await uow.signals.list_by_run(run_id, 0, 10_000)
        issues: list[str] = []
        if count != run.signals_generated:
            issues.append("SIGNAL_COUNT_MISMATCH")
        expected_sequences = list(range(1, count + 1))
        if [item.sequence_number for item in signals] != expected_sequences:
            issues.append("SIGNAL_SEQUENCE_INVALID")
        if any(
            item.strategy_key != run.strategy_key
            or item.strategy_version != run.strategy_version
            or item.correlation_id != run.correlation_id
            for item in signals
        ):
            issues.append("SIGNAL_PROVENANCE_MISMATCH")
        return StrategyRunIntegrityReport(
            run_id=run_id,
            persisted_signal_count=count,
            expected_signal_count=run.signals_generated,
            issues=tuple(issues),
        )
