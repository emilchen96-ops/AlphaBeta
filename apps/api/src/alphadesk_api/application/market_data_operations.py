"""D01-C/D/E daily updates, quality facts, coverage and readiness services."""

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import anyio

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.market_data import normalize_external_bar
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataIssueSeverity,
    MarketDataQualityRunStatus,
    MarketDataReadinessStatus,
    MarketDataSourceStatus,
    MarketSyncStatus,
    MarketTimeframe,
    SyncTriggerType,
)
from alphadesk_domain.market import (
    MarketBar,
    MarketDataCoverage,
    MarketDataQualityIssue,
    MarketDataQualityRun,
    MarketDataSource,
    MarketSyncRun,
)
from alphadesk_domain.market_adapters import (
    ExternalMarketBar,
    MarketDataAdapter,
    MarketDataAdapterError,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_READINESS_REQUIREMENTS: dict[str, int] = {
    "scanner_volume_anomaly": 21,
    "scanner_limit_up_pullback": 21,
    "strategy_sma_crossover": 20,
    "strategy_volume_breakout": 21,
    "strategy_trend_pullback": 30,
    "strategy_atr_channel": 20,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyInstrumentPlan:
    instrument_id: UUID
    symbol: str
    start_date: date
    target_date: date
    state: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DailyUpdateResult:
    run: MarketSyncRun | None
    target_date: date
    requested: int
    up_to_date: int
    completed: int
    failed: int
    unprocessed: int
    bars_fetched: int
    bars_inserted: int
    bars_updated: int
    bars_skipped: int
    invalid_bars: int
    retry_count: int
    failures: tuple[dict[str, str], ...]
    plans: tuple[DailyInstrumentPlan, ...]
    dry_run: bool
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentCoverageItem:
    instrument_id: UUID
    symbol: str
    name: str
    exchange: str
    bar_count: int
    earliest_bar: datetime | None
    latest_bar: datetime | None
    mapping_status: str
    missing_requirements: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseCoverage:
    universe_key: str
    name: str
    instrument_count: int
    instruments_with_data: int
    sufficient_instruments: int
    insufficient_instruments: int
    earliest_bar: datetime | None
    latest_bar: datetime | None
    latest_sync_at: datetime | None
    items: tuple[InstrumentCoverageItem, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadinessCapability:
    capability_key: str
    display_name: str
    status: MarketDataReadinessStatus
    ready_instrument_count: int
    total_instrument_count: int
    minimum_bars_required: int
    latest_data_date: date | None
    blocking_issue_count: int
    warning_count: int
    reason: str
    required_action: str
    code_status: str = "WORKING"


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataOverview:
    instrument_count: int
    active_a_share_count: int
    research_universe_count: int
    market_bar_count: int
    earliest_bar: datetime | None
    latest_bar: datetime | None
    latest_sync_at: datetime | None
    provider: str
    timeframe: MarketTimeframe
    adjustment_type: AdjustmentType
    scanner_ready: bool
    strategy_ready: bool
    backtest_data_ready: bool
    backtest_code_status: str


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityRunResult:
    run: MarketDataQualityRun
    issues: tuple[MarketDataQualityIssue, ...]


class DailyMarketDataUpdateService:
    """Update one bounded universe from each instrument's last local daily bar."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        default_start_date: date,
        max_instruments: int,
        batch_size: int,
        max_retries: int,
        request_interval_seconds: float,
        future_tolerance_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._default_start_date = default_start_date
        self._max_instruments = max_instruments
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._request_interval_seconds = request_interval_seconds
        self._future_tolerance = timedelta(seconds=future_tolerance_seconds)

    async def update(
        self,
        *,
        adapter: MarketDataAdapter,
        instruments: list[Instrument],
        universe_key: str,
        target_date: date | None,
        continue_on_error: bool,
        dry_run: bool,
        correlation_id: UUID,
        progress: Callable[[int, int, str, str], None] | None = None,
    ) -> DailyUpdateResult:
        resolved_target = self._target_date(target_date)
        ordered = sorted(instruments, key=lambda item: str(item.id))
        if not ordered or len(ordered) > self._max_instruments:
            raise ApplicationError(
                "MARKET_DATA_TOO_MANY_INSTRUMENTS",
                f"每日更新需要 1 到 {self._max_instruments} 个标的",
            )
        if adapter.source_code.upper() != "BAOSTOCK":
            raise ApplicationError("MARKET_DATA_PROVIDER_NOT_AVAILABLE", "每日更新仅支持 BaoStock")
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(adapter.source_code)
            if source is None or source.status is not MarketDataSourceStatus.ACTIVE:
                raise ApplicationError(
                    "MARKET_DATA_PROVIDER_NOT_AVAILABLE", "BaoStock 行情源未启用"
                )
            mappings = {
                instrument.id: mapping
                for instrument in ordered
                if (
                    mapping := await uow.instrument_mappings.get_by_source_and_instrument(
                        source.id, instrument.id
                    )
                )
                is not None
            }
            latest_values = await uow.market_bars.get_latest_for_instruments(
                instrument_ids=[item.id for item in ordered],
                source_id=source.id,
                timeframe=MarketTimeframe.DAY_1,
                adjustment_type=AdjustmentType.NONE,
            )
        latest = {item.instrument_id: item for item in latest_values}
        plans = tuple(
            DailyInstrumentPlan(
                instrument_id=item.id,
                symbol=item.symbol,
                start_date=(
                    latest[item.id].bar_time.date() + timedelta(days=1)
                    if item.id in latest
                    else self._default_start_date
                ),
                target_date=resolved_target,
                state=(
                    "MAPPING_MISSING"
                    if item.id not in mappings
                    else "UP_TO_DATE"
                    if item.id in latest and latest[item.id].bar_time.date() >= resolved_target
                    else "UPDATE_REQUIRED"
                ),
            )
            for item in ordered
        )
        if dry_run:
            missing = sum(item.state == "MAPPING_MISSING" for item in plans)
            return DailyUpdateResult(
                run=None,
                target_date=resolved_target,
                requested=len(ordered),
                up_to_date=sum(item.state == "UP_TO_DATE" for item in plans),
                completed=0,
                failed=missing,
                unprocessed=sum(item.state == "UPDATE_REQUIRED" for item in plans),
                bars_fetched=0,
                bars_inserted=0,
                bars_updated=0,
                bars_skipped=0,
                invalid_bars=0,
                retry_count=0,
                failures=tuple(
                    self._failure(item, "MARKET_DATA_MAPPING_MISSING")
                    for item in ordered
                    if item.id not in mappings
                ),
                plans=plans,
                dry_run=True,
            )

        operation_key = self._operation_key(
            adapter.source_code, universe_key, ordered, resolved_target
        )
        async with self._uow_factory() as uow:
            existing = await uow.market_sync_runs.get_by_operation_key(operation_key)
        if existing is not None and existing.status is not MarketSyncStatus.RUNNING:
            return self._from_existing(existing, resolved_target, plans)

        run = MarketSyncRun(
            source_id=source.id,
            trigger_type=SyncTriggerType.MANUAL,
            status=MarketSyncStatus.RUNNING,
            timeframe=MarketTimeframe.DAY_1,
            adjustment_type=AdjustmentType.NONE,
            requested_symbols=tuple(item.symbol for item in ordered),
            requested_start=datetime.combine(
                min(item.start_date for item in plans), time.min, tzinfo=UTC
            ),
            requested_end=datetime.combine(resolved_target, time.min, tzinfo=UTC),
            started_at=datetime.now(UTC),
            correlation_id=correlation_id,
            metadata={
                "operation": "DAILY_UPDATE",
                "operation_key": operation_key,
                "universe": universe_key,
                "target_date": resolved_target.isoformat(),
                "requested_instrument_count": len(ordered),
            },
        )
        async with self._uow_factory() as uow:
            await uow.market_sync_runs.add(run)
            await uow.commit()

        stats = Counter[str]()
        failures: list[dict[str, str]] = []
        processed = 0
        opened = False
        try:
            open_method = getattr(cast(Any, adapter), "open", None)
            if callable(open_method):
                await open_method()
                opened = True
            for index, (instrument, plan) in enumerate(zip(ordered, plans, strict=True), start=1):
                if plan.state == "MAPPING_MISSING":
                    stats["failed"] += 1
                    failures.append(self._failure(instrument, "MARKET_DATA_MAPPING_MISSING"))
                    processed += 1
                    if progress:
                        progress(index, len(ordered), instrument.symbol, "FAILED_MAPPING")
                    if not continue_on_error:
                        break
                    continue
                if plan.state == "UP_TO_DATE":
                    stats["up_to_date"] += 1
                    processed += 1
                    if progress:
                        progress(index, len(ordered), instrument.symbol, "UP_TO_DATE")
                    continue
                if processed and self._request_interval_seconds:
                    await anyio.sleep(self._request_interval_seconds)
                mapping = mappings[instrument.id]
                try:
                    external, retries = await self._fetch(
                        adapter,
                        mapping.external_symbol,
                        plan.start_date,
                        resolved_target,
                    )
                    stats["retry_count"] += retries
                except MarketDataAdapterError:
                    stats["failed"] += 1
                    failures.append(self._failure(instrument, "MARKET_DATA_UPDATE_FAILED"))
                    processed += 1
                    if progress:
                        progress(index, len(ordered), instrument.symbol, "FAILED_PROVIDER")
                    if not continue_on_error:
                        break
                    continue
                stats["bars_fetched"] += len(external)
                valid: list[MarketBar] = []
                seen: set[datetime] = set()
                previous: datetime | None = None
                for value in external:
                    try:
                        bar = normalize_external_bar(
                            value,
                            instrument_id=instrument.id,
                            source_id=source.id,
                            adjustment=AdjustmentType.NONE,
                            future_tolerance=self._future_tolerance,
                        )
                        if value.symbol.upper() != mapping.external_symbol.upper():
                            raise ValueError("provider symbol mismatch")
                        if previous is not None and bar.bar_time < previous:
                            raise ValueError("bar order invalid")
                        if bar.bar_time in seen:
                            raise ValueError("duplicate provider bar")
                        if not plan.start_date <= bar.bar_time.date() <= resolved_target:
                            raise ValueError("bar outside requested range")
                        seen.add(bar.bar_time)
                        previous = bar.bar_time
                        valid.append(bar)
                    except (ArithmeticError, TypeError, ValueError):
                        stats["invalid_bars"] += 1
                if external and not valid:
                    stats["failed"] += 1
                    failures.append(self._failure(instrument, "MARKET_DATA_UPDATE_FAILED"))
                    processed += 1
                    if not continue_on_error:
                        break
                    continue
                if valid:
                    async with self._uow_factory() as uow:
                        for offset in range(0, len(valid), self._batch_size):
                            result = await uow.market_bars.upsert_many(
                                valid[offset : offset + self._batch_size]
                            )
                            stats["bars_inserted"] += result.inserted
                            stats["bars_updated"] += result.updated
                            stats["bars_skipped"] += result.unchanged
                        await uow.commit()
                stats["completed"] += 1
                processed += 1
                if progress:
                    progress(index, len(ordered), instrument.symbol, "COMPLETED")
        except MarketDataAdapterError as exc:
            failures.append({"instrument_id": "", "symbol": "", "code": exc.__class__.__name__})
            stats["failed"] += len(ordered) - processed
            processed = len(ordered)
        finally:
            if opened:
                close_method = getattr(cast(Any, adapter), "close", None)
                if callable(close_method):
                    await close_method()

        unprocessed = len(ordered) - processed
        status = (
            MarketSyncStatus.FAILED
            if stats["failed"] and not (stats["completed"] or stats["up_to_date"])
            else MarketSyncStatus.PARTIALLY_SUCCEEDED
            if stats["failed"] or stats["invalid_bars"] or unprocessed
            else MarketSyncStatus.SUCCEEDED
        )
        completed_at = datetime.now(UTC)
        metadata: dict[str, object] = {
            **run.metadata,
            "up_to_date_instrument_count": stats["up_to_date"],
            "completed_instrument_count": stats["completed"],
            "failed_instrument_count": stats["failed"],
            "unprocessed_instrument_count": unprocessed,
            "bars_skipped": stats["bars_skipped"],
            "invalid_bars": stats["invalid_bars"],
            "retry_count": stats["retry_count"],
            "failures": failures[:100],
        }
        async with self._uow_factory() as uow:
            await uow.market_sync_runs.update_status(
                run.id,
                status=status,
                completed_at=completed_at,
                total_received=stats["bars_fetched"],
                total_inserted=stats["bars_inserted"],
                total_updated=stats["bars_updated"],
                total_rejected=stats["invalid_bars"],
                error_summary=";".join(item["code"] for item in failures[:20]) or None,
                metadata=metadata,
            )
            await uow.commit()
        completed_run = MarketSyncRun(
            **{
                **asdict(run),
                "status": status,
                "completed_at": completed_at,
                "total_received": stats["bars_fetched"],
                "total_inserted": stats["bars_inserted"],
                "total_updated": stats["bars_updated"],
                "total_rejected": stats["invalid_bars"],
                "error_summary": ";".join(item["code"] for item in failures[:20]) or None,
                "metadata": metadata,
            }
        )
        return DailyUpdateResult(
            run=completed_run,
            target_date=resolved_target,
            requested=len(ordered),
            up_to_date=stats["up_to_date"],
            completed=stats["completed"],
            failed=stats["failed"],
            unprocessed=unprocessed,
            bars_fetched=stats["bars_fetched"],
            bars_inserted=stats["bars_inserted"],
            bars_updated=stats["bars_updated"],
            bars_skipped=stats["bars_skipped"],
            invalid_bars=stats["invalid_bars"],
            retry_count=stats["retry_count"],
            failures=tuple(failures),
            plans=plans,
            dry_run=False,
        )

    async def _fetch(
        self, adapter: MarketDataAdapter, symbol: str, start: date, end: date
    ) -> tuple[list[ExternalMarketBar], int]:
        start_at = datetime.combine(start, time.min, tzinfo=UTC)
        end_at = datetime.combine(end, time.min, tzinfo=UTC)
        for attempt in range(self._max_retries + 1):
            try:
                values = [
                    item
                    async for item in adapter.fetch_bars(
                        [symbol],
                        MarketTimeframe.DAY_1,
                        start_at,
                        end_at,
                        AdjustmentType.NONE,
                    )
                ]
                return values, attempt
            except MarketDataAdapterError:
                if attempt >= self._max_retries:
                    raise
                await anyio.sleep(min(0.25 * (2**attempt), 1.0))
        raise AssertionError("retry loop exhausted")

    @staticmethod
    def _target_date(value: date | None) -> date:
        today = datetime.now(SHANGHAI).date()
        if value is not None:
            if value > today:
                raise ApplicationError(
                    "MARKET_DATA_INVALID_TARGET_DATE", "target_date 不得晚于当前本地日期"
                )
            return value
        return today - timedelta(days=1)

    @staticmethod
    def _operation_key(
        provider: str, universe_key: str, instruments: list[Instrument], target: date
    ) -> str:
        payload = json.dumps(
            {
                "provider": provider.upper(),
                "universe": universe_key,
                "instruments": [str(item.id) for item in instruments],
                "target": target.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode()).hexdigest()

    @staticmethod
    def _failure(instrument: Instrument, code: str) -> dict[str, str]:
        return {"instrument_id": str(instrument.id), "symbol": instrument.symbol, "code": code}

    @staticmethod
    def _from_existing(
        run: MarketSyncRun, target: date, plans: tuple[DailyInstrumentPlan, ...]
    ) -> DailyUpdateResult:
        metadata = run.metadata
        failures = tuple(cast(list[dict[str, str]], metadata.get("failures", [])))
        return DailyUpdateResult(
            run=run,
            target_date=target,
            requested=len(run.requested_symbols),
            up_to_date=int(metadata.get("up_to_date_instrument_count", 0)),
            completed=int(metadata.get("completed_instrument_count", 0)),
            failed=int(metadata.get("failed_instrument_count", 0)),
            unprocessed=int(metadata.get("unprocessed_instrument_count", 0)),
            bars_fetched=run.total_received,
            bars_inserted=run.total_inserted,
            bars_updated=run.total_updated,
            bars_skipped=int(metadata.get("bars_skipped", 0)),
            invalid_bars=run.total_rejected,
            retry_count=int(metadata.get("retry_count", 0)),
            failures=failures,
            plans=plans,
            dry_run=False,
            idempotent_replay=True,
        )


class MarketDataReadinessService:
    def __init__(self, uow_factory: UnitOfWorkFactory, *, backtest_minimum_bars: int) -> None:
        self._uow_factory = uow_factory
        self._requirements = {
            **DEFAULT_READINESS_REQUIREMENTS,
            "backtest_daily": backtest_minimum_bars,
        }

    async def coverage(
        self, *, instruments: list[Instrument], universe_key: str, provider: str
    ) -> UniverseCoverage:
        source, coverage, mapping_ids = await self._coverage(instruments, provider)
        by_id = {item.instrument_id: item for item in coverage}
        maximum = max(self._requirements.values())
        items_list: list[InstrumentCoverageItem] = []
        for instrument in instruments:
            value = by_id.get(instrument.id)
            bar_count = 0 if value is None else value.bar_count
            items_list.append(
                InstrumentCoverageItem(
                    instrument_id=instrument.id,
                    symbol=instrument.symbol,
                    name=instrument.name,
                    exchange=instrument.exchange,
                    bar_count=bar_count,
                    earliest_bar=None if value is None else value.earliest_bar,
                    latest_bar=None if value is None else value.latest_bar,
                    mapping_status="MAPPED" if instrument.id in mapping_ids else "MISSING",
                    missing_requirements=tuple(
                        key for key, required in self._requirements.items() if bar_count < required
                    ),
                )
            )
        items = tuple(items_list)
        async with self._uow_factory() as uow:
            runs = await uow.market_sync_runs.list_recent(100)
        matching = [run for run in runs if run.source_id == source.id]
        return UniverseCoverage(
            universe_key=universe_key,
            name="D01 Research Universe" if universe_key == "research" else universe_key,
            instrument_count=len(instruments),
            instruments_with_data=sum(item.bar_count > 0 for item in items),
            sufficient_instruments=sum(item.bar_count >= maximum for item in items),
            insufficient_instruments=sum(item.bar_count < maximum for item in items),
            earliest_bar=min(
                (item.earliest_bar for item in items if item.earliest_bar is not None),
                default=None,
            ),
            latest_bar=max(
                (item.latest_bar for item in items if item.latest_bar is not None), default=None
            ),
            latest_sync_at=max(
                (run.completed_at for run in matching if run.completed_at is not None), default=None
            ),
            items=items,
        )

    async def readiness(
        self, *, instruments: list[Instrument], provider: str
    ) -> tuple[ReadinessCapability, ...]:
        _, coverage, mapping_ids = await self._coverage(instruments, provider)
        by_id = {item.instrument_id: item for item in coverage}
        names = {
            "scanner_volume_anomaly": "放量异常 Scanner",
            "scanner_limit_up_pullback": "涨停回落 Scanner",
            "strategy_sma_crossover": "SMA 策略",
            "strategy_volume_breakout": "放量突破策略",
            "strategy_trend_pullback": "趋势回调策略",
            "strategy_atr_channel": "ATR 通道策略",
            "backtest_daily": "日线回测",
        }
        values = []
        total = len(instruments)
        latest = max(
            (item.latest_bar for item in coverage if item.latest_bar is not None), default=None
        )
        for key, required in self._requirements.items():
            ready = sum(
                instrument.id in mapping_ids
                and by_id.get(instrument.id) is not None
                and by_id[instrument.id].bar_count >= required
                for instrument in instruments
            )
            status = (
                MarketDataReadinessStatus.UNKNOWN
                if total == 0
                else MarketDataReadinessStatus.READY
                if ready == total
                else MarketDataReadinessStatus.PARTIAL
                if ready > 0
                else MarketDataReadinessStatus.NOT_READY
            )
            values.append(
                ReadinessCapability(
                    capability_key=key,
                    display_name=names[key],
                    status=status,
                    ready_instrument_count=ready,
                    total_instrument_count=total,
                    minimum_bars_required=required,
                    latest_data_date=None if latest is None else latest.date(),
                    blocking_issue_count=sum(item.id not in mapping_ids for item in instruments),
                    warning_count=total - ready,
                    reason=(
                        "全部研究标的满足最低日线数量。"
                        if status is MarketDataReadinessStatus.READY
                        else f"{ready}/{total} 个标的满足最低日线数量。"
                    ),
                    required_action=(
                        "无需数据操作。"
                        if status is MarketDataReadinessStatus.READY
                        else "先执行日线增量更新, 再运行数据质量检查。"
                    ),
                    code_status="PARTIAL" if key == "backtest_daily" else "WORKING",
                )
            )
        return tuple(values)

    async def overview(
        self, *, instruments: list[Instrument], universe_key: str, provider: str
    ) -> MarketDataOverview:
        coverage = await self.coverage(
            instruments=instruments, universe_key=universe_key, provider=provider
        )
        readiness = await self.readiness(instruments=instruments, provider=provider)
        async with self._uow_factory() as uow:
            _, active_count = await uow.instruments.search(
                keyword=None,
                exchange=None,
                market="CN_A",
                asset_type="STOCK",
                is_active=True,
                offset=0,
                limit=1,
            )
        by_key = {item.capability_key: item for item in readiness}
        return MarketDataOverview(
            instrument_count=active_count,
            active_a_share_count=active_count,
            research_universe_count=len(instruments),
            market_bar_count=sum(item.bar_count for item in coverage.items),
            earliest_bar=coverage.earliest_bar,
            latest_bar=coverage.latest_bar,
            latest_sync_at=coverage.latest_sync_at,
            provider=provider.upper(),
            timeframe=MarketTimeframe.DAY_1,
            adjustment_type=AdjustmentType.NONE,
            scanner_ready=all(
                by_key[key].status is MarketDataReadinessStatus.READY
                for key in ("scanner_volume_anomaly", "scanner_limit_up_pullback")
            ),
            strategy_ready=all(
                by_key[key].status is MarketDataReadinessStatus.READY
                for key in (
                    "strategy_sma_crossover",
                    "strategy_volume_breakout",
                    "strategy_trend_pullback",
                    "strategy_atr_channel",
                )
            ),
            backtest_data_ready=(
                by_key["backtest_daily"].status is MarketDataReadinessStatus.READY
            ),
            backtest_code_status="PARTIAL",
        )

    async def _coverage(
        self, instruments: list[Instrument], provider: str
    ) -> tuple[MarketDataSource, list[MarketDataCoverage], set[UUID]]:
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(provider)
            if source is None:
                raise ApplicationError(
                    "MARKET_DATA_PROVIDER_NOT_AVAILABLE", "请求的历史行情源不存在"
                )
            mapping_ids = {
                instrument.id
                for instrument in instruments
                if await uow.instrument_mappings.get_by_source_and_instrument(
                    source.id, instrument.id
                )
                is not None
            }
            coverage = await uow.market_bars.get_coverage(
                instrument_ids=[item.id for item in instruments],
                source_id=source.id,
                timeframe=MarketTimeframe.DAY_1,
                adjustment_type=AdjustmentType.NONE,
            )
        return source, coverage, mapping_ids


class MarketDataQualityService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        stale_calendar_days: int,
        minimum_bars: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._stale_days = stale_calendar_days
        self._minimum_bars = minimum_bars

    async def verify(
        self,
        *,
        instruments: list[Instrument],
        universe_key: str,
        provider: str,
        correlation_id: UUID,
        checked_at: datetime | None = None,
        range_start: datetime | None = None,
        range_end: datetime | None = None,
    ) -> QualityRunResult:
        now = (checked_at or datetime.now(UTC)).astimezone(UTC)
        run = MarketDataQualityRun(
            universe_key=universe_key,
            provider=provider.upper(),
            timeframe=MarketTimeframe.DAY_1,
            status=MarketDataQualityRunStatus.RUNNING,
            started_at=now,
            correlation_id=correlation_id,
        )
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(provider)
            if source is None:
                raise ApplicationError("MARKET_DATA_PROVIDER_NOT_AVAILABLE", "质量检查行情源不存在")
            await uow.market_data_quality_runs.add(run)
            await uow.commit()
        issues: list[MarketDataQualityIssue] = []
        bars_checked = 0
        try:
            for instrument in sorted(instruments, key=lambda item: str(item.id)):
                async with self._uow_factory() as uow:
                    mapping = await uow.instrument_mappings.get_by_source_and_instrument(
                        source.id, instrument.id
                    )
                    mappings = await uow.instrument_mappings.list_for_instrument(instrument.id)
                    bars = await uow.market_bars.get_bars(
                        instrument_id=instrument.id,
                        source_id=source.id,
                        timeframe=MarketTimeframe.DAY_1,
                        adjustment_type=AdjustmentType.NONE,
                        start=range_start or datetime(1990, 1, 1, tzinfo=UTC),
                        end=range_end or now,
                        limit=100_000,
                    )
                bars_checked += len(bars)
                issues.extend(
                    self._instrument_issues(run.id, instrument, mapping, mappings, bars, now)
                )
            counts = Counter(issue.severity for issue in issues)
            completed_at = datetime.now(UTC)
            metadata: dict[str, object] = {
                "minimum_bars": self._minimum_bars,
                "stale_calendar_days": self._stale_days,
                "range_start": None if range_start is None else range_start.isoformat(),
                "range_end": None if range_end is None else range_end.isoformat(),
                "issue_types": dict(Counter(issue.issue_type for issue in issues)),
            }
            async with self._uow_factory() as uow:
                await uow.market_data_quality_issues.add_many(issues)
                await uow.market_data_quality_runs.complete(
                    run.id,
                    status=MarketDataQualityRunStatus.COMPLETED,
                    completed_at=completed_at,
                    instruments_checked=len(instruments),
                    bars_checked=bars_checked,
                    error_count=counts[MarketDataIssueSeverity.ERROR],
                    warning_count=counts[MarketDataIssueSeverity.WARNING],
                    info_count=counts[MarketDataIssueSeverity.INFO],
                    metadata=metadata,
                )
                await uow.commit()
            completed = MarketDataQualityRun(
                id=run.id,
                universe_key=run.universe_key,
                provider=run.provider,
                timeframe=run.timeframe,
                status=MarketDataQualityRunStatus.COMPLETED,
                instruments_checked=len(instruments),
                bars_checked=bars_checked,
                issues_found=len(issues),
                error_count=counts[MarketDataIssueSeverity.ERROR],
                warning_count=counts[MarketDataIssueSeverity.WARNING],
                info_count=counts[MarketDataIssueSeverity.INFO],
                started_at=run.started_at,
                completed_at=completed_at,
                correlation_id=run.correlation_id,
                metadata=metadata,
                created_at=run.created_at,
                updated_at=completed_at,
            )
            return QualityRunResult(run=completed, issues=tuple(issues))
        except Exception as exc:
            completed_at = datetime.now(UTC)
            async with self._uow_factory() as uow:
                await uow.market_data_quality_runs.complete(
                    run.id,
                    status=MarketDataQualityRunStatus.FAILED,
                    completed_at=completed_at,
                    instruments_checked=0,
                    bars_checked=0,
                    error_count=0,
                    warning_count=0,
                    info_count=0,
                    metadata={"error_code": type(exc).__name__},
                )
                await uow.commit()
            raise ApplicationError("MARKET_DATA_QUALITY_CHECK_FAILED", "数据质量检查失败") from exc

    def _instrument_issues(
        self,
        run_id: UUID,
        instrument: Instrument,
        mapping: Any,
        mappings: list[Any],
        bars: list[MarketBar],
        now: datetime,
    ) -> list[MarketDataQualityIssue]:
        issues: list[MarketDataQualityIssue] = []

        def issue(
            issue_type: str,
            severity: MarketDataIssueSeverity,
            message: str,
            *,
            observed: str | None = None,
            expected: str | None = None,
            first: datetime | None = None,
            last: datetime | None = None,
            action: str | None = None,
        ) -> None:
            issues.append(
                MarketDataQualityIssue(
                    quality_run_id=run_id,
                    instrument_id=instrument.id,
                    issue_type=issue_type,
                    severity=severity,
                    timeframe=MarketTimeframe.DAY_1,
                    first_affected_at=first,
                    last_affected_at=last,
                    observed_value=observed,
                    expected_value=expected,
                    message=message,
                    required_action=action,
                    metadata={"symbol": instrument.symbol, "exchange": instrument.exchange},
                )
            )

        if mapping is None:
            issue(
                "MAPPING_MISSING",
                MarketDataIssueSeverity.ERROR,
                "活跃标的缺少 BaoStock Mapping。",
                action="先同步 A 股 Instrument 与 BaoStock Mapping。",
            )
        elif not self._mapping_valid(instrument, mapping.external_symbol):
            issue(
                "MAPPING_INVALID",
                MarketDataIssueSeverity.ERROR,
                "BaoStock 外部代码与交易所不一致。",
                observed=mapping.external_symbol,
                expected=instrument.symbol,
                action="重新同步并核对 Instrument Mapping。",
            )
        if len(mappings) > 1:
            issue(
                "MULTIPLE_SOURCES",
                MarketDataIssueSeverity.WARNING,
                "标的映射到多个行情源, 研究前需确认目标日期范围只有一个权威来源。",
                observed=str(len(mappings)),
                expected="1 authoritative source per range",
            )
        if not bars:
            issue(
                "NO_MARKET_DATA",
                MarketDataIssueSeverity.WARNING,
                "当前检查范围没有日线数据。",
                observed="0",
                expected=str(self._minimum_bars),
                action="执行历史补数或每日增量更新。",
            )
            return issues
        seen: set[datetime] = set()
        previous: MarketBar | None = None
        for bar in bars:
            if bar.bar_time in seen:
                issue(
                    "DUPLICATE_BAR",
                    MarketDataIssueSeverity.ERROR,
                    "发现重复 K 线业务时间。",
                    first=bar.bar_time,
                    last=bar.bar_time,
                )
            seen.add(bar.bar_time)
            if previous is not None and bar.bar_time <= previous.bar_time:
                issue(
                    "TIME_ORDER_INVALID",
                    MarketDataIssueSeverity.ERROR,
                    "日线时间不是严格升序。",
                    first=previous.bar_time,
                    last=bar.bar_time,
                )
            if previous is not None and (bar.bar_time - previous.bar_time).days > 21:
                issue(
                    "LONG_CALENDAR_GAP",
                    MarketDataIssueSeverity.INFO,
                    "相邻日线存在较长自然日间隔; 可能是长假、停牌或数据缺口。",
                    observed=str((bar.bar_time - previous.bar_time).days),
                    expected="<=21 calendar days heuristic",
                    first=previous.bar_time,
                    last=bar.bar_time,
                )
            if bar.bar_time.date() > now.date():
                issue(
                    "FUTURE_BAR",
                    MarketDataIssueSeverity.ERROR,
                    "发现明显未来日期 K 线。",
                    first=bar.bar_time,
                    last=bar.bar_time,
                )
            if (
                min(bar.open, bar.high, bar.low, bar.close) <= 0
                or bar.high < max(bar.open, bar.close, bar.low)
                or bar.low > min(bar.open, bar.close, bar.high)
            ):
                issue(
                    "OHLC_INVALID",
                    MarketDataIssueSeverity.ERROR,
                    "OHLC 关系或正数约束异常。",
                    first=bar.bar_time,
                    last=bar.bar_time,
                )
            if bar.volume < 0 or (bar.amount is not None and bar.amount < 0):
                issue(
                    "NEGATIVE_TURNOVER",
                    MarketDataIssueSeverity.ERROR,
                    "成交量或成交额为负数。",
                    first=bar.bar_time,
                    last=bar.bar_time,
                )
            previous = bar
        latest = bars[-1].bar_time
        age = (now.date() - latest.date()).days
        if instrument.is_active and age > self._stale_days:
            issue(
                "STALE_DATA",
                MarketDataIssueSeverity.WARNING,
                "最后一根日线超过新鲜度阈值; 周末、长假或停牌可能合理。",
                observed=str(age),
                expected=f"<={self._stale_days} calendar days",
                first=latest,
                last=latest,
                action="核对市场日期后执行每日增量更新。",
            )
        if len(bars) < self._minimum_bars:
            issue(
                "INSUFFICIENT_BARS",
                MarketDataIssueSeverity.WARNING,
                "日线数量低于受控研究/回测基线。",
                observed=str(len(bars)),
                expected=str(self._minimum_bars),
                first=bars[0].bar_time,
                last=bars[-1].bar_time,
                action="扩大历史补数起始范围。",
            )
        return issues

    @staticmethod
    def _mapping_valid(instrument: Instrument, external_symbol: str) -> bool:
        normalized = external_symbol.lower()
        if normalized.startswith(("sh.", "sz.", "bj.")):
            prefix, symbol = normalized.split(".", 1)
        else:
            symbol = normalized
            prefix = (
                "sh" if symbol.startswith("6") else "bj" if symbol.startswith(("4", "8")) else "sz"
            )
        expected = {"SSE": "sh", "SZSE": "sz", "BSE": "bj"}.get(instrument.exchange)
        return symbol.upper() == instrument.symbol.upper() and prefix == expected


class MarketDataQualityQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list_runs(
        self, *, page: int, page_size: int
    ) -> tuple[list[MarketDataQualityRun], int]:
        async with self._uow_factory() as uow:
            return await uow.market_data_quality_runs.list_recent(
                offset=(page - 1) * page_size, limit=page_size
            )

    async def run(self, run_id: UUID) -> MarketDataQualityRun:
        async with self._uow_factory() as uow:
            value = await uow.market_data_quality_runs.get_by_id(run_id)
        if value is None:
            raise ApplicationError("MARKET_DATA_QUALITY_RUN_NOT_FOUND", "数据质量运行不存在")
        return value

    async def issues(
        self,
        run_id: UUID,
        *,
        page: int,
        page_size: int,
        severity: MarketDataIssueSeverity | None = None,
        issue_type: str | None = None,
        instrument_id: UUID | None = None,
    ) -> tuple[list[MarketDataQualityIssue], int]:
        await self.run(run_id)
        async with self._uow_factory() as uow:
            return await uow.market_data_quality_issues.list_for_run(
                run_id,
                offset=(page - 1) * page_size,
                limit=page_size,
                severity=severity,
                issue_type=issue_type,
                instrument_id=instrument_id,
            )


class MarketDataQualityIntegrityService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def verify(self, run_id: UUID) -> tuple[str, ...]:
        async with self._uow_factory() as uow:
            run = await uow.market_data_quality_runs.get_by_id(run_id)
            if run is None:
                raise ApplicationError("MARKET_DATA_QUALITY_RUN_NOT_FOUND", "数据质量运行不存在")
            counts = await uow.market_data_quality_issues.count_by_severity(run_id)
        mismatches = []
        expected = {
            MarketDataIssueSeverity.ERROR: run.error_count,
            MarketDataIssueSeverity.WARNING: run.warning_count,
            MarketDataIssueSeverity.INFO: run.info_count,
        }
        for severity, value in expected.items():
            if counts.get(severity, 0) != value:
                mismatches.append(f"{severity.value}_COUNT_MISMATCH")
        if sum(counts.values()) != run.issues_found:
            mismatches.append("ISSUE_TOTAL_MISMATCH")
        if (
            run.status
            in (
                MarketDataQualityRunStatus.COMPLETED,
                MarketDataQualityRunStatus.FAILED,
            )
            and run.completed_at is None
        ):
            mismatches.append("COMPLETED_AT_MISSING")
        return tuple(mismatches)
