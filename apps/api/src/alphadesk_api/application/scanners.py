"""SC01 synchronous scanner orchestration and read-only query services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.miniqmt_market import miniqmt_provider_symbol
from alphadesk_domain.scanners import (
    ScanMemberStatus,
    Scanner,
    ScannerContext,
    ScannerError,
    ScannerMetadata,
    ScannerParameterValue,
    ScannerRegistry,
    ScanResult,
    ScanRun,
    ScanRunMember,
    ScanRunStatus,
    ScanUniverseType,
    is_delisting_instrument,
    is_st_instrument,
    scanner_request_fingerprint,
    scanner_required_history_bars,
    stored_scanner_metrics,
    stored_scanner_parameters,
)
from alphadesk_domain.strategy import StrategyBar
from alphadesk_domain.unit_of_work import UnitOfWork

SHANGHAI = ZoneInfo("Asia/Shanghai")
BackfillEnqueuer = Callable[[dict[str, object]], Awaitable[int | None]]


@dataclass(frozen=True, slots=True, kw_only=True)
class ScannerRunRequest:
    scanner_key: str
    parameters: Mapping[str, ScannerParameterValue]
    instrument_ids: tuple[UUID, ...]
    timeframe: MarketTimeframe
    as_of: datetime
    idempotency_key: str
    correlation_id: UUID
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW


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


@dataclass(frozen=True, slots=True, kw_only=True)
class ScannerUniverseFilters:
    exclude_st: bool = True
    exclude_suspended: bool = True
    exclude_insufficient_history: bool = True
    exclude_bse: bool = False
    exclude_star_market: bool = False
    exclude_chinext: bool = False
    minimum_listing_trading_days: int | None = None
    excluded_instrument_ids: tuple[UUID, ...] = ()

    def stored(self) -> dict[str, object]:
        return {
            "exclude_st": self.exclude_st,
            "exclude_suspended": self.exclude_suspended,
            "exclude_insufficient_history": self.exclude_insufficient_history,
            "exclude_bse": self.exclude_bse,
            "exclude_star_market": self.exclude_star_market,
            "exclude_chinext": self.exclude_chinext,
            "minimum_listing_trading_days": self.minimum_listing_trading_days,
            "excluded_instrument_ids": [
                str(item) for item in sorted(set(self.excluded_instrument_ids), key=str)
            ],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class FullMarketScanRequest:
    scanner_key: str
    parameters: Mapping[str, ScannerParameterValue]
    scan_date: date
    filters: ScannerUniverseFilters
    correlation_id: UUID
    idempotency_key: str | None = None


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
                "display_name": item.display_name or item.name,
                "unit": item.unit,
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
        return [
            {
                **_catalog_item(item),
                "data_source": "MINIQMT",
                "default_universe": ScanUniverseType.ALL_ACTIVE_A_SHARES.value,
                "execution_mode": "BACKGROUND_BATCH",
            }
            for item in self._registry.list_metadata()
        ]


class FullMarketScannerService:
    """Create durable all-A-share jobs; execution belongs to the scanner worker."""

    def __init__(self, uow_factory: UnitOfWorkFactory, registry: ScannerRegistry) -> None:
        self._uow_factory = uow_factory
        self._registry = registry

    async def enqueue(self, request: FullMarketScanRequest) -> ScannerRunOutcome:
        try:
            scanner = self._registry.create(request.scanner_key)
            validated = scanner.validate_parameters(request.parameters)
        except ScannerError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        if request.filters.minimum_listing_trading_days is not None and not (
            1 <= request.filters.minimum_listing_trading_days <= 5000
        ):
            raise ApplicationError(
                "SCANNER_INVALID_FILTER",
                "新股排除交易日数必须在1到5000之间",
            )
        stored_parameters = stored_scanner_parameters(validated)
        filters = request.filters.stored()
        idempotency_key = request.idempotency_key or f"scan:{uuid4()}"
        as_of = await self._validate_scan_date(request.scan_date)
        fingerprint = scanner_request_fingerprint(
            {
                "schema_version": 2,
                "scanner_key": scanner.metadata.scanner_key,
                "scanner_version": scanner.metadata.version,
                "parameters": stored_parameters,
                "universe_type": ScanUniverseType.ALL_ACTIVE_A_SHARES.value,
                "universe_filters": filters,
                "timeframe": MarketTimeframe.DAY_1.value,
                "as_of": as_of.isoformat(),
                "source_code": "MINIQMT",
                "price_adjustment_mode": PriceAdjustmentMode.RAW.value,
            }
        )
        async with self._uow_factory() as uow:
            existing = await uow.scan_runs.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ApplicationError(
                        "SCAN_RUN_IDEMPOTENCY_CONFLICT",
                        "幂等键已用于不同的扫描请求",
                    )
                return ScannerRunOutcome(
                    run=existing,
                    results=tuple(await uow.scan_results.list_by_run(existing.id)),
                    replayed=True,
                )
            run = ScanRun(
                scanner_key=scanner.metadata.scanner_key,
                scanner_version=scanner.metadata.version,
                parameters=stored_parameters,
                universe_type=ScanUniverseType.ALL_ACTIVE_A_SHARES.value,
                universe_filters=filters,
                instrument_ids=(),
                timeframe=MarketTimeframe.DAY_1,
                as_of=as_of,
                status=ScanRunStatus.QUEUED,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                correlation_id=request.correlation_id,
                price_adjustment_mode=PriceAdjustmentMode.RAW,
                source_code="MINIQMT",
            )
            await uow.scan_runs.add(run)
            await uow.commit()
            return ScannerRunOutcome(run=run, results=(), replayed=False)

    async def _validate_scan_date(self, value: date) -> datetime:
        async with self._uow_factory() as uow:
            sessions = await uow.trading_calendar.list(
                exchange="SHSE", start=value, end=value, limit=1
            )
        if not sessions or not sessions[0].is_open:
            raise ApplicationError(
                "SCANNER_DATE_NOT_TRADING_DAY",
                "扫描日期不是已登记的A股交易日",
            )
        return datetime.combine(value, time(15, 0), SHANGHAI).astimezone(UTC)

    async def latest_completed_scan_date(self, now: datetime | None = None) -> date:
        local_now = (now or datetime.now(UTC)).astimezone(SHANGHAI)
        end = local_now.date()
        async with self._uow_factory() as uow:
            sessions = await uow.trading_calendar.list(
                exchange="SHSE",
                start=end - timedelta(days=370),
                end=end,
                limit=500,
            )
        open_dates = [
            item.session_date
            for item in sessions
            if item.is_open
            and (item.session_date < local_now.date() or local_now.time() >= time(15, 10))
        ]
        if not open_dates:
            raise ApplicationError(
                "MARKET_CALENDAR_NOT_AVAILABLE",
                "交易日历中没有可用的已完成交易日",
            )
        return max(open_dates)


class FullMarketScannerProcessor:
    """Advance one durable scanner job by one worker tick."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: ScannerRegistry,
        *,
        source_code: str = "MINIQMT",
        backfill_batch_size: int = 50,
        backfill_wait_seconds: int = 120,
        scan_batch_size: int = 250,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._source_code = source_code.strip().upper()
        self._backfill_batch_size = max(1, min(backfill_batch_size, 50))
        self._backfill_wait_seconds = max(0, backfill_wait_seconds)
        self._scan_batch_size = max(1, min(scan_batch_size, 1000))

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
        try:
            await self.process(run_id, enqueue_backfill)
        except Exception as exc:
            await self._fail(run_id, exc)
        return run_id

    async def process(self, run_id: UUID, enqueue_backfill: BackfillEnqueuer) -> None:
        run = await self._get_run(run_id)
        if run.cancel_requested:
            await self._cancel(run)
            return
        scanner = self._registry.create(run.scanner_key)
        validated = scanner.validate_parameters(run.parameters)
        required_bars = scanner_required_history_bars(run.scanner_key, validated)
        if run.status in {ScanRunStatus.QUEUED, ScanRunStatus.RESOLVING}:
            await self._resolve_universe(run, required_bars)
            run = await self._get_run(run_id)
        if run.status in {ScanRunStatus.CHECKING_DATA, ScanRunStatus.BACKFILLING}:
            should_continue = await self._prepare_data(run, required_bars, enqueue_backfill)
            if not should_continue:
                return
            run = await self._get_run(run_id)
        if run.cancel_requested:
            await self._cancel(run)
            return
        await self._execute_ready(run, scanner, validated)

    async def _get_run(self, run_id: UUID) -> ScanRun:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_by_id(run_id)
        if run is None:
            raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
        return run

    async def _resolve_universe(self, run: ScanRun, required_bars: int) -> None:
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
            if locked.cancel_requested:
                locked.mark_canceled(datetime.now(UTC))
                await uow.scan_runs.update(locked)
                await uow.commit()
                return
            locked.mark_phase(ScanRunStatus.RESOLVING, datetime.now(UTC), progress_percent=5)
            await uow.scan_runs.update(locked)
            await uow.commit()
        async with self._uow_factory() as uow:
            instruments, _ = await uow.instruments.search(
                keyword=None,
                exchange=None,
                market=None,
                asset_type="STOCK",
                is_active=True,
                offset=0,
                limit=10_000,
                source_code=self._source_code,
            )
            statuses = await uow.instrument_trading_statuses.list(
                instrument_ids=[item.id for item in instruments],
                start=run.as_of.astimezone(SHANGHAI).date(),
                end=run.as_of.astimezone(SHANGHAI).date(),
                limit=10_000,
            )
            trading_status = {item.instrument_id: item.status.value for item in statuses}
            minimum_days = run.universe_filters.get("minimum_listing_trading_days")
            open_sessions: list[date] = []
            if isinstance(minimum_days, int):
                scan_date = run.as_of.astimezone(SHANGHAI).date()
                sessions = await uow.trading_calendar.list(
                    exchange="SHSE",
                    start=scan_date - timedelta(days=minimum_days * 2 + 60),
                    end=scan_date,
                    limit=max(minimum_days * 2, 500),
                )
                open_sessions = [item.session_date for item in sessions if item.is_open]
        filters = run.universe_filters
        raw_manual = filters.get("excluded_instrument_ids", [])
        manual = (
            {UUID(str(item)) for item in raw_manual}
            if isinstance(raw_manual, (list, tuple))
            else set()
        )
        members: list[ScanRunMember] = []
        included: list[UUID] = []
        for instrument in instruments:
            reason_code: str | None = None
            reason: str | None = None
            if instrument.exchange not in {"SSE", "SZSE", "BSE"} or instrument.market not in {
                "CN",
                "CN_A",
            }:
                reason_code, reason = "NOT_A_SHARE", "不是A股普通股票"
            elif bool(filters.get("exclude_bse")) and instrument.exchange == "BSE":
                reason_code, reason = "BSE_EXCLUDED", "已按设置排除北交所股票"
            elif bool(filters.get("exclude_star_market")) and instrument.symbol.startswith(
                ("688", "689")
            ):
                reason_code, reason = "STAR_MARKET_EXCLUDED", "已按设置排除科创板股票"
            elif bool(filters.get("exclude_chinext")) and instrument.symbol.startswith(
                ("300", "301")
            ):
                reason_code, reason = "CHINEXT_EXCLUDED", "已按设置排除创业板股票"
            elif bool(filters.get("exclude_st", True)) and is_st_instrument(instrument):
                reason_code, reason = "ST_EXCLUDED", "已按默认设置排除ST或*ST股票"
            elif is_delisting_instrument(instrument):
                reason_code, reason = "DELISTING_EXCLUDED", "已排除退市整理股票"
            elif instrument.id in manual:
                reason_code, reason = "MANUAL_EXCLUDED", "已由用户手动排除"
            elif (
                bool(filters.get("exclude_suspended", True))
                and trading_status.get(instrument.id) == "SUSPENDED"
            ):
                reason_code, reason = "SUSPENDED", "扫描日处于停牌状态"
            minimum_days = filters.get("minimum_listing_trading_days")
            if (
                reason_code is None
                and isinstance(minimum_days, int)
                and instrument.listed_at is not None
                and sum(session_date >= instrument.listed_at for session_date in open_sessions)
                < minimum_days
            ):
                reason_code, reason = "NEW_LISTING_EXCLUDED", "上市时间不足设定天数"
            status = (
                ScanMemberStatus.EXCLUDED if reason_code is not None else ScanMemberStatus.INCLUDED
            )
            if status is ScanMemberStatus.INCLUDED:
                included.append(instrument.id)
            members.append(
                ScanRunMember(
                    scan_run_id=run.id,
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    exchange=instrument.exchange,
                    instrument_name=instrument.name,
                    status=status,
                    reason_code=reason_code,
                    reason=reason,
                    required_bars=required_bars,
                )
            )
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
            await uow.scan_run_members.upsert_many(members)
            locked.instrument_ids = tuple(sorted(included, key=str))
            locked.total_instruments = len(instruments)
            locked.excluded_instruments = len(instruments) - len(included)
            locked.mark_phase(
                ScanRunStatus.CHECKING_DATA,
                datetime.now(UTC),
                progress_percent=15,
            )
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _prepare_data(
        self,
        run: ScanRun,
        required_bars: int,
        enqueue_backfill: BackfillEnqueuer,
    ) -> bool:
        if not run.instrument_ids:
            raise ApplicationError(
                "SCANNER_EMPTY_UNIVERSE",
                "应用排除条件后没有可扫描的A股股票",
            )
        start_at = run.as_of - timedelta(days=max(required_bars * 3, 90))
        async with self._uow_factory() as uow:
            bars = await uow.historical_bars.list_authoritative_bars(
                instrument_ids=run.instrument_ids,
                timeframe=MarketTimeframe.DAY_1,
                start_at=start_at,
                end_at=run.as_of + timedelta(microseconds=1),
                source_code=self._source_code,
                price_adjustment_mode=PriceAdjustmentMode.RAW,
            )
            members = await uow.scan_run_members.list_by_run(run.id)
        grouped: dict[UUID, list[StrategyBar]] = {item: [] for item in run.instrument_ids}
        for bar in bars:
            if bar.instrument_id in grouped:
                grouped[bar.instrument_id].append(bar)
        scan_date = run.as_of.astimezone(SHANGHAI).date()
        ready_ids: set[UUID] = set()
        missing_ids: list[UUID] = []
        for instrument_id, instrument_bars in grouped.items():
            has_latest = bool(instrument_bars) and (
                instrument_bars[-1].timestamp.astimezone(SHANGHAI).date() == scan_date
            )
            if len(instrument_bars) >= required_bars and has_latest:
                ready_ids.add(instrument_id)
            else:
                missing_ids.append(instrument_id)
        now = datetime.now(UTC)
        if missing_ids and run.backfill_requested == 0:
            instruments = await self._instruments(missing_ids)
            queue_errors = 0
            for offset in range(0, len(instruments), self._backfill_batch_size):
                batch = instruments[offset : offset + self._backfill_batch_size]
                try:
                    await enqueue_backfill(
                        {
                            "request_id": str(uuid4()),
                            "instrument_ids": [str(item.id) for item in batch],
                            "timeframe": MarketTimeframe.DAY_1.value,
                            "start_at": start_at.isoformat(),
                            "end_at": (run.as_of + timedelta(days=1)).isoformat(),
                            "instruments": [
                                {
                                    "instrument_id": str(item.id),
                                    "provider_symbol": miniqmt_provider_symbol(
                                        item.symbol, item.exchange
                                    ),
                                }
                                for item in batch
                            ],
                            "origin": "SC01_R",
                            "scan_run_id": str(run.id),
                        }
                    )
                except Exception:
                    queue_errors += len(batch)
            updated = []
            for member in members:
                if member.instrument_id in ready_ids:
                    member.status = ScanMemberStatus.READY
                    member.bars_available = len(grouped[member.instrument_id])
                elif member.instrument_id in grouped:
                    member.status = ScanMemberStatus.BACKFILL_REQUESTED
                    member.bars_available = len(grouped[member.instrument_id])
                    member.reason_code = "HISTORY_BACKFILL_REQUESTED"
                    member.reason = "已请求MiniQMT补齐历史日线"
                member.updated_at = now
                updated.append(member)
            async with self._uow_factory() as uow:
                locked = await uow.scan_runs.get_for_update(run.id)
                if locked is None:
                    raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
                await uow.scan_run_members.upsert_many(updated)
                locked.data_ready_instruments = len(ready_ids)
                locked.backfill_requested = len(missing_ids)
                locked.backfill_failed = queue_errors
                locked.backfill_requested_at = now
                locked.mark_phase(ScanRunStatus.BACKFILLING, now, progress_percent=35)
                await uow.scan_runs.update(locked)
                await uow.commit()
            return not missing_ids
        if (
            missing_ids
            and run.status is ScanRunStatus.BACKFILLING
            and run.backfill_requested_at is not None
            and (now - run.backfill_requested_at).total_seconds() < self._backfill_wait_seconds
        ):
            return False
        updated = []
        for member in members:
            if member.instrument_id in ready_ids:
                member.status = ScanMemberStatus.READY
                member.reason_code = None
                member.reason = None
                member.bars_available = len(grouped[member.instrument_id])
            elif member.instrument_id in grouped:
                member.status = ScanMemberStatus.DATA_MISSING
                member.reason_code = "INSUFFICIENT_HISTORY"
                member.reason = "MiniQMT历史日线不足或缺少扫描日日线"
                member.bars_available = len(grouped[member.instrument_id])
            member.updated_at = now
            updated.append(member)
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
            await uow.scan_run_members.upsert_many(updated)
            locked.instrument_ids = tuple(sorted(ready_ids, key=str))
            locked.data_ready_instruments = len(ready_ids)
            locked.insufficient_history = len(missing_ids)
            locked.mark_running(now)
            locked.progress_percent = 55
            await uow.scan_runs.update(locked)
            await uow.commit()
        return True

    async def _instruments(self, instrument_ids: list[UUID]) -> list[Instrument]:
        async with self._uow_factory() as uow:
            instruments = await uow.instruments.get_many(instrument_ids)
        return sorted(instruments, key=lambda item: (item.exchange, item.symbol, str(item.id)))

    async def _execute_ready(
        self,
        run: ScanRun,
        scanner: Scanner,
        validated: dict[str, ScannerParameterValue],
    ) -> None:
        instruments = await self._instruments(list(run.instrument_ids))
        start_at = run.as_of - timedelta(
            days=max(scanner_required_history_bars(run.scanner_key, validated) * 3, 90)
        )
        async with self._uow_factory() as uow:
            bars = await uow.historical_bars.list_authoritative_bars(
                instrument_ids=run.instrument_ids,
                timeframe=run.timeframe,
                start_at=start_at,
                end_at=run.as_of + timedelta(microseconds=1),
                source_code=self._source_code,
                price_adjustment_mode=PriceAdjustmentMode.RAW,
            )
            members = await uow.scan_run_members.list_by_run(run.id)
        grouped: dict[UUID, list[StrategyBar]] = {item.id: [] for item in instruments}
        for bar in bars:
            if bar.instrument_id in grouped:
                grouped[bar.instrument_id].append(bar)
        context = ScannerContext(as_of=run.as_of, timeframe=run.timeframe, parameters=validated)
        candidates = []
        failed: set[UUID] = set()
        for offset in range(0, len(instruments), self._scan_batch_size):
            batch = instruments[offset : offset + self._scan_batch_size]
            for instrument in batch:
                try:
                    candidate = scanner.scan(context, instrument, grouped[instrument.id])
                    if candidate is not None:
                        candidates.append(candidate)
                except (ScannerError, RuntimeError, ValueError):
                    failed.add(instrument.id)
            processed = offset + len(batch)
            if await self._update_scan_progress(run.id, processed, len(instruments)):
                await self._cancel(run)
                return
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
                metrics={
                    **stored_scanner_metrics(item.metrics),
                    **self._market_metrics(grouped[item.instrument_id]),
                    "price_adjustment_mode": PriceAdjustmentMode.RAW.value,
                    "reference_price_type": PriceAdjustmentMode.RAW.value,
                    "factor_source": None,
                    "data_source": self._source_code,
                },
                created_at=now,
            )
            for index, item in enumerate(candidates, start=1)
        ]
        matched = {item.instrument_id for item in results}
        updated = []
        for member in members:
            if member.instrument_id in failed:
                member.status = ScanMemberStatus.FAILED
                member.reason_code = "SCANNER_INSTRUMENT_FAILED"
                member.reason = "该股票规则计算失败"
            elif member.instrument_id in matched:
                member.status = ScanMemberStatus.MATCHED
            elif member.instrument_id in grouped:
                member.status = ScanMemberStatus.SCANNED
            member.updated_at = now
            updated.append(member)
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
            if locked.cancel_requested:
                locked.mark_canceled(now)
                await uow.scan_runs.update(locked)
                await uow.commit()
                return
            await uow.scan_results.append_many(results)
            await uow.scan_run_members.upsert_many(updated)
            locked.failed_instruments = len(failed)
            if locked.insufficient_history or locked.backfill_failed or failed:
                locked.mark_partial(now, len(instruments), len(results))
            else:
                locked.mark_completed(now, len(instruments), len(results))
            await uow.scan_runs.update(locked)
            await uow.commit()

    async def _update_scan_progress(self, run_id: UUID, processed: int, total: int) -> bool:
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run_id)
            if locked is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
            if locked.cancel_requested:
                return True
            locked.instruments_scanned = processed
            locked.progress_percent = 55 + int(processed / max(total, 1) * 44)
            locked.updated_at = datetime.now(UTC)
            await uow.scan_runs.update(locked)
            await uow.commit()
        return False

    @staticmethod
    def _market_metrics(bars: list[StrategyBar]) -> dict[str, str | None]:
        if not bars:
            return {}
        current = bars[-1]
        previous_close = bars[-2].close if len(bars) >= 2 else None
        daily_return = (
            None
            if previous_close is None or previous_close <= 0
            else current.close / previous_close - Decimal("1")
        )
        return {
            "current_close": format(current.close.normalize(), "f"),
            "current_volume": format(current.volume.normalize(), "f"),
            "current_amount": (
                None if current.amount is None else format(current.amount.normalize(), "f")
            ),
            "daily_return": (
                None if daily_return is None else format(daily_return.normalize(), "f")
            ),
            "market_data_time": current.timestamp.isoformat(),
            "data_source": "MINIQMT",
        }

    async def _cancel(self, run: ScanRun) -> None:
        async with self._uow_factory() as uow:
            locked = await uow.scan_runs.get_for_update(run.id)
            if locked is not None:
                locked.mark_canceled(datetime.now(UTC))
                await uow.scan_runs.update(locked)
                await uow.commit()

    async def _fail(self, run_id: UUID, exc: Exception) -> None:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is not None and run.status not in {
                ScanRunStatus.COMPLETED,
                ScanRunStatus.PARTIAL,
                ScanRunStatus.CANCELED,
            }:
                run.mark_failed(
                    datetime.now(UTC),
                    "SCAN_RUN_FAILED",
                    "全市场扫描任务执行失败",
                )
                await uow.scan_runs.update(run)
                await uow.commit()
        # Persist a bounded diagnostic for audit without leaking a traceback.
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is not None and run.status is ScanRunStatus.FAILED:
                run.error_message = f"全市场扫描任务执行失败: {str(exc)[:400]}"
                await uow.scan_runs.update(run)
                await uow.commit()


class ScannerRunService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: ScannerRegistry,
        *,
        authoritative_source_code: str | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._authoritative_source_code = (
            authoritative_source_code.strip().upper()
            if authoritative_source_code is not None
            else None
        )

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
                "price_adjustment_mode": request.price_adjustment_mode.value,
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
                price_adjustment_mode=request.price_adjustment_mode,
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
        if (
            request.scanner_key == "limit_up_pullback"
            and request.price_adjustment_mode is not PriceAdjustmentMode.RAW
        ):
            raise ApplicationError(
                "MARKET_ADJUSTMENT_MODE_NOT_SUPPORTED",
                "limit_up_pullback 必须使用 RAW 未复权价格",
            )
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
            if self._authoritative_source_code is None:
                bars = await uow.historical_bars.list_bars(
                    instrument_ids=run.instrument_ids,
                    timeframe=run.timeframe,
                    start_at=datetime(1970, 1, 1, tzinfo=UTC),
                    end_at=run.as_of + timedelta(microseconds=1),
                    price_adjustment_mode=run.price_adjustment_mode,
                )
            else:
                bars = await uow.historical_bars.list_authoritative_bars(
                    instrument_ids=run.instrument_ids,
                    timeframe=run.timeframe,
                    start_at=datetime(1970, 1, 1, tzinfo=UTC),
                    end_at=run.as_of + timedelta(microseconds=1),
                    source_code=self._authoritative_source_code,
                    price_adjustment_mode=run.price_adjustment_mode,
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
                    metrics={
                        **stored_scanner_metrics(item.metrics),
                        "price_adjustment_mode": run.price_adjustment_mode.value,
                        "reference_price_type": run.price_adjustment_mode.value,
                        "factor_source": (
                            "FIXTURE"
                            if run.price_adjustment_mode is PriceAdjustmentMode.QFQ
                            else None
                        ),
                    },
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

    async def result(self, run_id: UUID, result_id: UUID) -> ScanResultDto:
        items = await self.results(run_id)
        for item in items:
            if item.result.id == result_id:
                return item
        raise ApplicationError("SCAN_RESULT_NOT_FOUND", "扫描结果不存在")

    async def members(
        self, run_id: UUID, *, status: str | None = None
    ) -> tuple[list[ScanRunMember], dict[str, int]]:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_by_id(run_id)
            if run is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
            return (
                await uow.scan_run_members.list_by_run(run_id, status=status),
                await uow.scan_run_members.count_by_run(run_id),
            )

    async def cancel(self, run_id: UUID) -> ScanRun:
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_for_update(run_id)
            if run is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
            try:
                run.request_cancel(datetime.now(UTC))
            except ValueError as exc:
                raise ApplicationError(
                    "SCAN_RUN_CANNOT_CANCEL", "该扫描任务已经结束, 无法取消"
                ) from exc
            await uow.scan_runs.update(run)
            await uow.commit()
            return run


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
