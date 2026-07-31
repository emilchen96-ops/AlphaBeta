# ruff: noqa: RUF001
"""SC02-A durable all-A-share screening orchestration."""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from time import perf_counter
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.scanners import (
    BackfillEnqueuer,
    FullMarketScannerProcessor,
)
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import (
    InstrumentTradingState,
    InstrumentTradingStatus,
    PriceAdjustmentMode,
)
from alphadesk_domain.miniqmt_market import miniqmt_provider_symbol
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
    ConditionGroupOperator,
    ConditionOutcome,
    RankingDirection,
    RankingRule,
    RuleBasedScreeningEngine,
    ScreeningCandidate,
    ScreeningCondition,
    ScreeningConditionGroup,
    ScreeningError,
    ScreeningFeatureStore,
    ScreeningSpec,
    UniverseSpec,
    ValidatedScreeningSpec,
)
from alphadesk_domain.screening_data_preparation import (
    DataRequirementPlan,
    InstrumentDataGap,
    ScreeningDataGapService,
    ScreeningDataRequirementPlanner,
    ScreeningInstrumentReadiness,
    ScreeningPreparationRun,
    ScreeningPreparationStage,
)
from alphadesk_domain.strategy import StrategyBar

SHANGHAI = ZoneInfo("Asia/Shanghai")
BACKFILL_SECONDS_PER_BATCH = 30
MAX_BACKFILL_WAIT_SECONDS = 8 * 60 * 60
BACKFILL_QUEUE_DRAIN_GRACE_SECONDS = 30
BackfillPendingCounter = Callable[[UUID], Awaitable[int | None]]


def _integer_stat(values: Mapping[str, object], key: str) -> int:
    value = values.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


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
        use_existing_data_only: bool = False,
        retry_instrument_ids: Sequence[UUID] = (),
    ) -> ScreeningRunOutcome:
        try:
            validated = spec.validate(self._catalog)
            snapshot = spec.snapshot(self._catalog)
        except ScreeningError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        await self._validate_date(spec.as_of_date)
        key = idempotency_key or f"screening:{uuid4()}"
        request_snapshot = {
            **snapshot,
            "preparation_options": {
                "use_existing_data_only": use_existing_data_only,
                "retry_instrument_ids": [str(item) for item in retry_instrument_ids],
            },
        }
        fingerprint = scanner_request_fingerprint(request_snapshot)
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
                execution_stats={
                    "preparation_options": {
                        "use_existing_data_only": use_existing_data_only,
                        "retry_instrument_ids": [str(item) for item in retry_instrument_ids],
                    }
                },
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

    async def cancel(self, run_id: UUID) -> ScanRun:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is None or not run.screening_spec:
                raise ApplicationError("SCREENING_RUN_NOT_FOUND", "筛选任务不存在")
            try:
                run.request_cancel(datetime.now(UTC))
            except ValueError as exc:
                raise ApplicationError(
                    "SCREENING_PREPARATION_CANCELLED",
                    "该筛选任务已经结束，不能再次取消",
                ) from exc
            await uow.scan_runs.update(run)
            await uow.commit()
        return run

    async def retry_failed(
        self,
        run_id: UUID,
        *,
        correlation_id: UUID,
        idempotency_key: str | None,
    ) -> ScreeningRunOutcome:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_by_id(run_id)
            members = [] if run is None else await uow.scan_run_members.list_by_run(run_id)
        if run is None or not run.screening_spec:
            raise ApplicationError("SCREENING_RUN_NOT_FOUND", "筛选任务不存在")
        retry_statuses = {
            ScanMemberStatus.DATA_GAP,
            ScanMemberStatus.CALENDAR_MISMATCH,
            ScanMemberStatus.STALE_DATA,
            ScanMemberStatus.INSUFFICIENT_HISTORY,
            ScanMemberStatus.REFERENCE_DATA_MISSING,
            ScanMemberStatus.QUALITY_FAILED,
            ScanMemberStatus.PROVIDER_FAILED,
            ScanMemberStatus.FAILED,
        }
        retry_ids = tuple(item.instrument_id for item in members if item.status in retry_statuses)
        if not retry_ids:
            raise ApplicationError(
                "SCREENING_NO_FAILED_INSTRUMENTS",
                "本次筛选没有可重新尝试的失败股票",
            )
        return await self.enqueue(
            screening_spec_from_snapshot(run.screening_spec),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            retry_instrument_ids=retry_ids,
        )

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


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreeningPreparationOutcome:
    ready_for_screening: bool
    feature_store: ScreeningFeatureStore | None = None


class ScreeningDataPreparationService:
    """Prepare only missing SC02 data before invoking the existing engine."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        catalog: ConditionCatalog,
        *,
        source_code: str = "MINIQMT",
        warmup_buffer: int = 10,
        maximum_extension_sessions: int = 60,
        maximum_stale_sessions: int = 20,
        backfill_batch_size: int = 50,
        backfill_wait_seconds: int = 120,
    ) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog
        self._source_code = source_code.strip().upper()
        self._planner = ScreeningDataRequirementPlanner(
            warmup_buffer=warmup_buffer,
            maximum_extension_sessions=maximum_extension_sessions,
            provider_code=self._source_code,
        )
        self._gap_service = ScreeningDataGapService()
        self._universe = PointInTimeAshareUniverseService(
            uow_factory,
            source_code=self._source_code,
        )
        self._backfill_batch_size = max(1, min(backfill_batch_size, 50))
        self._backfill_wait_seconds = max(0, backfill_wait_seconds)
        self._maximum_stale_sessions = max(1, maximum_stale_sessions)

    async def prepare(
        self,
        run_id: UUID,
        enqueue_backfill: BackfillEnqueuer,
        pending_backfill_batches: BackfillPendingCounter | None = None,
    ) -> ScreeningPreparationOutcome:
        run = await self._get_run(run_id)
        if run.cancel_requested:
            await self._cancel(run.id)
            return ScreeningPreparationOutcome(ready_for_screening=False)
        if run.status is ScanRunStatus.QUEUED:
            await self._persist_stage(
                run.id,
                ScanRunStatus.PLANNING,
                3,
                "正在分析选股数据需求",
            )
            run = await self._get_run(run.id)
        spec = screening_spec_from_snapshot(run.screening_spec)
        try:
            validated = spec.validate(self._catalog)
        except ScreeningError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        resolution = await self._universe.resolve(spec.as_of_date, spec.universe_spec)
        retry_ids = self._retry_ids(run)
        included = tuple(
            item for item in resolution.included if not retry_ids or item.id in retry_ids
        )
        if not included:
            raise ApplicationError(
                "SCREENING_EMPTY_UNIVERSE",
                "应用排除条件后没有可筛选的A股",
            )
        plan, open_sessions = await self._plan(validated, resolution.total)
        if run.status in {ScanRunStatus.QUEUED, ScanRunStatus.PLANNING}:
            await self._persist_plan(run, included, resolution.excluded, plan)
            run = await self._get_run(run.id)
        bars_by_instrument, statuses = await self._load_data(
            included,
            plan,
            open_sessions,
        )
        suspended = {
            (item.instrument_id, item.session_date)
            for item in statuses
            if item.status.value == "SUSPENDED"
        }
        gaps = self._gap_service.assess(
            instruments=included,
            bars_by_instrument=bars_by_instrument,
            required_sessions=plan.market_sessions,
            minimum_rule_sessions=plan.minimum_rule_sessions,
            available_sessions=open_sessions,
            suspended_sessions=suspended,
            currently_suspended_ids={
                instrument_id
                for instrument_id, value in resolution.trading_statuses.items()
                if value == "SUSPENDED"
            },
            as_of_date=spec.as_of_date,
            max_stale_sessions=self._maximum_stale_sessions,
        )
        use_existing = bool(self._options(run).get("use_existing_data_only", False))
        missing = tuple(item for item in gaps if item.needs_backfill)
        if run.status is ScanRunStatus.CHECKING_COVERAGE and run.backfill_requested_at is None:
            plan = replace(
                plan,
                estimated_missing_instruments=len(missing),
            )
            await self._persist_gap_estimate(run.id, plan)
        if missing and not use_existing and run.backfill_requested_at is None:
            await self._enqueue_gaps(
                run,
                included,
                gaps,
                open_sessions,
                enqueue_backfill,
            )
            return ScreeningPreparationOutcome(ready_for_screening=False)
        now = datetime.now(UTC)
        backfill_wait_seconds = self._estimated_backfill_wait_seconds(run)
        pending_batches = (
            await pending_backfill_batches(run.id) if pending_backfill_batches is not None else None
        )
        queue_drain_observed_at = self._queue_drain_observed_at(run)
        if missing and not use_existing and run.backfill_requested_at is not None:
            if pending_batches is not None and pending_batches > 0:
                await self._persist_waiting(
                    run,
                    gaps,
                    pending_batches=pending_batches,
                    queue_drain_observed_at=None,
                )
                return ScreeningPreparationOutcome(ready_for_screening=False)
            if pending_batches == 0:
                if queue_drain_observed_at is None:
                    await self._persist_waiting(
                        run,
                        gaps,
                        pending_batches=0,
                        queue_drain_observed_at=now,
                    )
                    return ScreeningPreparationOutcome(ready_for_screening=False)
                if (
                    now - queue_drain_observed_at
                ).total_seconds() < BACKFILL_QUEUE_DRAIN_GRACE_SECONDS:
                    await self._persist_waiting(
                        run,
                        gaps,
                        pending_batches=0,
                        queue_drain_observed_at=queue_drain_observed_at,
                    )
                    return ScreeningPreparationOutcome(ready_for_screening=False)
        if (
            missing
            and not use_existing
            and run.backfill_requested_at is not None
            and pending_batches is None
            and (now - run.backfill_requested_at).total_seconds() < backfill_wait_seconds
        ):
            await self._persist_waiting(run, gaps)
            return ScreeningPreparationOutcome(ready_for_screening=False)

        if missing and run.backfill_requested_at is not None:
            # A market-wide missing session is not a calendar mismatch until
            # MiniQMT has actually been asked to refill it and the queue has
            # drained.  Classifying it during the initial coverage check would
            # make `needs_backfill` false and silently skip the provider.
            gaps = self._classify_confirmed_calendar_mismatches(
                gaps,
                included_count=len(included),
                backfill_attempted=True,
            )
            missing = tuple(item for item in gaps if item.needs_backfill)
            inferred_suspensions = self._confirmed_suspension_sessions(
                missing,
                bars_by_instrument,
            )
            if inferred_suspensions:
                await self._persist_inferred_suspensions(
                    run.id,
                    inferred_suspensions,
                )
                suspended.update(inferred_suspensions)
                gaps = self._gap_service.assess(
                    instruments=included,
                    bars_by_instrument=bars_by_instrument,
                    required_sessions=plan.market_sessions,
                    minimum_rule_sessions=plan.minimum_rule_sessions,
                    available_sessions=open_sessions,
                    suspended_sessions=suspended,
                    currently_suspended_ids={
                        instrument_id
                        for instrument_id, value in resolution.trading_statuses.items()
                        if value == "SUSPENDED"
                    },
                    as_of_date=spec.as_of_date,
                    max_stale_sessions=self._maximum_stale_sessions,
                )
                gaps = self._classify_calendar_mismatches(
                    gaps,
                    included_count=len(included),
                )

        explicit_provider_failures = {
            item.instrument_id
            for item in await self._members(run.id)
            if item.status is ScanMemberStatus.PROVIDER_FAILED
        }
        finalized = tuple(
            self._finalize_gap(
                item,
                backfill_attempted=run.backfill_requested_at is not None,
                provider_failed=item.instrument_id in explicit_provider_failures,
            )
            for item in gaps
        )
        await self._persist_stage(
            run.id,
            ScanRunStatus.BACKFILLING_REFERENCE_DATA,
            55,
            "正在补齐交易状态",
        )
        finalized = await self._verify_reference_data(
            spec,
            included,
            finalized,
            plan,
        )
        await self._persist_stage(
            run.id,
            ScanRunStatus.VERIFYING_DATA,
            65,
            "正在检查数据质量",
        )
        ready_ids = {item.instrument_id for item in finalized if item.calculation_ready}
        await self._persist_readiness(
            run.id,
            finalized,
            ready_ids=ready_ids,
            plan=plan,
            bars_by_instrument=bars_by_instrument,
        )
        if not ready_ids:
            await self._finish_without_ready(run.id)
            return ScreeningPreparationOutcome(ready_for_screening=False)
        await self._persist_stage(
            run.id,
            ScanRunStatus.PREPARING_FEATURES,
            75,
            "正在准备选股指标",
        )
        feature_store = ScreeningFeatureStore(
            required_condition_keys=tuple(
                item.definition.condition_key for item in validated.conditions
            ),
            market_sessions=plan.market_sessions,
        )
        by_id = {item.id: item for item in included}
        for instrument_id in ready_ids:
            feature_store.get(
                by_id[instrument_id],
                bars_by_instrument[instrument_id],
                spec.as_of_date,
            )
        await self._persist_prepared(run.id, ready_ids, len(ready_ids))
        return ScreeningPreparationOutcome(
            ready_for_screening=True,
            feature_store=feature_store,
        )

    async def _get_run(self, run_id: UUID) -> ScanRun:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_by_id(run_id)
        if run is None:
            raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
        return run

    async def _plan(
        self,
        validated: ValidatedScreeningSpec,
        universe_count: int,
    ) -> tuple[DataRequirementPlan, tuple[date, ...]]:
        try:
            spec = validated.spec
            search_start = spec.as_of_date - timedelta(days=4_000)
            async with self._uow_factory() as uow:
                sessions = await uow.trading_calendar.list(
                    exchange="SHSE",
                    start=search_start,
                    end=spec.as_of_date,
                    limit=4_500,
                )
            open_dates = tuple(item.session_date for item in sessions if item.is_open)
            plan = self._planner.plan(
                validated,
                universe_count=universe_count,
                open_sessions=open_dates,
            )
            required = tuple(
                item
                for item in open_dates
                if plan.earliest_fetch_date <= item <= plan.latest_required_date
            )
            return plan, required
        except (AttributeError, ValueError) as exc:
            raise ApplicationError(
                "SCREENING_DATA_PLAN_FAILED",
                f"无法生成选股数据计划：{str(exc)[:300]}",
            ) from exc

    async def _persist_plan(
        self,
        run: ScanRun,
        included: Sequence[Instrument],
        excluded: Sequence[tuple[Instrument, str, str]],
        plan: DataRequirementPlan,
    ) -> None:
        members = [
            ScanRunMember(
                scan_run_id=run.id,
                instrument_id=item.id,
                symbol=item.symbol,
                exchange=item.exchange,
                instrument_name=item.name,
                status=ScanMemberStatus.INCLUDED,
                required_bars=plan.required_open_sessions,
            )
            for item in included
        ]
        members.extend(
            ScanRunMember(
                scan_run_id=run.id,
                instrument_id=item.id,
                symbol=item.symbol,
                exchange=item.exchange,
                instrument_name=item.name,
                status=ScanMemberStatus.EXCLUDED,
                reason_code=code,
                reason=reason,
                required_bars=plan.required_open_sessions,
            )
            for item, code, reason in excluded
        )
        now = datetime.now(UTC)
        preparation = ScreeningPreparationRun(
            scan_run_id=run.id,
            stage=ScreeningPreparationStage.CHECKING_COVERAGE,
            current_action="正在检查本地数据",
            started_at=run.started_at or now,
            updated_at=now,
        )
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            await uow.scan_run_members.upsert_many(members)
            locked.instrument_ids = tuple(item.id for item in included)
            locked.total_instruments = len(included) + len(excluded)
            locked.excluded_instruments = len(excluded)
            locked.execution_stats = {
                **locked.execution_stats,
                "data_requirement_plan": plan.response_dict(),
                "data_preparation": preparation.response_dict(),
            }
            locked.mark_phase(ScanRunStatus.CHECKING_COVERAGE, now, progress_percent=10)
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _persist_gap_estimate(
        self,
        run_id: UUID,
        plan: DataRequirementPlan,
    ) -> None:
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run_id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            locked.execution_stats = {
                **locked.execution_stats,
                "data_requirement_plan": plan.response_dict(),
            }
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _load_data(
        self,
        instruments: Sequence[Instrument],
        plan: DataRequirementPlan,
        open_sessions: Sequence[date],
    ) -> tuple[dict[UUID, list[StrategyBar]], list[InstrumentTradingStatus]]:
        start_at = datetime.combine(plan.earliest_fetch_date, time.min, SHANGHAI).astimezone(UTC)
        end_at = datetime.combine(
            plan.latest_required_date + timedelta(days=1),
            time.min,
            SHANGHAI,
        ).astimezone(UTC)
        instrument_ids = tuple(item.id for item in instruments)
        async with self._uow_factory() as uow:
            bars = await uow.historical_bars.list_authoritative_bars(
                instrument_ids=instrument_ids,
                timeframe=plan.required_timeframe,
                start_at=start_at,
                end_at=end_at,
                source_code=self._source_code,
                price_adjustment_mode=plan.price_adjustment_mode,
            )
            statuses = await uow.instrument_trading_statuses.list(
                instrument_ids=list(instrument_ids),
                start=open_sessions[0],
                end=open_sessions[-1],
                limit=max(len(instrument_ids) * len(open_sessions), 10_000),
            )
        grouped: dict[UUID, list[StrategyBar]] = {item.id: [] for item in instruments}
        for bar in bars:
            if bar.instrument_id in grouped:
                grouped[bar.instrument_id].append(bar)
        for values in grouped.values():
            values.sort(key=lambda item: item.timestamp)
        return grouped, statuses

    async def _enqueue_gaps(
        self,
        run: ScanRun,
        instruments: Sequence[Instrument],
        gaps: Sequence[InstrumentDataGap],
        open_sessions: Sequence[date],
        enqueue_backfill: BackfillEnqueuer,
    ) -> None:
        by_id = {item.id: item for item in instruments}
        requests: dict[tuple[date, date], list[Instrument]] = {}
        for gap in gaps:
            for value in self._gap_service.contiguous_ranges(
                gap.missing_sessions,
                open_sessions,
            ):
                requests.setdefault(value, []).append(by_id[gap.instrument_id])
        missing_gaps = tuple(item for item in gaps if item.needs_backfill)
        queue_failed_ids: set[UUID] = set()
        queued_batch_count = 0
        maximum_queue_depth = 0
        for (start_date, end_date), values in requests.items():
            for offset in range(0, len(values), self._backfill_batch_size):
                batch = values[offset : offset + self._backfill_batch_size]
                try:
                    queue_depth = await enqueue_backfill(
                        {
                            "request_id": str(uuid4()),
                            "instrument_ids": [str(item.id) for item in batch],
                            "timeframe": MarketTimeframe.DAY_1.value,
                            "start_at": datetime.combine(
                                start_date,
                                time.min,
                                SHANGHAI,
                            )
                            .astimezone(UTC)
                            .isoformat(),
                            "end_at": datetime.combine(
                                end_date + timedelta(days=1),
                                time.min,
                                SHANGHAI,
                            )
                            .astimezone(UTC)
                            .isoformat(),
                            "instruments": [
                                {
                                    "instrument_id": str(item.id),
                                    "provider_symbol": miniqmt_provider_symbol(
                                        item.symbol,
                                        item.exchange,
                                    ),
                                }
                                for item in batch
                            ],
                            "origin": "SC02_D",
                            "scan_run_id": str(run.id),
                        }
                    )
                    queued_batch_count += 1
                    if isinstance(queue_depth, int):
                        maximum_queue_depth = max(maximum_queue_depth, queue_depth)
                except Exception:
                    queue_failed_ids.update(item.id for item in batch)
        estimated_batch_count = max(queued_batch_count, maximum_queue_depth)
        estimated_wait_seconds = (
            min(
                MAX_BACKFILL_WAIT_SECONDS,
                max(
                    self._backfill_wait_seconds,
                    estimated_batch_count * BACKFILL_SECONDS_PER_BATCH
                    + self._backfill_wait_seconds,
                ),
            )
            if queued_batch_count
            else 0
        )
        now = datetime.now(UTC)
        members = await self._members(run.id)
        gap_by_id = {item.instrument_id: item for item in gaps}
        for member in members:
            member_gap = gap_by_id.get(member.instrument_id)
            if member_gap is None or not member_gap.needs_backfill:
                continue
            member.status = (
                ScanMemberStatus.PROVIDER_FAILED
                if member.instrument_id in queue_failed_ids
                else ScanMemberStatus.BACKFILL_REQUESTED
            )
            member.reason_code = (
                "SCREENING_PROVIDER_NOT_AVAILABLE"
                if member.instrument_id in queue_failed_ids
                else "HISTORY_BACKFILL_REQUESTED"
            )
            member.reason = (
                "MiniQMT历史行情请求未能进入队列"
                if member.instrument_id in queue_failed_ids
                else "正在通过MiniQMT补齐缺失的历史日线区间"
            )
            member.bars_available = member_gap.available_bars
            member.required_bars = member_gap.required_bars
            member.updated_at = now
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            await uow.scan_run_members.upsert_many(members)
            preparation = self._preparation(locked)
            preparation.update(
                {
                    "stage": ScreeningPreparationStage.BACKFILLING_MARKET_DATA.value,
                    "current_action": "正在补齐历史行情",
                    "original_ready_count": sum(
                        item.readiness is ScreeningInstrumentReadiness.READY for item in gaps
                    ),
                    "original_bar_counts": {
                        str(item.instrument_id): item.available_bars for item in gaps
                    },
                    "downloading_count": len(missing_gaps) - len(queue_failed_ids),
                    "provider_failed_count": len(queue_failed_ids),
                    "queued_batch_count": queued_batch_count,
                    "maximum_queue_depth": maximum_queue_depth,
                    "estimated_backfill_wait_seconds": estimated_wait_seconds,
                    "queue_drain_observed_at": None,
                    "updated_at": now.isoformat(),
                }
            )
            locked.execution_stats = {
                **locked.execution_stats,
                "data_preparation": preparation,
            }
            locked.backfill_requested = len(missing_gaps)
            locked.backfill_failed = len(queue_failed_ids)
            locked.backfill_requested_at = now
            locked.mark_phase(
                ScanRunStatus.BACKFILLING_MARKET_DATA,
                now,
                progress_percent=30,
            )
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _persist_waiting(
        self,
        run: ScanRun,
        gaps: Sequence[InstrumentDataGap],
        *,
        pending_batches: int | None = None,
        queue_drain_observed_at: datetime | None = None,
    ) -> None:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is None:
                return
            preparation = self._preparation(locked)
            preparation.update(
                {
                    "stage": ScreeningPreparationStage.BACKFILLING_MARKET_DATA.value,
                    "current_action": (
                        "MiniQMT补数队列已排空，正在确认最后一批数据入库"
                        if pending_batches == 0
                        else "正在等待MiniQMT返回历史行情"
                    ),
                    "downloading_count": sum(item.needs_backfill for item in gaps),
                    "pending_batch_count": pending_batches,
                    "queue_drain_observed_at": (
                        queue_drain_observed_at.isoformat()
                        if queue_drain_observed_at is not None
                        else None
                    ),
                    "updated_at": now.isoformat(),
                }
            )
            locked.execution_stats = {
                **locked.execution_stats,
                "data_preparation": preparation,
            }
            locked.updated_at = now
            await uow.scan_runs.update(locked)
            await uow.commit()

    @staticmethod
    def _confirmed_suspension_sessions(
        gaps: Sequence[InstrumentDataGap],
        bars_by_instrument: Mapping[UUID, Sequence[StrategyBar]],
    ) -> set[tuple[UUID, date]]:
        """Infer suspension only after MiniQMT successfully returned no daily bar.

        A listed instrument with other valid bars in the requested window but
        no bar for a specifically re-requested open session is a suspension
        fact, not an endlessly retryable transport failure.  Instruments with
        no bars at all remain a reference/lifecycle problem and are not
        inferred here.
        """

        return {
            (gap.instrument_id, session)
            for gap in gaps
            if gap.readiness is ScreeningInstrumentReadiness.DATA_GAP
            and bars_by_instrument.get(gap.instrument_id)
            for session in gap.missing_sessions
        }

    async def _persist_inferred_suspensions(
        self,
        run_id: UUID,
        sessions: set[tuple[UUID, date]],
    ) -> None:
        now = datetime.now(UTC)
        values = [
            InstrumentTradingStatus(
                instrument_id=instrument_id,
                session_date=session_date,
                status=InstrumentTradingState.SUSPENDED,
                source="MINIQMT_DAILY_BAR",
                fetched_at=now,
                suspension_type="INFERRED_NO_DAILY_BAR",
                reason=(
                    "MiniQMT历史请求成功完成；市场开市且该股票在请求日期仍无日线，按停牌语义记录"
                ),
            )
            for instrument_id, session_date in sorted(
                sessions,
                key=lambda item: (item[1], str(item[0])),
            )
        ]
        async with self._uow_factory() as uow:
            await uow.instrument_trading_statuses.upsert_many(values)
            locked = await uow.scan_runs.get_for_update(run_id)
            if locked is not None:
                preparation = self._preparation(locked)
                preparation.update(
                    {
                        "inferred_suspended_session_count": len(values),
                        "updated_at": now.isoformat(),
                    }
                )
                locked.execution_stats = {
                    **locked.execution_stats,
                    "data_preparation": preparation,
                }
                await uow.scan_runs.update(locked)
            await uow.commit()

    @staticmethod
    def _finalize_gap(
        gap: InstrumentDataGap,
        *,
        backfill_attempted: bool,
        provider_failed: bool = False,
    ) -> InstrumentDataGap:
        if provider_failed:
            return InstrumentDataGap(
                instrument_id=gap.instrument_id,
                readiness=ScreeningInstrumentReadiness.PROVIDER_FAILED,
                available_bars=gap.available_bars,
                required_bars=gap.required_bars,
                missing_sessions=gap.missing_sessions,
                reason_code="SCREENING_PROVIDER_NOT_AVAILABLE",
                reason="MiniQMT历史行情请求明确失败",
            )
        if backfill_attempted and gap.readiness is ScreeningInstrumentReadiness.DATA_GAP:
            return replace(
                gap,
                reason_code="DATA_STILL_NOT_READY",
                reason="增量补数后正常交易日行情仍未就绪",
            )
        return gap

    @staticmethod
    def _classify_calendar_mismatches(
        gaps: Sequence[InstrumentDataGap],
        *,
        included_count: int,
    ) -> tuple[InstrumentDataGap, ...]:
        """Stop mass backfills when one alleged session is absent market-wide."""

        missing_lengths = sorted(len(gap.missing_sessions) for gap in gaps if gap.missing_sessions)
        if not missing_lengths or missing_lengths[len(missing_lengths) // 2] > 2:
            return tuple(gaps)
        counts = Counter(session for gap in gaps for session in gap.missing_sessions)
        threshold = max(50, int(included_count * 0.5))
        suspicious = {session for session, count in counts.items() if count >= threshold}
        if not suspicious:
            return tuple(gaps)
        dates = "、".join(item.isoformat() for item in sorted(suspicious))
        return tuple(
            replace(
                gap,
                readiness=ScreeningInstrumentReadiness.CALENDAR_MISMATCH,
                reason_code="CALENDAR_MISMATCH",
                reason=f"大量股票共同缺少{dates}行情，请先核对交易日历",
            )
            if suspicious.intersection(gap.missing_sessions)
            else gap
            for gap in gaps
        )

    @classmethod
    def _classify_confirmed_calendar_mismatches(
        cls,
        gaps: Sequence[InstrumentDataGap],
        *,
        included_count: int,
        backfill_attempted: bool,
    ) -> tuple[InstrumentDataGap, ...]:
        """Classify a common gap only after a real provider refill attempt."""

        if not backfill_attempted:
            return tuple(gaps)
        return cls._classify_calendar_mismatches(
            gaps,
            included_count=included_count,
        )

    async def _verify_reference_data(
        self,
        spec: ScreeningSpec,
        instruments: Sequence[Instrument],
        gaps: Sequence[InstrumentDataGap],
        plan: DataRequirementPlan,
    ) -> tuple[InstrumentDataGap, ...]:
        if spec.price_adjustment_mode is not PriceAdjustmentMode.QFQ:
            return tuple(gaps)
        ids = [item.id for item in instruments]
        async with self._uow_factory() as uow:
            factors = await uow.adjustment_factors.list(
                instrument_ids=ids,
                start=plan.earliest_required_date,
                end=plan.latest_required_date,
                source=None,
                convention=None,
                limit=max(len(ids) * plan.required_open_sessions, 10_000),
            )
        available = {item.instrument_id for item in factors}
        values: list[InstrumentDataGap] = []
        for gap in gaps:
            if (
                gap.readiness is ScreeningInstrumentReadiness.READY
                and gap.instrument_id not in available
            ):
                values.append(
                    InstrumentDataGap(
                        instrument_id=gap.instrument_id,
                        readiness=ScreeningInstrumentReadiness.REFERENCE_DATA_MISSING,
                        available_bars=gap.available_bars,
                        required_bars=gap.required_bars,
                        reason_code="SCREENING_REFERENCE_DATA_MISSING",
                        reason="缺少所需复权因子，不能可靠计算前复权条件",
                    )
                )
            else:
                values.append(gap)
        return tuple(values)

    async def _persist_readiness(
        self,
        run_id: UUID,
        gaps: Sequence[InstrumentDataGap],
        *,
        ready_ids: set[UUID],
        plan: DataRequirementPlan,
        bars_by_instrument: Mapping[UUID, Sequence[StrategyBar]],
    ) -> None:
        now = datetime.now(UTC)
        members = await self._members(run_id)
        by_id = {item.instrument_id: item for item in gaps}
        for member in members:
            gap = by_id.get(member.instrument_id)
            if gap is None:
                continue
            member.status = ScanMemberStatus(gap.readiness.value)
            member.reason_code = gap.reason_code
            member.reason = gap.reason
            member.bars_available = gap.available_bars
            member.required_bars = gap.required_bars
            member.updated_at = now
        counts = Counter(item.readiness.value for item in gaps)
        reason_counts = Counter(item.reason_code for item in gaps)
        prior_preparation = self._preparation(await self._get_run(run_id))
        original_ready_value = prior_preparation.get("original_ready_count")
        if isinstance(original_ready_value, int):
            original_ready = original_ready_value
        else:
            original_ready = counts[ScreeningInstrumentReadiness.READY.value]
        raw_original_counts = prior_preparation.get("original_bar_counts", {})
        original_counts = raw_original_counts if isinstance(raw_original_counts, Mapping) else {}
        backfilled_bars = sum(
            max(
                0,
                len(bars_by_instrument[item])
                - int(original_counts.get(str(item), len(bars_by_instrument[item]))),
            )
            for item in ready_ids
        )
        error_codes: list[str] = []
        if counts[ScreeningInstrumentReadiness.PROVIDER_FAILED.value]:
            error_codes.append("SCREENING_BACKFILL_PARTIAL_FAILED")
        if counts[ScreeningInstrumentReadiness.REFERENCE_DATA_MISSING.value]:
            error_codes.append("SCREENING_REFERENCE_DATA_MISSING")
        if counts[ScreeningInstrumentReadiness.QUALITY_FAILED.value]:
            error_codes.append("SCREENING_DATA_QUALITY_FAILED")
        if counts[ScreeningInstrumentReadiness.CALENDAR_MISMATCH.value]:
            error_codes.append("SCREENING_CALENDAR_MISMATCH")
        if counts[ScreeningInstrumentReadiness.DATA_GAP.value] and not prior_preparation.get(
            "downloading_count"
        ):
            error_codes.append("SCREENING_DATA_STILL_NOT_READY")
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run_id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            await uow.scan_run_members.upsert_many(members)
            preparation = self._preparation(locked)
            preparation.update(
                {
                    "stage": ScreeningPreparationStage.VERIFYING_DATA.value,
                    "current_action": "数据质量检查完成",
                    "original_ready_count": original_ready,
                    "ready_count": len(ready_ids),
                    "downloading_count": 0,
                    "insufficient_count": counts[
                        ScreeningInstrumentReadiness.INSUFFICIENT_HISTORY.value
                    ],
                    "indeterminate_count": counts[ScreeningInstrumentReadiness.INDETERMINATE.value],
                    "provider_failed_count": counts[
                        ScreeningInstrumentReadiness.PROVIDER_FAILED.value
                    ],
                    "quality_failed_count": counts[
                        ScreeningInstrumentReadiness.QUALITY_FAILED.value
                    ],
                    "reference_data_missing_count": counts[
                        ScreeningInstrumentReadiness.REFERENCE_DATA_MISSING.value
                    ],
                    "not_applicable_count": counts[
                        ScreeningInstrumentReadiness.NOT_APPLICABLE.value
                    ],
                    "listing_history_short_count": reason_counts["LISTING_HISTORY_TOO_SHORT"],
                    "currently_suspended_count": counts[
                        ScreeningInstrumentReadiness.CURRENTLY_SUSPENDED.value
                    ],
                    "stale_data_count": counts[ScreeningInstrumentReadiness.STALE_DATA.value],
                    "data_gap_count": counts[ScreeningInstrumentReadiness.DATA_GAP.value],
                    "calendar_mismatch_count": counts[
                        ScreeningInstrumentReadiness.CALENDAR_MISMATCH.value
                    ],
                    "calendar_mismatch_dates": [
                        item.isoformat()
                        for item in sorted(
                            {
                                session
                                for gap in gaps
                                if gap.readiness is ScreeningInstrumentReadiness.CALENDAR_MISMATCH
                                for session in gap.missing_sessions
                            }
                        )
                    ],
                    "delisted_count": counts[ScreeningInstrumentReadiness.DELISTED.value],
                    "backfilled_instrument_count": max(
                        0,
                        len(ready_ids) - original_ready,
                    ),
                    "backfilled_bar_count": backfilled_bars,
                    "required_open_sessions": plan.required_open_sessions,
                    "error_codes": error_codes,
                    "updated_at": now.isoformat(),
                }
            )
            locked.execution_stats = {
                **locked.execution_stats,
                "data_preparation": preparation,
            }
            locked.data_ready_instruments = len(ready_ids)
            locked.insufficient_history = (
                counts[ScreeningInstrumentReadiness.DATA_GAP.value]
                + counts[ScreeningInstrumentReadiness.INSUFFICIENT_HISTORY.value]
                + reason_counts["LISTING_HISTORY_TOO_SHORT"]
            )
            locked.backfill_failed = counts[ScreeningInstrumentReadiness.PROVIDER_FAILED.value]
            locked.failed_instruments = (
                counts[ScreeningInstrumentReadiness.PROVIDER_FAILED.value]
                + counts[ScreeningInstrumentReadiness.QUALITY_FAILED.value]
                + counts[ScreeningInstrumentReadiness.REFERENCE_DATA_MISSING.value]
                + counts[ScreeningInstrumentReadiness.CALENDAR_MISMATCH.value]
            )
            locked.mark_phase(ScanRunStatus.VERIFYING_DATA, now, progress_percent=70)
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _persist_prepared(
        self,
        run_id: UUID,
        ready_ids: set[UUID],
        feature_count: int,
    ) -> None:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run_id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            preparation = self._preparation(locked)
            preparation.update(
                {
                    "stage": ScreeningPreparationStage.SCREENING.value,
                    "current_action": "正在执行全市场选股",
                    "feature_prepared_count": feature_count,
                    "ready_instrument_ids": [str(item) for item in sorted(ready_ids, key=str)],
                    "prepared": True,
                    "updated_at": now.isoformat(),
                }
            )
            locked.execution_stats = {
                **locked.execution_stats,
                "data_preparation": preparation,
            }
            locked.mark_phase(ScanRunStatus.SCREENING, now, progress_percent=80)
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _persist_stage(
        self,
        run_id: UUID,
        status: ScanRunStatus,
        progress: int,
        action: str,
    ) -> None:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run_id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            preparation = self._preparation(locked)
            preparation.update(
                {
                    "stage": status.value,
                    "current_action": action,
                    "updated_at": now.isoformat(),
                }
            )
            locked.execution_stats = {
                **locked.execution_stats,
                "data_preparation": preparation,
            }
            locked.mark_phase(status, now, progress_percent=progress)
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _finish_without_ready(self, run_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run_id)
            if locked is None:
                return
            preparation = self._preparation(locked)
            preparation.update(
                {
                    "stage": ScreeningPreparationStage.PARTIAL_FAILED.value,
                    "current_action": "数据准备完成，但没有股票达到可计算状态",
                    "updated_at": now.isoformat(),
                }
            )
            locked.execution_stats = {
                **locked.execution_stats,
                "data_preparation": preparation,
            }
            locked.mark_phase(ScanRunStatus.SCREENING, now, progress_percent=99)
            locked.mark_partial_failed(now, 0, 0)
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _members(self, run_id: UUID) -> list[ScanRunMember]:
        async with self._uow_factory() as uow:
            return await uow.scan_run_members.list_by_run(run_id)

    async def _cancel(self, run_id: UUID) -> None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is not None:
                run.mark_canceled(datetime.now(UTC))
                await uow.scan_runs.update(run)
                await uow.commit()

    @staticmethod
    def _options(run: ScanRun) -> Mapping[str, object]:
        value = run.execution_stats.get("preparation_options", {})
        return value if isinstance(value, Mapping) else {}

    def _retry_ids(self, run: ScanRun) -> set[UUID]:
        raw = self._options(run).get("retry_instrument_ids", [])
        if not isinstance(raw, list):
            return set()
        values: set[UUID] = set()
        for item in raw:
            try:
                values.add(UUID(str(item)))
            except ValueError:
                continue
        return values

    @staticmethod
    def _preparation(run: ScanRun) -> dict[str, object]:
        value = run.execution_stats.get("data_preparation", {})
        return dict(value) if isinstance(value, Mapping) else {}

    def _estimated_backfill_wait_seconds(self, run: ScanRun) -> int:
        preparation = self._preparation(run)
        value = preparation.get("estimated_backfill_wait_seconds")
        persisted = value if isinstance(value, int) else self._backfill_wait_seconds
        queue_depth_value = preparation.get("maximum_queue_depth")
        if isinstance(queue_depth_value, int):
            queue_estimate = (
                queue_depth_value * BACKFILL_SECONDS_PER_BATCH + self._backfill_wait_seconds
            )
            persisted = max(persisted, queue_estimate)
        return max(0, min(persisted, MAX_BACKFILL_WAIT_SECONDS))

    def _queue_drain_observed_at(self, run: ScanRun) -> datetime | None:
        value = self._preparation(run).get("queue_drain_observed_at")
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


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

    async def process(
        self,
        run_id: UUID,
        *,
        feature_store: ScreeningFeatureStore | None = None,
    ) -> None:
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
        resolution = await self._universe.resolve(spec.as_of_date, spec.universe_spec)
        raw_preparation = run.execution_stats.get("data_preparation", {})
        preparation = dict(raw_preparation) if isinstance(raw_preparation, Mapping) else {}
        prepared = bool(preparation.get("prepared"))
        ready_ids = (
            {UUID(str(item)) for item in preparation.get("ready_instrument_ids", [])}
            if prepared and isinstance(preparation.get("ready_instrument_ids"), list)
            else set()
        )
        included = tuple(
            item for item in resolution.included if not prepared or item.id in ready_ids
        )
        if not included:
            raise ApplicationError("SCREENING_EMPTY_UNIVERSE", "应用排除条件后没有可筛选的A股")
        if prepared:
            async with self._uow_factory() as uow:
                members = await uow.scan_run_members.list_by_run(run.id)
        else:
            await self._mark_phase(run.id, ScanRunStatus.RESOLVING, 5)
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
                for item in included
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
                locked.instrument_ids = tuple(item.id for item in included)
                locked.total_instruments = resolution.total
                locked.excluded_instruments = len(resolution.excluded)
                locked.query_count = 2
                locked.mark_phase(
                    ScanRunStatus.CHECKING_DATA,
                    datetime.now(UTC),
                    progress_percent=15,
                )
                await uow.scan_runs.update(locked)
                await uow.commit()
        run = await self._get_run(run.id)
        plan = run.execution_stats.get("data_requirement_plan", {})
        earliest = (
            plan.get("earliest_fetch_date") or plan.get("earliest_required_date")
            if isinstance(plan, Mapping)
            else None
        )
        start_at = (
            datetime.combine(date.fromisoformat(str(earliest)), time.min, SHANGHAI).astimezone(UTC)
            if earliest is not None
            else run.as_of - timedelta(days=max(validated.required_history_bars * 3, 180))
        )
        async with self._uow_factory() as uow:
            bars = await uow.historical_bars.list_authoritative_bars(
                instrument_ids=tuple(item.id for item in included),
                timeframe=MarketTimeframe.DAY_1,
                start_at=start_at,
                end_at=run.as_of + timedelta(microseconds=1),
                source_code=self._source_code,
                price_adjustment_mode=PriceAdjustmentMode.RAW,
            )
        grouped: dict[UUID, list[StrategyBar]] = {instrument.id: [] for instrument in included}
        for market_bar in bars:
            if market_bar.instrument_id in grouped:
                grouped[market_bar.instrument_id].append(market_bar)
        for values in grouped.values():
            values.sort(key=lambda market_bar: market_bar.timestamp)
        if prepared:
            await self._mark_screening_loaded(run.id, bars_read=len(bars))
        else:
            await self._mark_running(run.id, bars_read=len(bars))
        engine = RuleBasedScreeningEngine(self._catalog, feature_store)
        candidates: list[ScreeningCandidate] = []
        insufficient = 0
        indeterminate = 0
        failed = 0
        ready = 0
        processed = 0
        condition_failure_counts: Counter[str] = Counter()
        by_member = {item.instrument_id: item for item in members}
        included_list = list(included)
        for offset in range(0, len(included_list), self._batch_size):
            batch = included_list[offset : offset + self._batch_size]
            for instrument in batch:
                item_bars = grouped[instrument.id]
                member = by_member[instrument.id]
                member.bars_available = len(item_bars)
                current_status = resolution.trading_statuses.get(instrument.id)
                currently_suspended = current_status == "SUSPENDED"
                latest_is_as_of = bool(item_bars) and (
                    item_bars[-1].timestamp.astimezone(SHANGHAI).date() == spec.as_of_date
                )
                if len(item_bars) < validated.required_history_bars or (
                    not latest_is_as_of and not currently_suspended
                ):
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
                        trading_status=current_status,
                    )
                except Exception as exc:
                    member.status = ScanMemberStatus.FAILED
                    member.reason_code = "CONDITION_EVALUATION_FAILED"
                    member.reason = f"该股票规则计算失败：{str(exc)[:300]}"
                    failed += 1
                    processed += 1
                    continue
                if currently_suspended:
                    member.status = ScanMemberStatus.CURRENTLY_SUSPENDED
                    member.reason_code = "CURRENTLY_SUSPENDED"
                    member.reason = "筛选截止日当前停牌，已完成研究计算但不进入可执行结果"
                    processed += 1
                    continue
                if (
                    outcome.outcome is not ConditionOutcome.MATCHED
                    and outcome.failed_condition_key is not None
                ):
                    condition_failure_counts[outcome.failed_condition_key] += 1
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
                total=len(included_list),
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
            locked.batch_count = max(
                1,
                (len(included_list) + self._batch_size - 1) // self._batch_size,
            )
            locked.query_count = 3
            locked.bars_read = len(bars)
            preparation_stats = self._preparation_stats(locked)
            preparation_insufficient = 0
            preparation_indeterminate = 0
            preparation_failed = 0
            if preparation_stats:
                preparation_insufficient = (
                    _integer_stat(preparation_stats, "insufficient_count")
                    + _integer_stat(preparation_stats, "listing_history_short_count")
                    + _integer_stat(preparation_stats, "data_gap_count")
                )
                preparation_indeterminate = _integer_stat(
                    preparation_stats,
                    "indeterminate_count",
                )
                preparation_failed = (
                    _integer_stat(preparation_stats, "provider_failed_count")
                    + _integer_stat(preparation_stats, "quality_failed_count")
                    + _integer_stat(preparation_stats, "reference_data_missing_count")
                    + _integer_stat(preparation_stats, "calendar_mismatch_count")
                )
            locked.insufficient_history = insufficient + preparation_insufficient
            locked.indeterminate_count = indeterminate + preparation_indeterminate
            locked.failed_instruments = failed + preparation_failed
            locked.execution_stats = {
                **locked.execution_stats,
                "as_of_date": spec.as_of_date.isoformat(),
                "universe_count": resolution.total,
                "included_count": len(included_list),
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
                "condition_failure_counts": dict(condition_failure_counts),
            }
            if preparation_stats:
                preparation_stats.update(
                    {
                        "stage": ScreeningPreparationStage.COMPLETED.value,
                        "current_action": "全市场选股已完成",
                        "feature_prepared_count": len(included_list),
                        "updated_at": now.isoformat(),
                    }
                )
                locked.execution_stats["data_preparation"] = preparation_stats
            if (
                locked.insufficient_history
                or locked.indeterminate_count
                or locked.failed_instruments
            ):
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

    async def _mark_screening_loaded(self, run_id: UUID, *, bars_read: int) -> None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "筛选任务不存在")
            run.mark_phase(ScanRunStatus.SCREENING, datetime.now(UTC), progress_percent=80)
            run.query_count += 1
            run.bars_read = bars_read
            await uow.scan_runs.update(run)
            await uow.commit()

    @staticmethod
    def _preparation_stats(run: ScanRun) -> dict[str, object]:
        value = run.execution_stats.get("data_preparation", {})
        return dict(value) if isinstance(value, Mapping) else {}

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
            if run.status is ScanRunStatus.SCREENING:
                run.progress_percent = 80 + int(processed / max(total, 1) * 19)
            else:
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
                code = exc.code if isinstance(exc, ApplicationError) else "SCREENING_RUN_FAILED"
                message = (
                    str(exc)
                    if isinstance(exc, ApplicationError)
                    else f"规则筛选任务执行失败：{str(exc)[:400]}"
                )
                run.mark_failed(datetime.now(UTC), code, message)
                preparation = self._preparation_stats(run)
                if preparation:
                    preparation.update(
                        {
                            "stage": ScreeningPreparationStage.FAILED.value,
                            "current_action": message[:300],
                            "updated_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    run.execution_stats = {
                        **run.execution_stats,
                        "data_preparation": preparation,
                    }
                await uow.scan_runs.update(run)
                await uow.commit()


class ScreeningOrchestrationService:
    """Run the SC02-D preparation pipeline before the immutable SC02 engine."""

    def __init__(
        self,
        preparation: ScreeningDataPreparationService,
        screening: RuleBasedScreeningProcessor,
    ) -> None:
        self._preparation = preparation
        self._screening = screening

    async def process(
        self,
        run_id: UUID,
        enqueue_backfill: BackfillEnqueuer,
        pending_backfill_batches: BackfillPendingCounter | None = None,
    ) -> None:
        outcome = (
            await self._preparation.prepare(run_id, enqueue_backfill)
            if pending_backfill_batches is None
            else await self._preparation.prepare(
                run_id,
                enqueue_backfill,
                pending_backfill_batches,
            )
        )
        if outcome.ready_for_screening:
            await self._screening.process(
                run_id,
                feature_store=outcome.feature_store,
            )

    async def fail(self, run_id: UUID, exc: Exception) -> None:
        await self._screening.fail(run_id, exc)


class UnifiedScannerWorkerProcessor:
    """Route old SC01 runs and new SC02-A specs through one claim loop."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        legacy_processor: FullMarketScannerProcessor,
        screening_processor: RuleBasedScreeningProcessor,
        screening_orchestration: ScreeningOrchestrationService | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._legacy = legacy_processor
        self._screening = screening_processor
        self._screening_orchestration = screening_orchestration

    async def process_next(
        self,
        enqueue_backfill: BackfillEnqueuer,
        pending_backfill_batches: BackfillPendingCounter | None = None,
    ) -> UUID | None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_next_pending(
                (
                    ScanRunStatus.QUEUED,
                    ScanRunStatus.RESOLVING,
                    ScanRunStatus.CHECKING_DATA,
                    ScanRunStatus.BACKFILLING,
                    ScanRunStatus.RUNNING,
                    ScanRunStatus.PLANNING,
                    ScanRunStatus.CHECKING_COVERAGE,
                    ScanRunStatus.BACKFILLING_MARKET_DATA,
                    ScanRunStatus.BACKFILLING_REFERENCE_DATA,
                    ScanRunStatus.VERIFYING_DATA,
                    ScanRunStatus.PREPARING_FEATURES,
                    ScanRunStatus.SCREENING,
                )
            )
            if run is None:
                return None
            run_id = run.id
            is_screening = bool(run.screening_spec)
        try:
            if is_screening:
                if self._screening_orchestration is None:
                    await self._screening.process(run_id)
                else:
                    await self._screening_orchestration.process(
                        run_id,
                        enqueue_backfill,
                        pending_backfill_batches,
                    )
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
        schema_version = int(str(payload["schema_version"]))
        conditions_value = payload.get("conditions", [])
        root_group_value = payload.get("root_group")
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
            conditions_list.append(_screening_condition_from_snapshot(condition_value))
        root_group = None
        if schema_version == 2:
            root_group = _screening_group_from_snapshot(root_group_value)
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
            schema_version=schema_version,
            name=str(payload["name"]),
            origin=str(payload["origin"]),
            universe_spec=universe,
            as_of_date=date.fromisoformat(str(payload["as_of_date"])),
            timeframe=MarketTimeframe(str(payload["timeframe"])),
            conditions=tuple(conditions_list),
            root_group=root_group,
            exclusions=dict(exclusions_value),
            ranking_rules=tuple(ranking_list),
            top_n=(None if payload.get("top_n") is None else int(str(payload["top_n"]))),
            price_adjustment_mode=PriceAdjustmentMode(
                str(payload.get("price_adjustment_mode", "RAW"))
            ),
        )
    except (KeyError, TypeError, ValueError, ScreeningError) as exc:
        raise ApplicationError("SCREENING_SPEC_INVALID", "持久化的ScreeningSpec快照无效") from exc


def _screening_condition_from_snapshot(value: object) -> ScreeningCondition:
    if not isinstance(value, Mapping):
        raise TypeError("condition must be an object")
    raw = dict(value)
    parameter_value = raw.get("parameters", {})
    if not isinstance(parameter_value, Mapping):
        raise TypeError("condition parameters must be an object")
    return ScreeningCondition(
        condition_key=str(raw["condition_key"]),
        parameters=dict(parameter_value),
    )


def _screening_group_from_snapshot(
    value: object,
    *,
    depth: int = 1,
) -> ScreeningConditionGroup:
    if not isinstance(value, Mapping):
        raise TypeError("root_group must be an object for ScreeningSpec v2")
    if depth > 3:
        raise ValueError("condition group nesting exceeds three levels")
    raw = dict(value)
    children_value = raw.get("children")
    if not isinstance(children_value, list) or not children_value:
        raise TypeError("condition group children must be a non-empty array")
    children: list[ScreeningCondition | ScreeningConditionGroup] = []
    for child_value in children_value:
        if not isinstance(child_value, Mapping):
            raise TypeError("condition group child must be an object")
        child_raw = dict(child_value)
        is_group = child_raw.get("node_type") == "GROUP" or (
            "children" in child_raw and "operator" in child_raw
        )
        children.append(
            _screening_group_from_snapshot(child_raw, depth=depth + 1)
            if is_group
            else _screening_condition_from_snapshot(child_raw)
        )
    return ScreeningConditionGroup(
        operator=ConditionGroupOperator(str(raw.get("operator", "AND"))),
        children=tuple(children),
    )
