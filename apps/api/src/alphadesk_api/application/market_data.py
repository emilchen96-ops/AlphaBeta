"""Market-data ingestion, validation, idempotency, and query services."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from alphadesk_api.application.common import (
    ApplicationError,
    UnitOfWorkFactory,
    append_event_and_audit,
)
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketSyncStatus,
    MarketTimeframe,
    SyncTriggerType,
)
from alphadesk_domain.market import (
    MarketBar,
    MarketDataFreshness,
    MarketDataSource,
    MarketSyncRun,
)
from alphadesk_domain.market_adapters import (
    ExternalMarketBar,
    MarketDataAdapter,
    MarketDataAdapterError,
)
from alphadesk_domain.unit_of_work import UnitOfWork


class MarketDataIngestionService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        batch_size: int = 500,
        future_tolerance_seconds: int = 300,
    ) -> None:
        self._uow_factory = uow_factory
        self._batch_size = batch_size
        self._future_tolerance = timedelta(seconds=future_tolerance_seconds)

    async def sync_bars(
        self,
        *,
        adapter: MarketDataAdapter,
        symbols: list[str],
        timeframe: MarketTimeframe,
        adjustment: AdjustmentType,
        start: datetime,
        end: datetime,
        trigger_type: SyncTriggerType,
        correlation_id: UUID,
    ) -> MarketSyncRun:
        if start.tzinfo is None or end.tzinfo is None:
            raise ApplicationError("MARKET_DATA_INVALID_RANGE", "时间范围必须包含时区")
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        if start > end:
            raise ApplicationError("MARKET_DATA_INVALID_RANGE", "开始时间不能晚于结束时间")
        source = await self._require_source(adapter.source_code)
        if source.status is not MarketDataSourceStatus.ACTIVE:
            raise ApplicationError("MARKET_SOURCE_DISABLED", "行情源当前不可用")
        if timeframe not in source.supported_timeframes:
            raise ApplicationError("MARKET_DATA_VALIDATION_FAILED", "行情源不支持该周期")

        run = MarketSyncRun(
            source_id=source.id,
            trigger_type=trigger_type,
            status=MarketSyncStatus.RUNNING,
            timeframe=timeframe,
            adjustment_type=adjustment,
            requested_symbols=tuple(symbols),
            requested_start=start,
            requested_end=end,
            started_at=datetime.now(UTC),
            correlation_id=correlation_id,
        )
        async with self._uow_factory() as uow:
            await uow.market_sync_runs.add(run)
            await append_event_and_audit(
                uow,
                event_type="MARKET_SYNC_STARTED",
                entity_type="MarketSyncRun",
                entity_id=run.id,
                correlation_id=correlation_id,
                payload={
                    "source_code": source.source_code,
                    "timeframe": timeframe.value,
                    "symbol_count": len(symbols),
                },
            )
            await uow.commit()

        total_received = 0
        rejected = 0
        errors: list[str] = []
        valid: list[MarketBar] = []
        try:
            async with self._uow_factory() as uow:
                mappings = await uow.instrument_mappings.list_for_source_symbols(source.id, symbols)
            mapping_by_symbol = {mapping.external_symbol: mapping for mapping in mappings}
            previous_times: dict[str, datetime] = {}
            async for external in adapter.fetch_bars(symbols, timeframe, start, end, adjustment):
                total_received += 1
                mapping = mapping_by_symbol.get(external.symbol)
                if mapping is None:
                    rejected += 1
                    errors.append(f"mapping_missing:{external.symbol}")
                    continue
                try:
                    bar = normalize_external_bar(
                        external,
                        instrument_id=mapping.instrument_id,
                        source_id=source.id,
                        adjustment=adjustment,
                        future_tolerance=self._future_tolerance,
                    )
                    previous = previous_times.get(external.symbol)
                    if previous is not None and bar.bar_time < previous:
                        raise ValueError("bars are not ordered")
                    previous_times[external.symbol] = bar.bar_time
                    valid.append(bar)
                except (ArithmeticError, TypeError, ValueError) as exc:
                    rejected += 1
                    errors.append(f"invalid_bar:{external.symbol}:{type(exc).__name__}")
        except MarketDataAdapterError as exc:
            return await self._mark_failed(
                run,
                total_received=total_received,
                total_rejected=rejected,
                reason=type(exc).__name__,
            )

        inserted = 0
        updated = 0
        try:
            async with self._uow_factory() as uow:
                for offset in range(0, len(valid), self._batch_size):
                    chunk = valid[offset : offset + self._batch_size]
                    result = await uow.market_bars.upsert_many(chunk)
                    inserted += result.inserted
                    updated += result.updated
                completed_at = datetime.now(UTC)
                status = (
                    MarketSyncStatus.PARTIALLY_SUCCEEDED if rejected else MarketSyncStatus.SUCCEEDED
                )
                summary = ";".join(errors[:10]) or None
                await uow.market_sync_runs.update_status(
                    run.id,
                    status=status,
                    completed_at=completed_at,
                    total_received=total_received,
                    total_inserted=inserted,
                    total_updated=updated,
                    total_rejected=rejected,
                    error_summary=summary,
                )
                await append_event_and_audit(
                    uow,
                    event_type="MARKET_BARS_INGESTED",
                    entity_type="MarketSyncRun",
                    entity_id=run.id,
                    correlation_id=correlation_id,
                    payload={
                        "received": total_received,
                        "inserted": inserted,
                        "updated": updated,
                        "rejected": rejected,
                    },
                )
                await append_event_and_audit(
                    uow,
                    event_type=(
                        "MARKET_SYNC_PARTIALLY_SUCCEEDED" if rejected else "MARKET_SYNC_SUCCEEDED"
                    ),
                    entity_type="MarketSyncRun",
                    entity_id=run.id,
                    correlation_id=correlation_id,
                    payload={"status": status.value},
                )
                await uow.commit()
        except Exception as exc:
            if exc.__class__.__module__.startswith(("sqlalchemy", "asyncpg")):
                return await self._mark_failed(
                    run,
                    total_received=total_received,
                    total_rejected=rejected,
                    reason="PERSISTENCE_ERROR",
                )
            raise
        return MarketSyncRun(
            source_id=run.source_id,
            trigger_type=run.trigger_type,
            status=status,
            timeframe=run.timeframe,
            adjustment_type=run.adjustment_type,
            requested_symbols=run.requested_symbols,
            requested_start=run.requested_start,
            requested_end=run.requested_end,
            started_at=run.started_at,
            completed_at=completed_at,
            correlation_id=run.correlation_id,
            id=run.id,
            total_received=total_received,
            total_inserted=inserted,
            total_updated=updated,
            total_rejected=rejected,
            error_summary=summary,
        )

    async def _require_source(self, source_code: str) -> MarketDataSource:
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(source_code)
        if source is None:
            raise ApplicationError("MARKET_SOURCE_NOT_FOUND", "行情源不存在")
        return source

    async def _mark_failed(
        self,
        run: MarketSyncRun,
        *,
        total_received: int,
        total_rejected: int,
        reason: str,
    ) -> MarketSyncRun:
        completed_at = datetime.now(UTC)
        async with self._uow_factory() as uow:
            await uow.market_sync_runs.update_status(
                run.id,
                status=MarketSyncStatus.FAILED,
                completed_at=completed_at,
                total_received=total_received,
                total_inserted=0,
                total_updated=0,
                total_rejected=total_rejected,
                error_summary=reason[:1000],
            )
            await append_event_and_audit(
                uow,
                event_type="MARKET_SYNC_FAILED",
                entity_type="MarketSyncRun",
                entity_id=run.id,
                correlation_id=run.correlation_id,
                payload={"reason_code": reason[:100]},
                outcome="FAILED",
            )
            await uow.commit()
        return MarketSyncRun(
            source_id=run.source_id,
            trigger_type=run.trigger_type,
            status=MarketSyncStatus.FAILED,
            timeframe=run.timeframe,
            adjustment_type=run.adjustment_type,
            requested_symbols=run.requested_symbols,
            requested_start=run.requested_start,
            requested_end=run.requested_end,
            started_at=run.started_at,
            completed_at=completed_at,
            correlation_id=run.correlation_id,
            id=run.id,
            total_received=total_received,
            total_rejected=total_rejected,
            error_summary=reason[:1000],
        )


def normalize_external_bar(
    external: ExternalMarketBar,
    *,
    instrument_id: UUID,
    source_id: UUID,
    adjustment: AdjustmentType,
    future_tolerance: timedelta,
) -> MarketBar:
    """Convert string-valued provider data without passing through binary floats."""

    now = datetime.now(UTC)
    if external.timeframe not in (MarketTimeframe.DAY_1, MarketTimeframe.MINUTE_1):
        raise ValueError("unsupported normalized timeframe")
    if external.bar_time.tzinfo is None:
        raise ValueError("bar_time must be timezone-aware")
    bar_time = external.bar_time.astimezone(UTC)
    if bar_time > now + future_tolerance:
        raise ValueError("bar_time is too far in the future")
    return MarketBar(
        instrument_id=instrument_id,
        source_id=source_id,
        timeframe=external.timeframe,
        adjustment_type=adjustment,
        bar_time=bar_time,
        open=Decimal(external.open),
        high=Decimal(external.high),
        low=Decimal(external.low),
        close=Decimal(external.close),
        volume=Decimal(external.volume),
        amount=None if external.amount is None else Decimal(external.amount),
        vwap=None if external.vwap is None else Decimal(external.vwap),
        open_interest=None if external.open_interest is None else Decimal(external.open_interest),
        received_at=now,
        source_updated_at=external.source_updated_at,
        quality_status=MarketDataQualityStatus.NORMAL,
        quality_flags={
            "source_classification": "EXTERNAL",
            **(external.metadata or {}),
        },
    )


class MarketDataQueryService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        minute_stale_seconds: int = 300,
        authoritative_source_code: str | None = None,
        allow_non_authoritative_sources: bool = True,
    ) -> None:
        self._uow_factory = uow_factory
        self._minute_stale = timedelta(seconds=minute_stale_seconds)
        self._authoritative_source_code = (
            authoritative_source_code.strip().upper() if authoritative_source_code else None
        )
        self._allow_non_authoritative_sources = allow_non_authoritative_sources

    async def bars(
        self,
        *,
        instrument_id: UUID,
        timeframe: MarketTimeframe,
        adjustment: AdjustmentType,
        source_code: str | None,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> tuple[MarketDataSource, list[MarketBar], MarketDataFreshness]:
        async with self._uow_factory() as uow:
            if await uow.instruments.get_by_id(instrument_id) is None:
                raise ApplicationError("INSTRUMENT_NOT_FOUND", "金融标的不存在")
            source = await self._resolve_source(uow, instrument_id, source_code)
            bars = await uow.market_bars.get_bars(
                instrument_id=instrument_id,
                source_id=source.id,
                timeframe=timeframe,
                adjustment_type=adjustment,
                start=start,
                end=end,
                limit=limit,
            )
        latest = bars[-1] if bars else None
        return source, bars, self.freshness(source, timeframe, latest)

    async def latest(
        self,
        *,
        instrument_ids: list[UUID],
        timeframe: MarketTimeframe,
        adjustment: AdjustmentType,
        source_code: str | None,
    ) -> tuple[MarketDataSource, list[tuple[MarketBar, MarketDataFreshness]]]:
        async with self._uow_factory() as uow:
            requested_code = (
                source_code.strip().upper() if source_code else self._authoritative_source_code
            )
            self._validate_requested_source(requested_code)
            sources = await uow.market_data_sources.list_active()
            if requested_code:
                source = await uow.market_data_sources.get_by_code(requested_code)
                if source is None:
                    raise ApplicationError(
                        "MARKET_SOURCE_NOT_FOUND",
                        "MiniQMT 行情源尚未初始化。请启动 Windows 行情代理",
                    )
            elif sources:
                source = sources[0]
            else:
                raise ApplicationError("MARKET_SOURCE_NOT_FOUND", "没有可用行情源")
            if source.status is not MarketDataSourceStatus.ACTIVE:
                raise ApplicationError("MARKET_SOURCE_DISABLED", "MiniQMT 行情源当前不可用")
            bars = await uow.market_bars.get_latest_for_instruments(
                instrument_ids=instrument_ids,
                source_id=source.id,
                timeframe=timeframe,
                adjustment_type=adjustment,
            )
        return source, [(bar, self.freshness(source, timeframe, bar)) for bar in bars]

    async def sources(self) -> list[MarketDataSource]:
        async with self._uow_factory() as uow:
            values = await uow.market_data_sources.list_all()
        if self._authoritative_source_code and not self._allow_non_authoritative_sources:
            return [
                value for value in values if value.source_code == self._authoritative_source_code
            ]
        return values

    async def sync_runs(self, limit: int) -> list[MarketSyncRun]:
        async with self._uow_factory() as uow:
            return await uow.market_sync_runs.list_recent(limit)

    async def sync_run(self, run_id: UUID) -> MarketSyncRun:
        async with self._uow_factory() as uow:
            run = await uow.market_sync_runs.get_by_id(run_id)
        if run is None:
            raise ApplicationError("MARKET_SYNC_RUN_NOT_FOUND", "行情同步记录不存在")
        return run

    async def _resolve_source(
        self, uow: UnitOfWork, instrument_id: UUID, source_code: str | None
    ) -> MarketDataSource:
        requested_code = (
            source_code.strip().upper() if source_code else self._authoritative_source_code
        )
        self._validate_requested_source(requested_code)
        if requested_code:
            source = await uow.market_data_sources.get_by_code(requested_code)
            if source is None:
                raise ApplicationError(
                    "MARKET_SOURCE_NOT_FOUND",
                    "MiniQMT 行情源尚未初始化。请启动 Windows 行情代理",
                )
            if source.status is not MarketDataSourceStatus.ACTIVE:
                raise ApplicationError("MARKET_SOURCE_DISABLED", "MiniQMT 行情源当前不可用")
            if requested_code == self._authoritative_source_code:
                # L2.5-A accepted history by canonical Instrument id. Some
                # persisted rows therefore predate a MiniQMT mapping; existing
                # authoritative facts remain readable while the catalog sync
                # repairs mappings in the background.
                return source
            mapping = await uow.instrument_mappings.get_by_source_and_instrument(
                source.id, instrument_id
            )
            if mapping is None:
                raise ApplicationError("MARKET_DATA_NOT_FOUND", "该行情源没有标的映射")
            return source
        mappings = await uow.instrument_mappings.list_for_instrument(instrument_id)
        mapped_sources = {mapping.source_id for mapping in mappings}
        for source in await uow.market_data_sources.list_active():
            if source.id in mapped_sources:
                return source
        raise ApplicationError("MARKET_DATA_NOT_FOUND", "该标的没有可用行情源")

    def _validate_requested_source(self, source_code: str | None) -> None:
        if (
            source_code
            and self._authoritative_source_code
            and source_code != self._authoritative_source_code
            and not self._allow_non_authoritative_sources
        ):
            raise ApplicationError(
                "MARKET_SOURCE_NOT_AUTHORIZED",
                "正式行情只允许使用 MiniQMT 数据源",
            )

    def freshness(
        self,
        source: MarketDataSource,
        timeframe: MarketTimeframe,
        latest: MarketBar | None,
    ) -> MarketDataFreshness:
        now = datetime.now(UTC)
        if latest is None or source.status is MarketDataSourceStatus.DEGRADED:
            status = MarketDataQualityStatus.UNKNOWN
        elif latest.quality_status is not MarketDataQualityStatus.NORMAL:
            status = latest.quality_status
        elif timeframe is MarketTimeframe.MINUTE_1 and self._active_cn_window(now):
            status = (
                MarketDataQualityStatus.DELAYED
                if now - latest.bar_time > self._minute_stale
                else MarketDataQualityStatus.NORMAL
            )
        else:
            status = MarketDataQualityStatus.NORMAL
        return MarketDataFreshness(
            source_code=source.source_code,
            status=status,
            latest_bar_time=None if latest is None else latest.bar_time,
            latest_received_at=None if latest is None else latest.received_at,
            calculated_at=now,
        )

    @staticmethod
    def _active_cn_window(now: datetime) -> bool:
        current = now.time()
        return now.weekday() < 5 and time(1, 30) <= current <= time(7, 0)
