"""D03 offline intraday import, aggregation, quality and query services."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import perf_counter
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from alphadesk_api.application.catalog import InstrumentCatalogService
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.market_reference import AdjustedHistoricalMarketDataService
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataIssueSeverity,
    MarketDataQualityRunStatus,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketSyncStatus,
    MarketTimeframe,
    SyncTriggerType,
)
from alphadesk_domain.intraday import (
    AGGREGATION_VERSION,
    INTRADAY_TIMEFRAMES,
    AggregationResult,
    IntradayAggregationIntegrityService,
    IntradayBarAggregator,
    IntradayConflictPolicy,
    IntradayExternalBar,
    IntradayMarketDataProvider,
    IntradaySessionTemplate,
)
from alphadesk_domain.market import (
    MarketBar,
    MarketDataQualityIssue,
    MarketDataQualityRun,
    MarketSyncRun,
)
from alphadesk_domain.market_adapters import ExternalInstrument
from alphadesk_domain.market_reference import (
    CalendarSessionType,
    FactorConvention,
    InstrumentTradingState,
    InstrumentTradingStatus,
    PriceAdjustmentMode,
    TradingCalendarSession,
)


def bars_equal(left: MarketBar, right: MarketBar) -> bool:
    return all(
        getattr(left, name) == getattr(right, name)
        for name in ("open", "high", "low", "close", "volume", "amount")
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class IntradayImportResult:
    run: MarketSyncRun | None
    rows_read: int
    rows_valid: int
    rows_invalid: int
    bars_inserted: int
    bars_updated: int
    bars_skipped: int
    conflicts: int
    aggregated_bars_created: int
    incomplete_windows: int
    duration_seconds: float
    errors: tuple[str, ...]


class IntradayMarketDataImportService:
    def __init__(self, uow_factory: UnitOfWorkFactory, *, batch_size: int = 500) -> None:
        self._uow_factory = uow_factory
        self._batch_size = batch_size
        self._template = IntradaySessionTemplate()
        self._instrument_cache: dict[tuple[str, str], Instrument] = {}
        self._missing_instrument_keys: set[tuple[str, str]] = set()

    async def _persist_batch(
        self, bars: list[MarketBar], policy: IntradayConflictPolicy
    ) -> tuple[int, int, int, int]:
        async with self._uow_factory() as uow:
            existing = await uow.market_bars.get_existing(bars)
            by_key = {
                (
                    bar.instrument_id,
                    bar.source_id,
                    bar.timeframe,
                    bar.adjustment_type,
                    bar.bar_time,
                ): bar
                for bar in existing
            }
            new: list[MarketBar] = []
            changed: list[MarketBar] = []
            skipped = conflicts = 0
            for bar in bars:
                key = (
                    bar.instrument_id,
                    bar.source_id,
                    bar.timeframe,
                    bar.adjustment_type,
                    bar.bar_time,
                )
                current = by_key.get(key)
                if current is None:
                    new.append(bar)
                elif bars_equal(current, bar):
                    skipped += 1
                else:
                    conflicts += 1
                    if policy is IntradayConflictPolicy.REJECT:
                        raise ApplicationError("INTRADAY_DATA_CONFLICT", "分钟Bar与现有事实冲突")
                    if policy is IntradayConflictPolicy.UPDATE_SAME_SOURCE:
                        changed.append(bar)
            result = await uow.market_bars.upsert_many(new + changed)
            await uow.commit()
            return result.inserted, result.updated, skipped, conflicts

    async def run(
        self,
        provider: IntradayMarketDataProvider,
        *,
        source_code: str,
        source_timezone: str | None,
        target_timeframes: tuple[MarketTimeframe, ...] = (),
        conflict_policy: IntradayConflictPolicy = IntradayConflictPolicy.KEEP_EXISTING,
        continue_on_error: bool = True,
        dry_run: bool = False,
        correlation_id: UUID | None = None,
    ) -> IntradayImportResult:
        started = perf_counter()
        correlation = correlation_id or uuid4()
        try:
            provider.validate_configuration()
        except ValueError as exc:
            raise ApplicationError(str(exc), "分钟行情Provider配置不可用") from exc
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(source_code)
            if source is None and not dry_run:
                raise ApplicationError("INTRADAY_PROVIDER_NOT_AVAILABLE", "分钟行情源不存在")
        source_id = source.id if source is not None else UUID(int=0)
        run: MarketSyncRun | None = None
        if not dry_run:
            run = MarketSyncRun(
                source_id=source_id,
                trigger_type=SyncTriggerType.CLI,
                status=MarketSyncStatus.RUNNING,
                timeframe=MarketTimeframe.MINUTE_1,
                adjustment_type=AdjustmentType.NONE,
                requested_symbols=(),
                started_at=datetime.now(UTC),
                correlation_id=correlation,
                metadata={
                    "operation_type": "INTRADAY_IMPORT",
                    "provider": provider.provider_key,
                    "source_timezone": source_timezone,
                    "target_timeframes": [item.value for item in target_timeframes],
                    "conflict_policy": conflict_policy.value,
                },
            )
            async with self._uow_factory() as uow:
                await uow.market_sync_runs.add(run)
                await uow.commit()
        counts: Counter[str] = Counter()
        errors: list[str] = []
        pending: list[MarketBar] = []
        touched: dict[UUID, tuple[datetime, datetime]] = {}
        try:
            async for row in provider.fetch_bars():
                counts["rows_read"] += 1
                try:
                    bar = await self._normalize(
                        row,
                        source_id,
                        source_timezone,
                        allow_unmapped=dry_run,
                    )
                    counts["rows_valid"] += 1
                    pending.append(bar)
                    current = touched.get(bar.instrument_id)
                    touched[bar.instrument_id] = (
                        min(current[0], bar.bar_time) if current else bar.bar_time,
                        max(current[1], bar.bar_time) if current else bar.bar_time,
                    )
                    if len(pending) >= self._batch_size:
                        if not dry_run:
                            values = await self._persist_batch(pending, conflict_policy)
                            for key, value in zip(
                                ("bars_inserted", "bars_updated", "bars_skipped", "conflicts"),
                                values,
                                strict=True,
                            ):
                                counts[key] += value
                        pending.clear()
                except (ValueError, InvalidOperation, ApplicationError) as exc:
                    counts["rows_invalid"] += 1
                    errors.append(f"row {counts['rows_read']}: {exc}")
                    if not continue_on_error:
                        raise
            if pending and not dry_run:
                values = await self._persist_batch(pending, conflict_policy)
                for key, value in zip(
                    ("bars_inserted", "bars_updated", "bars_skipped", "conflicts"),
                    values,
                    strict=True,
                ):
                    counts[key] += value
            if target_timeframes and not dry_run:
                for instrument_id, (start, end) in touched.items():
                    aggregate = await IntradayAggregationService(self._uow_factory).run(
                        instrument_id=instrument_id,
                        source_code=source_code,
                        start_at=start,
                        end_at=end + timedelta(minutes=1),
                        targets=target_timeframes,
                        dry_run=False,
                        correlation_id=correlation,
                    )
                    counts["aggregated_bars_created"] += aggregate[0]
                    counts["incomplete_windows"] += aggregate[1]
        except Exception as exc:
            errors.append(str(exc))
            if not continue_on_error:
                await self._complete_run(run, counts, errors, failed=True)
                raise
        await self._complete_run(run, counts, errors, failed=False)
        return IntradayImportResult(
            run=run,
            duration_seconds=perf_counter() - started,
            errors=tuple(errors[:100]),
            **{
                field: counts[field]
                for field in (
                    "rows_read",
                    "rows_valid",
                    "rows_invalid",
                    "bars_inserted",
                    "bars_updated",
                    "bars_skipped",
                    "conflicts",
                    "aggregated_bars_created",
                    "incomplete_windows",
                )
            },
        )

    async def _normalize(
        self,
        row: IntradayExternalBar,
        source_id: UUID,
        source_timezone: str | None,
        *,
        allow_unmapped: bool,
    ) -> MarketBar:
        if row.adjustment_mode is not AdjustmentType.NONE:
            raise ValueError("RAW is the only authoritative import adjustment mode")
        timestamp = self._template.normalize(row.timestamp, source_timezone)
        if row.timeframe not in INTRADAY_TIMEFRAMES:
            raise ValueError("INTRADAY_TIMEFRAME_NOT_SUPPORTED")
        if not self._template.validate_bar_start(timestamp, row.timeframe):
            raise ValueError("INTRADAY_OUTSIDE_SESSION")
        key = (row.exchange, row.symbol)
        instrument = self._instrument_cache.get(key)
        if instrument is None and key not in self._missing_instrument_keys:
            async with self._uow_factory() as uow:
                instrument = await uow.instruments.get_by_business_key(*key)
            if instrument is not None:
                self._instrument_cache[key] = instrument
            else:
                self._missing_instrument_keys.add(key)
        if instrument is None and not allow_unmapped:
            raise ValueError("INTRADAY_INSTRUMENT_MAPPING_MISSING")
        instrument_id = (
            instrument.id
            if instrument is not None
            else uuid5(NAMESPACE_URL, f"d03-dry-run:{row.exchange}:{row.symbol}")
        )
        return MarketBar(
            instrument_id=instrument_id,
            source_id=source_id,
            timeframe=row.timeframe,
            adjustment_type=AdjustmentType.NONE,
            bar_time=timestamp,
            open=Decimal(row.open),
            high=Decimal(row.high),
            low=Decimal(row.low),
            close=Decimal(row.close),
            volume=Decimal(row.volume),
            amount=None if row.amount is None else Decimal(row.amount),
            received_at=datetime.now(UTC),
            quality_status=MarketDataQualityStatus.NORMAL,
            quality_flags={
                "provider_symbol": row.symbol,
                "provider": row.source or "LOCAL",
                **row.metadata,
            },
        )

    async def _complete_run(
        self, run: MarketSyncRun | None, counts: Counter[str], errors: list[str], *, failed: bool
    ) -> None:
        if run is None:
            return
        status = (
            MarketSyncStatus.FAILED
            if failed and not counts["rows_valid"]
            else MarketSyncStatus.PARTIALLY_SUCCEEDED
            if errors or counts["conflicts"]
            else MarketSyncStatus.SUCCEEDED
        )
        metadata = dict(run.metadata)
        metadata.update({key: int(value) for key, value in counts.items()})
        metadata["errors"] = errors[:100]
        async with self._uow_factory() as uow:
            await uow.market_sync_runs.update_status(
                run.id,
                status=status,
                completed_at=datetime.now(UTC),
                total_received=counts["rows_read"],
                total_inserted=counts["bars_inserted"],
                total_updated=counts["bars_updated"],
                total_rejected=counts["rows_invalid"],
                error_summary="; ".join(errors[:3])[:1000] or None,
                metadata=metadata,
            )
            await uow.commit()
        run.status = status
        run.metadata = metadata
        run.completed_at = datetime.now(UTC)
        run.total_received = counts["rows_read"]
        run.total_inserted = counts["bars_inserted"]
        run.total_updated = counts["bars_updated"]
        run.total_rejected = counts["rows_invalid"]
        run.error_summary = "; ".join(errors[:3])[:1000] or None


class IntradayAggregationService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory
        self._aggregator = IntradayBarAggregator()

    async def run(
        self,
        *,
        instrument_id: UUID,
        source_code: str,
        start_at: datetime,
        end_at: datetime,
        targets: tuple[MarketTimeframe, ...],
        dry_run: bool,
        correlation_id: UUID | None = None,
    ) -> tuple[int, int, list[MarketBar]]:
        if start_at.tzinfo is None or end_at.tzinfo is None or start_at >= end_at:
            raise ApplicationError("INTRADAY_AGGREGATION_FAILED", "聚合范围无效")
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(source_code)
            if source is None:
                raise ApplicationError("INTRADAY_PROVIDER_NOT_AVAILABLE", "分钟行情源不存在")
            one_minute = await uow.market_bars.get_bars(
                instrument_id=instrument_id,
                source_id=source.id,
                timeframe=MarketTimeframe.MINUTE_1,
                adjustment_type=AdjustmentType.NONE,
                start=start_at,
                end=end_at - timedelta(microseconds=1),
                limit=100_000,
            )
        output: list[MarketBar] = []
        incomplete = 0
        for target in targets:
            result: AggregationResult = self._aggregator.aggregate(one_minute, target)
            output.extend(result.bars)
            incomplete += len(result.incomplete_windows)
        inserted = 0
        if output and not dry_run:
            async with self._uow_factory() as uow:
                write_result = await uow.market_bars.upsert_many(output)
                inserted = write_result.inserted
                await uow.commit()
        del correlation_id
        return inserted, incomplete, output


class IntradayQueryService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        max_bars: int = 5_000,
        max_date_range_days: int = 31,
    ) -> None:
        self._uow_factory = uow_factory
        self._max_bars = max_bars
        self._max_date_range_days = max_date_range_days

    async def bars(
        self,
        *,
        instrument_id: UUID,
        source_code: str,
        timeframe: MarketTimeframe,
        start_at: datetime,
        end_at: datetime,
        adjustment_mode: PriceAdjustmentMode,
        limit: int,
    ) -> list[MarketBar]:
        if timeframe not in INTRADAY_TIMEFRAMES:
            raise ApplicationError("INTRADAY_TIMEFRAME_NOT_SUPPORTED", "仅支持分钟周期")
        if start_at.tzinfo is None or end_at.tzinfo is None or start_at >= end_at:
            raise ApplicationError("INTRADAY_INVALID_TIMESTAMP", "必须提供有效的aware时间范围")
        if limit > self._max_bars:
            raise ApplicationError("INTRADAY_QUERY_TOO_LARGE", "查询超过服务端Bar上限")
        if end_at - start_at > timedelta(days=self._max_date_range_days):
            raise ApplicationError("INTRADAY_QUERY_TOO_LARGE", "查询超过服务端日期范围上限")
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(source_code)
            if source is None:
                raise ApplicationError("INTRADAY_PROVIDER_NOT_AVAILABLE", "分钟行情源不存在")
            bars = await uow.market_bars.get_bars(
                instrument_id=instrument_id,
                source_id=source.id,
                timeframe=timeframe,
                adjustment_type=AdjustmentType.NONE,
                start=start_at,
                end=end_at - timedelta(microseconds=1),
                limit=limit,
            )
        adjusted = await AdjustedHistoricalMarketDataService(self._uow_factory).adjust_existing(
            bars, adjustment_mode
        )
        return [item.as_market_bar() for item in adjusted]


class IntradayOverviewService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory
        self._template = IntradaySessionTemplate()

    async def coverage(
        self,
        source_code: str = "MINIQMT",
        *,
        instrument_id: UUID | None = None,
        timeframe: MarketTimeframe | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> list[dict[str, object]]:
        if (start_at is None) != (end_at is None):
            raise ApplicationError("INTRADAY_INVALID_TIMESTAMP", "覆盖度开始和结束时间必须同时提供")
        if start_at is not None and (
            start_at.tzinfo is None or end_at is None or end_at.tzinfo is None or start_at >= end_at
        ):
            raise ApplicationError("INTRADAY_INVALID_TIMESTAMP", "覆盖度时间范围无效")
        if timeframe is not None and timeframe not in INTRADAY_TIMEFRAMES:
            raise ApplicationError("INTRADAY_TIMEFRAME_NOT_SUPPORTED", "仅支持分钟周期")
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(source_code)
            instruments, _ = await uow.instruments.search(
                keyword=None,
                exchange=None,
                market=None,
                asset_type="STOCK",
                is_active=True,
                offset=0,
                limit=500,
            )
            if instrument_id is not None:
                instruments = [item for item in instruments if item.id == instrument_id]
            if source is None:
                return []
            one_minute_coverage = await uow.market_bars.get_coverage(
                instrument_ids=[item.id for item in instruments],
                source_id=source.id,
                timeframe=MarketTimeframe.MINUTE_1,
                adjustment_type=AdjustmentType.NONE,
                start=start_at,
                end=end_at,
            )
            covered_ids = {item.instrument_id for item in one_minute_coverage}
            covered_instruments = [item for item in instruments if item.id in covered_ids]
            values: list[dict[str, object]] = []
            statuses = await uow.instrument_trading_statuses.list(
                instrument_ids=[item.id for item in covered_instruments],
                start=(self._template.local(start_at).date() if start_at else None),
                end=(
                    self._template.local(end_at - timedelta(microseconds=1)).date()
                    if end_at
                    else None
                ),
                limit=10_000,
            )
            tradable_sessions = sum(
                item.status in {InstrumentTradingState.TRADING, InstrumentTradingState.RESUMED}
                for item in statuses
            )
            tradable_keys = {
                (item.instrument_id, item.session_date)
                for item in statuses
                if item.status in {InstrumentTradingState.TRADING, InstrumentTradingState.RESUMED}
            }
            factor_rows = await uow.adjustment_factors.list(
                instrument_ids=[item.id for item in covered_instruments],
                start=min((item[1] for item in tradable_keys), default=None),
                end=max((item[1] for item in tradable_keys), default=None),
                source=None,
                convention=FactorConvention.TUSHARE_CUMULATIVE,
                limit=100_000,
            )
            factor_keys = {(item.instrument_id, item.trade_date) for item in factor_rows}
            qfq_ready = bool(tradable_keys) and tradable_keys <= factor_keys
            quality_runs, _ = await uow.market_data_quality_runs.list_recent(offset=0, limit=500)
            recent_quality = [
                item
                for item in quality_runs
                if item.metadata.get("scope") == "D03_INTRADAY" and item.provider == source_code
            ]
            sync_runs = await uow.market_sync_runs.list_recent(500)
            latest_import_at = max(
                (
                    item.completed_at or item.started_at
                    for item in sync_runs
                    if item.source_id == source.id
                    and item.metadata.get("operation_type") == "INTRADAY_IMPORT"
                ),
                default=None,
            )
            requested_timeframes = (timeframe,) if timeframe is not None else INTRADAY_TIMEFRAMES
            for requested_timeframe in requested_timeframes:
                rows = (
                    one_minute_coverage
                    if requested_timeframe is MarketTimeframe.MINUTE_1
                    else await uow.market_bars.get_coverage(
                        instrument_ids=[item.id for item in covered_instruments],
                        source_id=source.id,
                        timeframe=requested_timeframe,
                        adjustment_type=AdjustmentType.NONE,
                        start=start_at,
                        end=end_at,
                    )
                )
                bar_count = sum(item.bar_count for item in rows)
                expected_bar_count = tradable_sessions * self._template.expected_count(
                    requested_timeframe
                )
                missing_bar_count = max(expected_bar_count - bar_count, 0)
                values.append(
                    {
                        "timeframe": requested_timeframe.value,
                        "instrument_count": len(rows),
                        "bar_count": bar_count,
                        "earliest_at": min(
                            (item.earliest_bar for item in rows if item.earliest_bar), default=None
                        ),
                        "latest_at": max(
                            (item.latest_bar for item in rows if item.latest_bar), default=None
                        ),
                        "expected_bar_count": expected_bar_count,
                        "missing_bar_count": missing_bar_count,
                        "complete_session_count": max(
                            tradable_sessions - (1 if missing_bar_count else 0),
                            0,
                        ),
                        "missing_session_count": 1 if missing_bar_count else 0,
                        "raw_coverage": bar_count,
                        "qfq_coverage": bar_count if qfq_ready else 0,
                        "quality_error_count": sum(
                            item.error_count
                            for item in recent_quality
                            if item.timeframe is requested_timeframe
                        ),
                        "latest_import_at": latest_import_at,
                        "source_code": source_code,
                    }
                )
            return values

    async def readiness(self, source_code: str = "MINIQMT") -> list[dict[str, object]]:
        coverage = await self.coverage(source_code)
        by_timeframe = {item["timeframe"]: item for item in coverage}
        result = []
        for timeframe in INTRADAY_TIMEFRAMES:
            item = by_timeframe[timeframe.value]
            ready = bool(item["bar_count"])
            result.append(
                {
                    "capability_key": f"intraday_{timeframe.value.split('_')[1]}m_ready",
                    "timeframe": timeframe.value,
                    "status": "READY" if ready else "NOT_READY",
                    "data_status": "READY" if ready else "NOT_READY",
                    "implementation_status": "IMPLEMENTED",
                    "ready_instrument_count": item["instrument_count"],
                    "total_instrument_count": item["instrument_count"],
                    "earliest_at": item["earliest_at"],
                    "latest_at": item["latest_at"],
                    "bar_count": item["bar_count"],
                    "expected_bar_count": item["expected_bar_count"],
                    "missing_bar_count": item["missing_bar_count"],
                    "quality_error_count": 0,
                    "warning_count": 1 if item["missing_bar_count"] else 0,
                    "required_action": (
                        "检查演示缺口和D02交易状态"
                        if item["missing_bar_count"]
                        else (None if ready else "运行D03 Fixture或CLI导入分钟数据")
                    ),
                }
            )
        data_5 = next(item for item in result if item["timeframe"] == "MINUTE_5")
        data_15 = next(item for item in result if item["timeframe"] == "MINUTE_15")
        for key, source in (
            ("bt02_5m_ready", data_5),
            ("bt02_15m_ready", data_15),
            ("replay_intraday_ready", result[0]),
        ):
            result.append(
                {
                    **source,
                    "capability_key": key,
                    "implementation_status": "NOT_IMPLEMENTED",
                    "required_action": "代码尚未开发",
                }
            )
        return result


class IntradayQualityService:
    """Append-only structural quality verification for a bounded instrument/range."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory
        self._template = IntradaySessionTemplate()
        self._integrity = IntradayAggregationIntegrityService()

    async def run(
        self,
        *,
        instrument_id: UUID,
        source_code: str,
        timeframe: MarketTimeframe,
        start_at: datetime,
        end_at: datetime,
        correlation_id: UUID,
    ) -> MarketDataQualityRun:
        if timeframe not in INTRADAY_TIMEFRAMES or start_at >= end_at:
            raise ApplicationError("INTRADAY_TIMEFRAME_NOT_SUPPORTED", "质量检查参数无效")
        now = datetime.now(UTC)
        run = MarketDataQualityRun(
            timeframe=timeframe,
            status=MarketDataQualityRunStatus.RUNNING,
            started_at=now,
            correlation_id=correlation_id,
            universe_key=str(instrument_id),
            provider=source_code,
            metadata={
                "scope": "D03_INTRADAY",
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
            },
        )
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(source_code)
            instrument = await uow.instruments.get_by_id(instrument_id)
            if source is None or instrument is None:
                raise ApplicationError(
                    "INTRADAY_PROVIDER_NOT_AVAILABLE", "质量检查来源或标的不存在"
                )
            await uow.market_data_quality_runs.add(run)
            await uow.commit()
        async with self._uow_factory() as uow:
            bars = await uow.market_bars.get_bars(
                instrument_id=instrument_id,
                source_id=source.id,
                timeframe=timeframe,
                adjustment_type=AdjustmentType.NONE,
                start=start_at,
                end=end_at - timedelta(microseconds=1),
                limit=100_000,
            )
            one_minute = (
                bars
                if timeframe is MarketTimeframe.MINUTE_1
                else await uow.market_bars.get_bars(
                    instrument_id=instrument_id,
                    source_id=source.id,
                    timeframe=MarketTimeframe.MINUTE_1,
                    adjustment_type=AdjustmentType.NONE,
                    start=start_at,
                    end=end_at - timedelta(microseconds=1),
                    limit=100_000,
                )
            )
            statuses = await uow.instrument_trading_statuses.list(
                instrument_ids=[instrument_id],
                start=start_at.date(),
                end=end_at.date(),
                limit=1_000,
            )
            exchange = "SHSE" if instrument.exchange == "SSE" else instrument.exchange
            calendar = await uow.trading_calendar.list(
                exchange=exchange,
                start=start_at.date(),
                end=(end_at - timedelta(microseconds=1)).date(),
                limit=1_000,
            )
            factors = await uow.adjustment_factors.list(
                instrument_ids=[instrument_id],
                start=start_at.date(),
                end=(end_at - timedelta(microseconds=1)).date(),
                source=None,
                convention=FactorConvention.TUSHARE_CUMULATIVE,
                limit=1_000,
            )
        suspended = {item.session_date for item in statuses if item.status.value == "SUSPENDED"}
        trading = {
            item.session_date
            for item in statuses
            if item.status in {InstrumentTradingState.TRADING, InstrumentTradingState.RESUMED}
        }
        factor_dates = {item.trade_date for item in factors}
        by_day: dict[date, list[MarketBar]] = defaultdict(list)
        issues: list[MarketDataQualityIssue] = []
        for bar in bars:
            local_date = self._template.local(bar.bar_time).date()
            by_day[local_date].append(bar)
            if not self._template.validate_bar_start(bar.bar_time, timeframe):
                local_time = self._template.local(bar.bar_time).time().replace(tzinfo=None)
                if self._template.segment_for(bar.bar_time) is not None:
                    issue_type = "INTRADAY_TIMESTAMP_MISALIGNED"
                elif (
                    datetime.strptime("11:30", "%H:%M").time()
                    <= local_time
                    < datetime.strptime("13:00", "%H:%M").time()
                ):
                    issue_type = "INTRADAY_LUNCH_BREAK_BAR"
                else:
                    issue_type = "INTRADAY_OUTSIDE_SESSION"
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        bar.bar_time,
                        issue_type,
                        "Bar时间未对齐或位于Session外",
                    )
                )
            if min(bar.open, bar.high, bar.low, bar.close) <= 0 or (
                bar.high < max(bar.open, bar.close, bar.low)
                or bar.low > min(bar.open, bar.close, bar.high)
            ):
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        bar.bar_time,
                        "INTRADAY_OHLC_INVALID",
                        "OHLC关系不合法",
                    )
                )
            if bar.volume < 0:
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        bar.bar_time,
                        "INTRADAY_NEGATIVE_VOLUME",
                        "成交量为负数",
                    )
                )
            if bar.amount is not None and bar.amount < 0:
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        bar.bar_time,
                        "INTRADAY_AMOUNT_INVALID",
                        "成交额为负数",
                    )
                )
        expected_dates = [
            item.session_date
            for item in calendar
            if item.is_open
            and (instrument.listed_at is None or item.session_date >= instrument.listed_at)
            and (instrument.delisted_at is None or item.session_date <= instrument.delisted_at)
        ]
        open_dates = {item.session_date for item in calendar if item.is_open}
        for session_date, values in sorted(by_day.items()):
            if session_date not in open_dates:
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        min(item.bar_time for item in values),
                        "INTRADAY_OUTSIDE_SESSION",
                        "非开放交易日存在分钟Bar",
                    )
                )
            elif session_date in suspended and values:
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        min(item.bar_time for item in values),
                        "INTRADAY_UNEXPECTED_BAR_COUNT",
                        "停牌日存在分钟Bar",
                    )
                )
        for session_date in expected_dates:
            values = by_day.get(session_date, [])
            if session_date in suspended:
                continue
            expected = set(self._template.expected_starts(session_date, timeframe))
            actual = {item.bar_time for item in values}
            missing = sorted(expected - actual)
            if missing:
                state = "TRADING" if session_date in trading else "UNKNOWN"
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        missing[0],
                        "INTRADAY_MISSING_BAR",
                        f"缺少{len(missing)}根预期Bar (交易状态{state})",
                        expected=str(len(expected)),
                        observed=str(len(actual)),
                    )
                )
            if len(actual) != len(expected):
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        min(actual) if actual else None,
                        "INTRADAY_UNEXPECTED_BAR_COUNT",
                        "交易日Bar数量不符合Session模板",
                        expected=str(len(expected)),
                        observed=str(len(actual)),
                    )
                )
            if values and session_date not in factor_dates:
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        min(actual),
                        "INTRADAY_ADJUSTMENT_FACTOR_MISSING",
                        "该交易日缺少QFQ日级复权因子, RAW仍可使用",
                    )
                )
        if timeframe is not MarketTimeframe.MINUTE_1:
            for mismatch in self._integrity.compare(one_minute, bars, timeframe):
                issues.append(
                    self._issue(
                        run.id,
                        instrument_id,
                        timeframe,
                        mismatch.bar_time,
                        "INTRADAY_AGGREGATION_MISMATCH",
                        f"聚合复算字段不一致: {','.join(mismatch.fields)}",
                    )
                )
        warning_count = len(issues)
        metadata: dict[str, object] = {
            "scope": "D03_INTRADAY",
            "expected_session_model": "CN_CONTINUOUS_V1",
            "aggregation_version": AGGREGATION_VERSION,
            "qfq_factor_dates": len(factor_dates),
            "latest_bar_at": (max(item.bar_time for item in bars).isoformat() if bars else None),
        }
        async with self._uow_factory() as uow:
            await uow.market_data_quality_issues.add_many(issues)
            await uow.market_data_quality_runs.complete(
                run.id,
                status=MarketDataQualityRunStatus.COMPLETED,
                completed_at=datetime.now(UTC),
                instruments_checked=1,
                bars_checked=len(bars),
                error_count=0,
                warning_count=warning_count,
                info_count=0,
                metadata=metadata,
            )
            await uow.commit()
        run.status = MarketDataQualityRunStatus.COMPLETED
        run.instruments_checked = 1
        run.bars_checked = len(bars)
        run.issues_found = warning_count
        run.warning_count = warning_count
        run.metadata = metadata
        run.completed_at = datetime.now(UTC)
        return run

    @staticmethod
    def _issue(
        run_id: UUID,
        instrument_id: UUID,
        timeframe: MarketTimeframe,
        at: datetime | None,
        issue_type: str,
        message: str,
        *,
        expected: str | None = None,
        observed: str | None = None,
    ) -> MarketDataQualityIssue:
        return MarketDataQualityIssue(
            quality_run_id=run_id,
            instrument_id=instrument_id,
            issue_type=issue_type,
            severity=MarketDataIssueSeverity.WARNING,
            timeframe=timeframe,
            message=message,
            first_affected_at=at,
            last_affected_at=at,
            expected_value=expected,
            observed_value=observed,
            required_action="检查源文件与D02交易状态后重新导入",
            metadata={"scope": "D03_INTRADAY"},
        )


async def ensure_fixture_catalog(
    uow_factory: UnitOfWorkFactory,
) -> tuple[UUID, tuple[Instrument, ...]]:
    catalog = InstrumentCatalogService(uow_factory)
    source = await catalog.ensure_source(
        source_code="D03_FIXTURE",
        name="D03 deterministic intraday fixture",
        status=MarketDataSourceStatus.ACTIVE,
        priority=5,
        supports_realtime=False,
        supported_timeframes=INTRADAY_TIMEFRAMES,
        provider_tier=MarketProviderTier.DEMO,
    )
    external = [
        ExternalInstrument(
            symbol="600000",
            exchange="SSE",
            market="CN",
            name="D03 Fixture SSE",
            asset_type="STOCK",
            currency="CNY",
            lot_size="100",
            price_tick="0.01",
            timezone="Asia/Shanghai",
            metadata={"fixture": "D03_FIXTURE"},
        ),
        ExternalInstrument(
            symbol="000001",
            exchange="SZSE",
            market="CN",
            name="D03 Fixture SZSE",
            asset_type="STOCK",
            currency="CNY",
            lot_size="100",
            price_tick="0.01",
            timezone="Asia/Shanghai",
            metadata={"fixture": "D03_FIXTURE"},
        ),
    ]
    await catalog.import_external(source.source_code, external, uuid4())
    async with uow_factory() as uow:
        values = tuple(
            item
            for item in (
                await uow.instruments.get_by_business_key("SSE", "600000"),
                await uow.instruments.get_by_business_key("SZSE", "000001"),
            )
            if item is not None
        )
        now = datetime.now(UTC)
        calendar_dates = (
            date(2026, 7, 6),
            date(2026, 7, 7),
            date(2026, 7, 8),
            date(2026, 7, 9),
            date(2026, 7, 10),
            date(2026, 7, 13),
            date(2026, 7, 14),
        )
        for exchange in ("SHSE", "SZSE"):
            await uow.trading_calendar.upsert_many(
                [
                    TradingCalendarSession(
                        exchange=exchange,
                        session_date=value,
                        is_open=True,
                        session_type=CalendarSessionType.NORMAL,
                        source="D03_FIXTURE",
                        fetched_at=now,
                    )
                    for value in calendar_dates
                ]
            )
        await uow.instrument_trading_statuses.upsert_many(
            [
                InstrumentTradingStatus(
                    instrument_id=instrument.id,
                    session_date=session_date,
                    status=(
                        InstrumentTradingState.SUSPENDED
                        if session_date == date(2026, 7, 14)
                        or (session_date == date(2026, 7, 13) and instrument.symbol == "000001")
                        else InstrumentTradingState.TRADING
                    ),
                    source="D03_FIXTURE",
                    fetched_at=now,
                    reason=(
                        "D03 suspended-day fixture" if session_date == date(2026, 7, 14) else None
                    ),
                )
                for instrument in values
                for session_date in calendar_dates
            ]
        )
        await uow.commit()
    return source.id, values


def fixture_rows() -> tuple[IntradayExternalBar, ...]:
    template = IntradaySessionTemplate()
    dates = (
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
        date(2026, 7, 9),
        date(2026, 7, 10),
    )
    rows: list[IntradayExternalBar] = []
    for symbol_index, (symbol, exchange) in enumerate((("600000", "SSE"), ("000001", "SZSE"))):
        for date_index, session_date in enumerate(dates):
            for minute_index, timestamp in enumerate(
                template.expected_starts(session_date, MarketTimeframe.MINUTE_1)
            ):
                price = (
                    Decimal("10")
                    + Decimal(symbol_index)
                    + Decimal(date_index) / 10
                    + Decimal(minute_index) / 10000
                )
                rows.append(
                    IntradayExternalBar(
                        symbol=symbol,
                        exchange=exchange,
                        timestamp=timestamp,
                        timeframe=MarketTimeframe.MINUTE_1,
                        open=str(price),
                        high=str(price + Decimal("0.02")),
                        low=str(price - Decimal("0.01")),
                        close=str(price + Decimal("0.01")),
                        volume=str(100 + minute_index),
                        amount=str((price + Decimal("0.01")) * (100 + minute_index)),
                        source="D03_FIXTURE",
                        metadata={"fixture": "D03_FIXTURE", "timestamp_semantics": "BAR_START"},
                    )
                )
        if symbol_index == 0:
            incomplete_date = date(2026, 7, 13)
            starts = template.expected_starts(incomplete_date, MarketTimeframe.MINUTE_1)
            for minute_index, timestamp in enumerate(starts):
                if timestamp == starts[30]:
                    continue
                price = Decimal("12") + Decimal(minute_index) / 10000
                rows.append(
                    IntradayExternalBar(
                        symbol=symbol,
                        exchange=exchange,
                        timestamp=timestamp,
                        timeframe=MarketTimeframe.MINUTE_1,
                        open=str(price),
                        high=str(price + Decimal("0.02")),
                        low=str(price - Decimal("0.01")),
                        close=str(price + Decimal("0.01")),
                        volume=str(100 + minute_index),
                        amount=str((price + Decimal("0.01")) * (100 + minute_index)),
                        source="D03_FIXTURE",
                        metadata={
                            "fixture": "D03_FIXTURE",
                            "case": "INCOMPLETE_SESSION",
                            "timestamp_semantics": "BAR_START",
                        },
                    )
                )
    return tuple(rows)
