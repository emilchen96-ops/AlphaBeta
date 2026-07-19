"""SC01 synchronous scanner orchestration and read-only query services."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.scanners import (
    Scanner,
    ScannerContext,
    ScannerError,
    ScannerMetadata,
    ScannerParameterValue,
    ScannerRegistry,
    ScanResult,
    ScanRun,
    ScanRunStatus,
    scanner_request_fingerprint,
    stored_scanner_metrics,
    stored_scanner_parameters,
)
from alphadesk_domain.strategy import StrategyBar
from alphadesk_domain.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True, kw_only=True)
class ScannerRunRequest:
    scanner_key: str
    parameters: Mapping[str, ScannerParameterValue]
    instrument_ids: tuple[UUID, ...]
    timeframe: MarketTimeframe
    as_of: datetime
    idempotency_key: str
    correlation_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class ScannerRunOutcome:
    run: ScanRun
    results: tuple[ScanResult, ...]
    replayed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ScanResultDto:
    result: ScanResult
    symbol: str
    exchange: str
    instrument_name: str


def _catalog_item(metadata: ScannerMetadata) -> dict[str, Any]:
    return {
        "scanner_key": metadata.scanner_key,
        "display_name": metadata.display_name,
        "description": metadata.description,
        "version": metadata.version,
        "supported_timeframes": [item.value for item in metadata.supported_timeframes],
        "schema_version": metadata.schema_version,
        "parameters": [
            {
                "name": item.name,
                "type": item.parameter_type.value,
                "description": item.description,
                "required": item.required,
                "nullable": item.nullable,
                "default": _json_parameter(item.default),
                "min_value": _json_parameter(item.min_value),
                "max_value": _json_parameter(item.max_value),
            }
            for item in metadata.parameter_definitions
        ],
    }


def _json_parameter(value: object) -> object:
    return format(value.normalize(), "f") if isinstance(value, Decimal) else value


class ScannerCatalogService:
    def __init__(self, registry: ScannerRegistry) -> None:
        self._registry = registry

    def list(self) -> list[dict[str, Any]]:
        return [_catalog_item(item) for item in self._registry.list_metadata()]


class ScannerRunService:
    def __init__(self, uow_factory: UnitOfWorkFactory, registry: ScannerRegistry) -> None:
        self._uow_factory = uow_factory
        self._registry = registry

    async def run(self, request: ScannerRunRequest) -> ScannerRunOutcome:
        scanner, validated, instrument_ids, as_of = self._validate_request(request)
        stored_parameters = stored_scanner_parameters(validated)
        fingerprint = scanner_request_fingerprint(
            {
                "schema_version": 1,
                "scanner_key": scanner.metadata.scanner_key,
                "scanner_version": scanner.metadata.version,
                "parameters": stored_parameters,
                "instrument_ids": [str(item) for item in instrument_ids],
                "timeframe": request.timeframe.value,
                "as_of": as_of.isoformat(),
            }
        )
        async with self._uow_factory() as uow:
            existing = await uow.scan_runs.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ApplicationError(
                        "SCAN_RUN_IDEMPOTENCY_CONFLICT",
                        "idempotency key belongs to a different scanner request",
                    )
                results = await uow.scan_results.list_by_run(existing.id)
                return ScannerRunOutcome(run=existing, results=tuple(results), replayed=True)
            instruments = await self._load_instruments(uow, instrument_ids)
            run = ScanRun(
                scanner_key=scanner.metadata.scanner_key,
                scanner_version=scanner.metadata.version,
                parameters=stored_parameters,
                universe_type="INSTRUMENTS",
                instrument_ids=instrument_ids,
                timeframe=request.timeframe,
                as_of=as_of,
                status=ScanRunStatus.CREATED,
                idempotency_key=request.idempotency_key,
                request_fingerprint=fingerprint,
                correlation_id=request.correlation_id,
            )
            run.mark_running(datetime.now(UTC))
            await uow.scan_runs.add(run)
            await uow.commit()
        try:
            results = await self._execute(run, scanner, validated, instruments)
        except (ScannerError, RuntimeError, ValueError) as exc:
            await self._mark_failed(run.id, "SCAN_RUN_FAILED", "scanner execution failed")
            raise ApplicationError("SCAN_RUN_FAILED", "scanner execution failed") from exc
        return ScannerRunOutcome(run=run, results=tuple(results), replayed=False)

    def _validate_request(
        self, request: ScannerRunRequest
    ) -> tuple[Scanner, dict[str, ScannerParameterValue], tuple[UUID, ...], datetime]:
        try:
            scanner = self._registry.create(request.scanner_key)
            validated = scanner.validate_parameters(request.parameters)
        except ScannerError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        if request.timeframe is not MarketTimeframe.DAY_1:
            raise ApplicationError("SCANNER_TIMEFRAME_NOT_SUPPORTED", "SC01 only supports DAY_1")
        if request.as_of.tzinfo is None:
            raise ApplicationError("SCANNER_INVALID_AS_OF", "as_of must be timezone-aware")
        instrument_ids = tuple(sorted(set(request.instrument_ids), key=str))
        if not instrument_ids:
            raise ApplicationError("SCANNER_INVALID_UNIVERSE", "instrument_ids must not be empty")
        return scanner, validated, instrument_ids, request.as_of.astimezone(UTC)

    async def _load_instruments(
        self, uow: UnitOfWork, instrument_ids: tuple[UUID, ...]
    ) -> tuple[Instrument, ...]:
        instruments = await uow.instruments.get_many(list(instrument_ids))
        by_id = {item.id: item for item in instruments}
        if set(by_id) != set(instrument_ids):
            raise ApplicationError(
                "SCANNER_INSTRUMENT_NOT_FOUND", "one or more instruments do not exist"
            )
        ordered = tuple(by_id[item] for item in instrument_ids)
        if any(
            not item.is_active or item.asset_type not in {"EQUITY", "STOCK"} for item in ordered
        ):
            raise ApplicationError(
                "SCANNER_INVALID_UNIVERSE", "SC01 only scans active A-share equities"
            )
        return ordered

    async def _execute(
        self,
        run: ScanRun,
        scanner: Scanner,
        validated: dict[str, ScannerParameterValue],
        instruments: tuple[Instrument, ...],
    ) -> list[ScanResult]:
        async with self._uow_factory() as uow:
            bars = await uow.historical_bars.list_bars(
                instrument_ids=run.instrument_ids,
                timeframe=run.timeframe,
                start_at=datetime(1970, 1, 1, tzinfo=UTC),
                end_at=run.as_of + timedelta(microseconds=1),
            )
            grouped: dict[UUID, list[StrategyBar]] = {item.id: [] for item in instruments}
            for bar in bars:
                if bar.instrument_id in grouped:
                    grouped[bar.instrument_id].append(bar)
            context = ScannerContext(as_of=run.as_of, timeframe=run.timeframe, parameters=validated)
            candidates = []
            for instrument in instruments:
                candidate = scanner.scan(context, instrument, grouped[instrument.id])
                if candidate is not None:
                    candidates.append(candidate)
            candidates.sort(key=lambda item: (-item.score, str(item.instrument_id)))
            now = datetime.now(UTC)
            results = [
                ScanResult(
                    scan_run_id=run.id,
                    instrument_id=item.instrument_id,
                    rank=index,
                    score=item.score,
                    matched_at=item.matched_at,
                    reference_price=item.reference_price,
                    reason_code=item.reason_code,
                    reason=item.reason,
                    metrics=stored_scanner_metrics(item.metrics),
                    created_at=now,
                )
                for index, item in enumerate(candidates, start=1)
            ]
            await uow.scan_results.append_many(results)
            run.mark_completed(now, len(instruments), len(results))
            await uow.scan_runs.update(run)
            await uow.commit()
            return results

    async def _mark_failed(self, run_id: UUID, code: str, message: str) -> None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_by_id(run_id)
            if run is not None:
                run.mark_failed(datetime.now(UTC), code, message)
                await uow.scan_runs.update(run)
                await uow.commit()


class ScannerQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get(self, run_id: UUID) -> ScanRun | None:
        async with self._uow_factory() as uow:
            return await uow.scan_runs.get_by_id(run_id)

    async def list_runs(
        self,
        *,
        scanner_key: str | None,
        status: str | None,
        instrument_id: UUID | None,
        created_from: datetime | None,
        created_to: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ScanRun], int]:
        async with self._uow_factory() as uow:
            return await uow.scan_runs.list(
                scanner_key=scanner_key,
                status=status,
                instrument_id=instrument_id,
                created_from=created_from,
                created_to=created_to,
                offset=offset,
                limit=limit,
            )

    async def results(self, run_id: UUID) -> list[ScanResultDto]:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_by_id(run_id)
            if run is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "scan run does not exist")
            results = await uow.scan_results.list_by_run(run_id)
            instruments = await uow.instruments.get_many([item.instrument_id for item in results])
            by_id = {item.id: item for item in instruments}
            return [
                ScanResultDto(
                    result=item,
                    symbol=by_id[item.instrument_id].symbol,
                    exchange=by_id[item.instrument_id].exchange,
                    instrument_name=by_id[item.instrument_id].name,
                )
                for item in results
                if item.instrument_id in by_id
            ]


class ScannerIntegrityService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def verify(self, run_id: UUID) -> list[dict[str, str]]:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_by_id(run_id)
            if run is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "scan run does not exist")
            results = await uow.scan_results.list_by_run(run_id)
        issues: list[dict[str, str]] = []
        if run.matches_found != len(results):
            issues.append({"code": "RESULT_COUNT_MISMATCH", "message": "result count differs"})
        if [item.rank for item in results] != list(range(1, len(results) + 1)):
            issues.append({"code": "RANK_SEQUENCE_INVALID", "message": "ranks are not continuous"})
        ids = [item.instrument_id for item in results]
        if len(ids) != len(set(ids)):
            issues.append({"code": "DUPLICATE_INSTRUMENT", "message": "instrument repeats"})
        for item in results:
            if item.instrument_id not in run.instrument_ids:
                issues.append(
                    {"code": "INSTRUMENT_OUTSIDE_UNIVERSE", "message": str(item.instrument_id)}
                )
            if item.matched_at > run.as_of:
                issues.append({"code": "MATCH_AFTER_AS_OF", "message": str(item.id)})
            if item.score < 0 or not item.score.is_finite():
                issues.append({"code": "INVALID_SCORE", "message": str(item.id)})
            for name, value in item.metrics.items():
                if not isinstance(value, str | int | bool) and value is not None:
                    issues.append({"code": "INVALID_METRIC", "message": f"{item.id}:{name}"})
        return issues
