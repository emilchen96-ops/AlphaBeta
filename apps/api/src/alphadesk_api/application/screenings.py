# ruff: noqa: RUF001
"""SC02-A durable all-A-share screening orchestration."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from time import perf_counter
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.scanners import BackfillEnqueuer, FullMarketScannerProcessor
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.scanners import (
    ScanMemberStatus,
    ScanResult,
    ScanRun,
    ScanRunMember,
    ScanRunStatus,
    ScanUniverseType,
    is_st_instrument,
    scanner_request_fingerprint,
)
from alphadesk_domain.screening import (
    ConditionCatalog,
    ConditionOutcome,
    RankingDirection,
    RankingRule,
    RuleBasedScreeningEngine,
    ScreeningCandidate,
    ScreeningCondition,
    ScreeningError,
    ScreeningSpec,
    UniverseSpec,
)
from alphadesk_domain.strategy import StrategyBar

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreeningRunOutcome:
    run: ScanRun
    replayed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseResolution:
    included: tuple[Instrument, ...]
    excluded: tuple[tuple[Instrument, str, str], ...]
    trading_statuses: Mapping[UUID, str]

    @property
    def total(self) -> int:
        return len(self.included) + len(self.excluded)


class PointInTimeAshareUniverseService:
    """Resolve the SSE/SZSE/BSE membership that existed on one historical date."""

    def __init__(self, uow_factory: UnitOfWorkFactory, *, source_code: str = "MINIQMT") -> None:
        self._uow_factory = uow_factory
        self._source_code = source_code.strip().upper()

    async def resolve(self, as_of_date: date, universe_spec: UniverseSpec) -> UniverseResolution:
        async with self._uow_factory() as uow:
            instruments = await uow.instruments.list_point_in_time_ashares(
                as_of_date=as_of_date,
                source_code=self._source_code,
            )
            statuses = await uow.instrument_trading_statuses.list(
                instrument_ids=[item.id for item in instruments],
                start=as_of_date,
                end=as_of_date,
                limit=max(len(instruments) * 2, 10_000),
            )
        status_by_id = {item.instrument_id: item.status.value for item in statuses}
        manual = set(universe_spec.excluded_instrument_ids)
        included: list[Instrument] = []
        excluded: list[tuple[Instrument, str, str]] = []
        for instrument in instruments:
            reason: tuple[str, str] | None = None
            if universe_spec.exclude_bse and instrument.exchange == "BSE":
                reason = ("BSE_EXCLUDED", "已按设置排除北交所股票")
            elif universe_spec.exclude_star_market and instrument.symbol.startswith(("688", "689")):
                reason = ("STAR_MARKET_EXCLUDED", "已按设置排除科创板股票")
            elif universe_spec.exclude_chinext and instrument.symbol.startswith(("300", "301")):
                reason = ("CHINEXT_EXCLUDED", "已按设置排除创业板股票")
            elif universe_spec.exclude_st and is_st_instrument(instrument):
                reason = ("ST_EXCLUDED", "已按设置排除ST及*ST股票")
            elif instrument.id in manual:
                reason = ("MANUAL_EXCLUDED", "已由用户手动排除")
            if reason is None:
                included.append(instrument)
            else:
                excluded.append((instrument, *reason))
        return UniverseResolution(
            included=tuple(included),
            excluded=tuple(excluded),
            trading_statuses=status_by_id,
        )


class ScreeningRunService:
    """Validate and enqueue a durable screening job without blocking for execution."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        catalog: ConditionCatalog,
        *,
        source_code: str = "MINIQMT",
    ) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog
        self._source_code = source_code.strip().upper()

    async def enqueue(
        self,
        spec: ScreeningSpec,
        *,
        correlation_id: UUID,
        idempotency_key: str | None,
    ) -> ScreeningRunOutcome:
        try:
            validated = spec.validate(self._catalog)
            snapshot = spec.snapshot(self._catalog)
        except ScreeningError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        await self._validate_date(spec.as_of_date)
        key = idempotency_key or f"screening:{uuid4()}"
        fingerprint = scanner_request_fingerprint(snapshot)
        primary = validated.conditions[0].definition
        primary_parameters = validated.conditions[0].parameters
        universe_snapshot = snapshot["universe_spec"]
        if not isinstance(universe_snapshot, Mapping):
            raise ApplicationError("SCREENING_SPEC_INVALID", "股票池快照无效")
        async with self._uow_factory() as uow:
            existing = await uow.scan_runs.get_by_idempotency_key(key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ApplicationError(
                        "SCREENING_IDEMPOTENCY_CONFLICT",
                        "幂等键已用于不同的筛选请求",
                    )
                return ScreeningRunOutcome(run=existing, replayed=True)
            run = ScanRun(
                scanner_key=(
                    primary.condition_key if len(validated.conditions) == 1 else "SCREENING_SPEC"
                ),
                scanner_version=primary.version,
                parameters={
                    name: (format(value.normalize(), "f") if isinstance(value, Decimal) else value)
                    for name, value in primary_parameters.items()
                },
                screening_spec=snapshot,
                universe_type=ScanUniverseType.ALL_ACTIVE_A_SHARES.value,
                universe_filters={
                    **dict(universe_snapshot),
                    "exclusions": snapshot["exclusions"],
                },
                instrument_ids=(),
                source_code=self._source_code,
                timeframe=MarketTimeframe.DAY_1,
                as_of=datetime.combine(spec.as_of_date, time(15), SHANGHAI).astimezone(UTC),
                status=ScanRunStatus.QUEUED,
                idempotency_key=key,
                request_fingerprint=fingerprint,
                correlation_id=correlation_id,
                price_adjustment_mode=PriceAdjustmentMode.RAW,
            )
            await uow.scan_runs.add(run)
            await uow.commit()
        return ScreeningRunOutcome(run=run, replayed=False)

    async def _validate_date(self, value: date) -> None:
        async with self._uow_factory() as uow:
            sessions = await uow.trading_calendar.list(
                exchange="SHSE", start=value, end=value, limit=1
            )
        if not sessions or not sessions[0].is_open:
            raise ApplicationError(
                "SCREENING_DATE_NOT_TRADING_DAY",
                "筛选日期不是已登记的A股交易日",
            )


class RuleBasedScreeningProcessor:
    """Execute one SC02-A job from PostgreSQL facts in bounded batches."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        catalog: ConditionCatalog,
        *,
        source_code: str = "MINIQMT",
        batch_size: int = 250,
    ) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog
        self._source_code = source_code.strip().upper()
        self._batch_size = max(1, min(batch_size, 1_000))
        self._universe = PointInTimeAshareUniverseService(
            uow_factory, source_code=self._source_code
        )

    async def process(self, run_id: UUID) -> None:
        started = perf_counter()
        run = await self._get_run(run_id)
        if not run.screening_spec:
            raise ApplicationError("SCREENING_SPEC_MISSING", "筛选任务缺少Spec快照")
        spec = screening_spec_from_snapshot(run.screening_spec)
        try:
            validated = spec.validate(self._catalog)
        except ScreeningError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        if run.cancel_requested:
            await self._mark_canceled(run.id)
            return
        await self._mark_phase(run.id, ScanRunStatus.RESOLVING, 5)
        resolution = await self._universe.resolve(spec.as_of_date, spec.universe_spec)
        if not resolution.included:
            raise ApplicationError("SCREENING_EMPTY_UNIVERSE", "应用排除条件后没有可筛选的A股")
        members = [
            ScanRunMember(
                scan_run_id=run.id,
                instrument_id=item.id,
                symbol=item.symbol,
                exchange=item.exchange,
                instrument_name=item.name,
                status=ScanMemberStatus.INCLUDED,
                required_bars=validated.required_history_bars,
            )
            for item in resolution.included
        ]
        members.extend(
            ScanRunMember(
                scan_run_id=run.id,
                instrument_id=item.id,
                symbol=item.symbol,
                exchange=item.exchange,
                instrument_name=item.name,
                status=ScanMemberStatus.EXCLUDED,
                reason_code=reason_code,
                reason=reason,
                required_bars=validated.required_history_bars,
            )
            for item, reason_code, reason in resolution.excluded
        )
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            await uow.scan_run_members.upsert_many(members)
            locked.instrument_ids = tuple(item.id for item in resolution.included)
            locked.total_instruments = resolution.total
            locked.excluded_instruments = len(resolution.excluded)
            locked.query_count = 2
            locked.mark_phase(ScanRunStatus.CHECKING_DATA, datetime.now(UTC), progress_percent=15)
            await uow.scan_runs.update(locked)
            await uow.commit()
        run = await self._get_run(run.id)
        start_at = run.as_of - timedelta(days=max(validated.required_history_bars * 3, 180))
        async with self._uow_factory() as uow:
            bars = await uow.historical_bars.list_authoritative_bars(
                instrument_ids=run.instrument_ids,
                timeframe=MarketTimeframe.DAY_1,
                start_at=start_at,
                end_at=run.as_of + timedelta(microseconds=1),
                source_code=self._source_code,
                price_adjustment_mode=PriceAdjustmentMode.RAW,
            )
        grouped: dict[UUID, list[StrategyBar]] = {
            instrument.id: [] for instrument in resolution.included
        }
        for market_bar in bars:
            if market_bar.instrument_id in grouped:
                grouped[market_bar.instrument_id].append(market_bar)
        for values in grouped.values():
            values.sort(key=lambda market_bar: market_bar.timestamp)
        await self._mark_running(run.id, bars_read=len(bars))
        engine = RuleBasedScreeningEngine(self._catalog)
        candidates: list[ScreeningCandidate] = []
        insufficient = 0
        indeterminate = 0
        failed = 0
        ready = 0
        processed = 0
        by_member = {item.instrument_id: item for item in members}
        included = list(resolution.included)
        for offset in range(0, len(included), self._batch_size):
            batch = included[offset : offset + self._batch_size]
            for instrument in batch:
                item_bars = grouped[instrument.id]
                member = by_member[instrument.id]
                member.bars_available = len(item_bars)
                latest_is_as_of = bool(item_bars) and (
                    item_bars[-1].timestamp.astimezone(SHANGHAI).date() == spec.as_of_date
                )
                if len(item_bars) < validated.required_history_bars or not latest_is_as_of:
                    member.status = ScanMemberStatus.DATA_MISSING
                    member.reason_code = "INSUFFICIENT_HISTORY"
                    member.reason = "历史日线不足或缺少筛选日日线"
                    insufficient += 1
                    processed += 1
                    continue
                ready += 1
                try:
                    outcome = engine.evaluate_instrument(
                        spec,
                        instrument,
                        item_bars,
                        trading_status=resolution.trading_statuses.get(instrument.id),
                    )
                except Exception as exc:
                    member.status = ScanMemberStatus.FAILED
                    member.reason_code = "CONDITION_EVALUATION_FAILED"
                    member.reason = f"该股票规则计算失败：{str(exc)[:300]}"
                    failed += 1
                    processed += 1
                    continue
                if outcome.outcome is ConditionOutcome.MATCHED and outcome.candidate:
                    member.status = ScanMemberStatus.MATCHED
                    candidates.append(outcome.candidate)
                elif outcome.outcome is ConditionOutcome.INSUFFICIENT_DATA:
                    member.status = ScanMemberStatus.DATA_MISSING
                    member.reason_code = outcome.reason_code
                    member.reason = outcome.reason
                    insufficient += 1
                    ready -= 1
                elif outcome.outcome is ConditionOutcome.INDETERMINATE:
                    member.status = ScanMemberStatus.INDETERMINATE
                    member.reason_code = outcome.reason_code
                    member.reason = outcome.reason
                    indeterminate += 1
                elif outcome.outcome is ConditionOutcome.FAILED:
                    member.status = ScanMemberStatus.FAILED
                    member.reason_code = outcome.reason_code
                    member.reason = outcome.reason
                    failed += 1
                else:
                    member.status = ScanMemberStatus.SCANNED
                    member.reason_code = outcome.reason_code
                    member.reason = outcome.reason
                processed += 1
            await self._update_progress(
                run.id,
                processed=processed,
                total=len(included),
                ready=ready,
                insufficient=insufficient,
                indeterminate=indeterminate,
                failed=failed,
                matched=len(candidates),
                batch_count=(offset // self._batch_size) + 1,
                elapsed_ms=int((perf_counter() - started) * 1_000),
            )
            current = await self._get_run(run.id)
            if current.cancel_requested:
                await self._mark_canceled(run.id)
                return
        ranked = engine.rank(spec, candidates)
        now = datetime.now(UTC)
        results: list[ScanResult] = []
        for rank, ranked_candidate in enumerate(ranked, start=1):
            metrics = dict(ranked_candidate.metrics)
            metrics["rank"] = rank
            reason = ranked_candidate.reason
            if "volume_multiple" in metrics:
                reason = f"{reason}；成交量倍数排名第{rank}"
            results.append(
                ScanResult(
                    scan_run_id=run.id,
                    instrument_id=ranked_candidate.instrument_id,
                    rank=rank,
                    score=ranked_candidate.score,
                    matched_at=run.as_of,
                    reference_price=ranked_candidate.reference_price,
                    reason_code=ranked_candidate.reason_code,
                    reason=reason,
                    metrics=metrics,
                    schema_version=1,
                    created_at=now,
                )
            )
        elapsed_ms = int((perf_counter() - started) * 1_000)
        memory_bytes = (
            sys.getsizeof(bars)
            + sum(sys.getsizeof(market_bar) for market_bar in bars)
            + sys.getsizeof(grouped)
        )
        final_members = list(by_member.values())
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            await uow.scan_results.append_many(results)
            await uow.scan_run_members.upsert_many(final_members)
            locked.data_ready_instruments = ready
            locked.insufficient_history = insufficient
            locked.indeterminate_count = indeterminate
            locked.failed_instruments = failed
            locked.instruments_scanned = processed
            locked.matches_found = len(results)
            locked.elapsed_ms = elapsed_ms
            locked.batch_count = max(1, (len(included) + self._batch_size - 1) // self._batch_size)
            locked.query_count = 3
            locked.bars_read = len(bars)
            locked.execution_stats = {
                "as_of_date": spec.as_of_date.isoformat(),
                "universe_count": resolution.total,
                "included_count": len(included),
                "market_bar_query_count": 1,
                "universe_query_count": 2,
                "query_count": 3,
                "bars_read": len(bars),
                "batch_count": locked.batch_count,
                "elapsed_ms": elapsed_ms,
                "estimated_memory_bytes": memory_bytes,
                "no_n_plus_one": True,
                "future_bars_read": 0,
                "feature_version": "sc02a-v1",
            }
            if insufficient or indeterminate or failed:
                locked.mark_partial_failed(now, processed, len(results))
            else:
                locked.mark_completed(now, processed, len(results))
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _get_run(self, run_id: UUID) -> ScanRun:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_by_id(run_id)
        if run is None:
            raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
        return run

    async def _mark_phase(self, run_id: UUID, status: ScanRunStatus, progress: int) -> None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            run.mark_phase(status, datetime.now(UTC), progress_percent=progress)
            await uow.scan_runs.update(run)
            await uow.commit()

    async def _mark_running(self, run_id: UUID, *, bars_read: int) -> None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            run.mark_running(datetime.now(UTC))
            run.progress_percent = 20
            run.query_count = 3
            run.bars_read = bars_read
            await uow.scan_runs.update(run)
            await uow.commit()

    async def _update_progress(
        self,
        run_id: UUID,
        *,
        processed: int,
        total: int,
        ready: int,
        insufficient: int,
        indeterminate: int,
        failed: int,
        matched: int,
        batch_count: int,
        elapsed_ms: int,
    ) -> None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            run.instruments_scanned = processed
            run.data_ready_instruments = ready
            run.insufficient_history = insufficient
            run.indeterminate_count = indeterminate
            run.failed_instruments = failed
            run.matches_found = matched
            run.batch_count = batch_count
            run.elapsed_ms = elapsed_ms
            run.progress_percent = 20 + int(processed / max(total, 1) * 79)
            run.updated_at = datetime.now(UTC)
            await uow.scan_runs.update(run)
            await uow.commit()

    async def _mark_canceled(self, run_id: UUID) -> None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is not None:
                run.mark_canceled(datetime.now(UTC))
                await uow.scan_runs.update(run)
                await uow.commit()

    async def fail(self, run_id: UUID, exc: Exception) -> None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is not None and run.status not in {
                ScanRunStatus.COMPLETED,
                ScanRunStatus.PARTIAL,
                ScanRunStatus.PARTIAL_FAILED,
                ScanRunStatus.CANCELED,
            }:
                run.mark_failed(
                    datetime.now(UTC),
                    "SCREENING_RUN_FAILED",
                    f"规则筛选任务执行失败：{str(exc)[:400]}",
                )
                await uow.scan_runs.update(run)
                await uow.commit()


class UnifiedScannerWorkerProcessor:
    """Route old SC01 runs and new SC02-A specs through one claim loop."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        legacy_processor: FullMarketScannerProcessor,
        screening_processor: RuleBasedScreeningProcessor,
    ) -> None:
        self._uow_factory = uow_factory
        self._legacy = legacy_processor
        self._screening = screening_processor

    async def process_next(self, enqueue_backfill: BackfillEnqueuer) -> UUID | None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_next_pending(
                (
                    ScanRunStatus.QUEUED,
                    ScanRunStatus.RESOLVING,
                    ScanRunStatus.CHECKING_DATA,
                    ScanRunStatus.BACKFILLING,
                    ScanRunStatus.RUNNING,
                )
            )
            if run is None:
                return None
            run_id = run.id
            is_screening = bool(run.screening_spec)
        try:
            if is_screening:
                await self._screening.process(run_id)
            else:
                await self._legacy.process(run_id, enqueue_backfill)
        except Exception as exc:
            if is_screening:
                await self._screening.fail(run_id, exc)
            else:
                await self._legacy._fail(run_id, exc)
        return run_id


def screening_spec_from_snapshot(payload: Mapping[str, object]) -> ScreeningSpec:
    try:
        universe_value = payload["universe_spec"]
        conditions_value = payload["conditions"]
        ranking_value = payload.get("ranking_rules", [])
        exclusions_value = payload.get("exclusions", {})
        if not isinstance(universe_value, Mapping):
            raise TypeError("universe_spec must be an object")
        if not isinstance(conditions_value, list) or not isinstance(ranking_value, list):
            raise TypeError("conditions and ranking_rules must be arrays")
        if not isinstance(exclusions_value, Mapping):
            raise TypeError("exclusions must be an object")
        universe_raw = dict(universe_value)
        excluded_values = universe_raw.get("excluded_instrument_ids", [])
        if not isinstance(excluded_values, list):
            raise TypeError("excluded_instrument_ids must be an array")
        universe = UniverseSpec(
            universe_key=str(universe_raw.get("universe_key", "ALL_A_SHARES")),
            excluded_instrument_ids=tuple(UUID(str(item)) for item in excluded_values),
            exclude_st=bool(universe_raw.get("exclude_st", False)),
            exclude_bse=bool(universe_raw.get("exclude_bse", False)),
            exclude_star_market=bool(universe_raw.get("exclude_star_market", False)),
            exclude_chinext=bool(universe_raw.get("exclude_chinext", False)),
        )
        conditions_list: list[ScreeningCondition] = []
        for condition_value in conditions_value:
            if not isinstance(condition_value, Mapping):
                raise TypeError("condition must be an object")
            condition_raw = dict(condition_value)
            parameter_value = condition_raw.get("parameters", {})
            if not isinstance(parameter_value, Mapping):
                raise TypeError("condition parameters must be an object")
            conditions_list.append(
                ScreeningCondition(
                    condition_key=str(condition_raw["condition_key"]),
                    parameters=dict(parameter_value),
                )
            )
        ranking_list: list[RankingRule] = []
        for rule_value in ranking_value:
            if not isinstance(rule_value, Mapping):
                raise TypeError("ranking rule must be an object")
            rule_raw = dict(rule_value)
            ranking_list.append(
                RankingRule(
                    field=str(rule_raw["field"]),
                    direction=RankingDirection(str(rule_raw.get("direction", "DESC"))),
                )
            )
        return ScreeningSpec(
            schema_version=int(str(payload["schema_version"])),
            name=str(payload["name"]),
            origin=str(payload["origin"]),
            universe_spec=universe,
            as_of_date=date.fromisoformat(str(payload["as_of_date"])),
            timeframe=MarketTimeframe(str(payload["timeframe"])),
            conditions=tuple(conditions_list),
            exclusions=dict(exclusions_value),
            ranking_rules=tuple(ranking_list),
            top_n=(None if payload.get("top_n") is None else int(str(payload["top_n"]))),
            price_adjustment_mode=PriceAdjustmentMode(
                str(payload.get("price_adjustment_mode", "RAW"))
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ApplicationError("SCREENING_SPEC_INVALID", "持久化的ScreeningSpec快照无效") from exc
