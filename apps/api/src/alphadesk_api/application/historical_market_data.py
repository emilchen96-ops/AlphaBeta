"""D01 deterministic A-share universe and daily historical backfill services."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import anyio

from alphadesk_api.application.catalog import InstrumentCatalogService
from alphadesk_api.application.common import (
    ApplicationError,
    UnitOfWorkFactory,
    append_event_and_audit,
)
from alphadesk_api.application.market_data import normalize_external_bar
from alphadesk_domain.entities import Instrument, Watchlist, WatchlistItem
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketSyncStatus,
    MarketTimeframe,
    SyncTriggerType,
)
from alphadesk_domain.market import InstrumentMapping, MarketSyncRun
from alphadesk_domain.market_adapters import (
    ExternalMarketBar,
    MarketDataAdapter,
    MarketDataAdapterError,
)

RESEARCH_UNIVERSE_NAME = "D01 Research Universe"
MAX_RESEARCH_INSTRUMENTS = 500


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentSyncResult:
    source_code: str
    provider_count: int
    selected_count: int
    active_count: int
    inactive_count: int
    instrument_count: int
    mapping_count: int
    dry_run: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchUniverseResult:
    name: str
    instrument_ids: tuple[UUID, ...]
    symbols: tuple[str, ...]
    created: bool
    dry_run: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalBackfillResult:
    run: MarketSyncRun | None
    requested: int
    succeeded: int
    failed: int
    skipped: int
    unprocessed: int
    unchanged: int
    retry_count: int
    failures: tuple[dict[str, str], ...]
    dry_run: bool


class InstrumentUniverseSyncService:
    """Synchronize provider instruments and maintain a bounded research watchlist."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory
        self._catalog = InstrumentCatalogService(uow_factory)

    async def sync_instruments(
        self,
        *,
        adapter: MarketDataAdapter,
        correlation_id: UUID,
        limit: int | None = None,
        symbols: set[str] | None = None,
        dry_run: bool = False,
    ) -> InstrumentSyncResult:
        if limit is not None and not 1 <= limit <= 10_000:
            raise ApplicationError(
                "D01_INSTRUMENT_LIMIT_INVALID", "标的同步上限必须在 1 到 10000 之间"
            )
        external = await adapter.list_instruments(market="CN_A")
        provider_count = len(external)
        normalized_symbols = (
            None if symbols is None else {_normalize_symbol(item) for item in symbols}
        )
        selected = [
            item
            for item in external
            if item.market.upper() == "CN_A"
            and item.asset_type.upper() == "STOCK"
            and (normalized_symbols is None or item.symbol.upper() in normalized_symbols)
        ]
        selected.sort(key=lambda item: (item.exchange.upper(), item.symbol.upper()))
        if limit is not None:
            selected = selected[:limit]
        if dry_run:
            counts = (0, 0)
        else:
            await self._ensure_source(adapter.source_code)
            counts = await self._catalog.import_external(
                adapter.source_code, selected, correlation_id
            )
        return InstrumentSyncResult(
            source_code=adapter.source_code,
            provider_count=provider_count,
            selected_count=len(selected),
            active_count=sum(item.is_active for item in selected),
            inactive_count=sum(not item.is_active for item in selected),
            instrument_count=counts[0],
            mapping_count=counts[1],
            dry_run=dry_run,
        )

    async def create_research_universe(
        self,
        *,
        correlation_id: UUID,
        limit: int = 300,
        symbols: set[str] | None = None,
        dry_run: bool = False,
    ) -> ResearchUniverseResult:
        if not 1 <= limit <= MAX_RESEARCH_INSTRUMENTS:
            raise ApplicationError(
                "D01_UNIVERSE_LIMIT_INVALID",
                f"研究股票池规模必须在 1 到 {MAX_RESEARCH_INSTRUMENTS} 之间",
            )
        eligible = await self._active_a_shares()
        if symbols is not None:
            requested = {_normalize_symbol(item) for item in symbols}
            eligible = [item for item in eligible if item.symbol.upper() in requested]
            found = {item.symbol.upper() for item in eligible}
            missing = sorted(requested - found)
            if missing:
                raise ApplicationError(
                    "D01_UNIVERSE_SYMBOL_NOT_FOUND",
                    "研究股票池包含不存在或非活跃的 A 股代码",
                    {"symbols": missing[:20]},
                )
        selected = eligible[:limit]
        if not selected:
            raise ApplicationError("D01_UNIVERSE_EMPTY", "没有可加入研究股票池的活跃 A 股")
        instrument_ids = tuple(item.id for item in selected)
        if dry_run:
            return ResearchUniverseResult(
                name=RESEARCH_UNIVERSE_NAME,
                instrument_ids=instrument_ids,
                symbols=tuple(item.symbol for item in selected),
                created=False,
                dry_run=True,
            )

        async with self._uow_factory() as uow:
            watchlist = await uow.watchlists.get_by_name(RESEARCH_UNIVERSE_NAME)
            created = watchlist is None
            if watchlist is None:
                watchlist = Watchlist(
                    name=RESEARCH_UNIVERSE_NAME,
                    description=(
                        "D01 managed daily-bar research universe; safe to recreate idempotently."
                    ),
                )
                await uow.watchlists.add(watchlist)
            current = await uow.watchlists.list_items(watchlist.id)
            selected_ids = set(instrument_ids)
            for current_item in current:
                if current_item.instrument_id not in selected_ids:
                    await uow.watchlists.remove_item(current_item.id)
            remaining = {
                current_item.instrument_id: current_item
                for current_item in current
                if current_item.instrument_id in selected_ids
            }
            ordered_items: list[WatchlistItem] = []
            for position, instrument in enumerate(selected):
                selected_item = remaining.get(instrument.id)
                if selected_item is None:
                    selected_item = WatchlistItem(
                        watchlist_id=watchlist.id,
                        instrument_id=instrument.id,
                        sort_order=position,
                        note="D01_RESEARCH_UNIVERSE",
                    )
                    await uow.watchlists.add_item(selected_item)
                ordered_items.append(selected_item)
            await uow.watchlists.reorder(watchlist.id, [item.id for item in ordered_items])
            await append_event_and_audit(
                uow,
                event_type="RESEARCH_UNIVERSE_SYNCHRONIZED",
                entity_type="Watchlist",
                entity_id=watchlist.id,
                correlation_id=correlation_id,
                payload={"instrument_count": len(selected), "managed_by": "D01"},
                source="ALPHADESK_D01",
            )
            await uow.commit()
        return ResearchUniverseResult(
            name=RESEARCH_UNIVERSE_NAME,
            instrument_ids=instrument_ids,
            symbols=tuple(item.symbol for item in selected),
            created=created,
            dry_run=False,
        )

    async def resolve_universe(
        self,
        *,
        universe: str,
        limit: int,
        instrument_ids: list[UUID] | None = None,
        symbols: set[str] | None = None,
    ) -> list[Instrument]:
        if not 1 <= limit <= MAX_RESEARCH_INSTRUMENTS:
            raise ApplicationError(
                "D01_UNIVERSE_LIMIT_INVALID",
                f"单次补数标的上限必须在 1 到 {MAX_RESEARCH_INSTRUMENTS} 之间",
            )
        normalized = universe.strip().lower()
        if normalized == "research":
            async with self._uow_factory() as uow:
                watchlist = await uow.watchlists.get_by_name(RESEARCH_UNIVERSE_NAME)
                if watchlist is None:
                    raise ApplicationError("D01_UNIVERSE_NOT_FOUND", "研究股票池尚未创建")
                items = (await uow.watchlists.list_items(watchlist.id))[:limit]
                values = await uow.instruments.get_many([item.instrument_id for item in items])
                by_id = {item.id: item for item in values}
                return [by_id[item.instrument_id] for item in items if item.instrument_id in by_id]
        if normalized == "all_active_a_share":
            return (await self._active_a_shares())[:limit]
        if normalized != "manual":
            raise ApplicationError(
                "D01_UNIVERSE_INVALID", "universe 仅支持 research、manual 或 all_active_a_share"
            )
        selected: dict[UUID, Instrument] = {}
        async with self._uow_factory() as uow:
            if instrument_ids:
                for item in await uow.instruments.get_many(instrument_ids):
                    selected[item.id] = item
        if symbols:
            requested = {_normalize_symbol(item) for item in symbols}
            for item in await self._active_a_shares():
                if item.symbol.upper() in requested:
                    selected[item.id] = item
        values = sorted(selected.values(), key=lambda item: (item.exchange, item.symbol))[:limit]
        if not values:
            raise ApplicationError("D01_UNIVERSE_EMPTY", "manual 股票池没有有效标的")
        return values

    async def _active_a_shares(self) -> list[Instrument]:
        async with self._uow_factory() as uow:
            values, _ = await uow.instruments.search(
                keyword=None,
                exchange=None,
                market="CN_A",
                asset_type="STOCK",
                is_active=True,
                offset=0,
                limit=10_000,
            )
        return sorted(values, key=lambda item: (item.exchange, item.symbol))

    async def _ensure_source(self, source_code: str) -> None:
        if source_code.upper() != "BAOSTOCK":
            raise ApplicationError(
                "D01_PROVIDER_UNSUPPORTED", "D01-A 仅支持 BaoStock Instrument 同步"
            )
        await self._catalog.ensure_source(
            source_code="BAOSTOCK",
            name="BaoStock free historical data",
            status=MarketDataSourceStatus.ACTIVE,
            priority=30,
            supports_realtime=False,
            supported_timeframes=(MarketTimeframe.DAY_1,),
            provider_tier=MarketProviderTier.FREE_BEST_EFFORT,
        )


class HistoricalMarketDataBackfillService:
    """Serial, retry-bounded daily backfill with one persistence transaction per instrument."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        future_tolerance_seconds: int = 300,
    ) -> None:
        self._uow_factory = uow_factory
        self._future_tolerance = timedelta(seconds=future_tolerance_seconds)

    async def backfill(
        self,
        *,
        adapter: MarketDataAdapter,
        instruments: list[Instrument],
        universe: str,
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        batch_size: int,
        continue_on_error: bool,
        correlation_id: UUID,
        max_retries: int = 2,
        request_interval_seconds: float = 0,
        adjustment: AdjustmentType = AdjustmentType.NONE,
        dry_run: bool = False,
        progress: Callable[[int, int, str, str], None] | None = None,
    ) -> HistoricalBackfillResult:
        start, end = self._validate(
            instruments=instruments,
            timeframe=timeframe,
            start=start,
            end=end,
            batch_size=batch_size,
            max_retries=max_retries,
            request_interval_seconds=request_interval_seconds,
        )
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(adapter.source_code)
            if source is None:
                raise ApplicationError(
                    "MARKET_SOURCE_NOT_FOUND", "行情源不存在; 请先同步 Instrument"
                )
            if source.status is not MarketDataSourceStatus.ACTIVE:
                raise ApplicationError("MARKET_SOURCE_DISABLED", "行情源当前不可用")
            mappings: dict[UUID, InstrumentMapping] = {}
            for instrument in instruments:
                mapping = await uow.instrument_mappings.get_by_source_and_instrument(
                    source.id, instrument.id
                )
                if mapping is not None:
                    mappings[instrument.id] = mapping
        if dry_run:
            missing = len(instruments) - len(mappings)
            return HistoricalBackfillResult(
                run=None,
                requested=len(instruments),
                succeeded=0,
                failed=missing,
                skipped=0,
                unprocessed=len(instruments) - missing,
                unchanged=0,
                retry_count=0,
                failures=tuple(
                    {
                        "instrument_id": str(item.id),
                        "symbol": item.symbol,
                        "code": "D01_MAPPING_MISSING",
                    }
                    for item in instruments
                    if item.id not in mappings
                ),
                dry_run=True,
            )

        managed_adapter = cast(Any, adapter)
        open_method = getattr(managed_adapter, "open", None)
        close_method = getattr(managed_adapter, "close", None)
        if callable(open_method):
            await open_method()

        run = MarketSyncRun(
            source_id=source.id,
            trigger_type=SyncTriggerType.CLI,
            status=MarketSyncStatus.RUNNING,
            timeframe=timeframe,
            adjustment_type=adjustment,
            requested_symbols=tuple(item.symbol for item in instruments),
            requested_start=start,
            requested_end=end,
            started_at=datetime.now(UTC),
            correlation_id=correlation_id,
            metadata={
                "operation": "HISTORICAL_BACKFILL",
                "universe": universe,
                "requested_instrument_count": len(instruments),
                "batch_size": batch_size,
                "continue_on_error": continue_on_error,
                "max_retries": max_retries,
            },
        )
        async with self._uow_factory() as uow:
            await uow.market_sync_runs.add(run)
            await append_event_and_audit(
                uow,
                event_type="HISTORICAL_BACKFILL_STARTED",
                entity_type="MarketSyncRun",
                entity_id=run.id,
                correlation_id=correlation_id,
                payload={"instrument_count": len(instruments), "universe": universe},
                source="ALPHADESK_D01",
            )
            await uow.commit()

        received = inserted = updated = rejected = unchanged = 0
        succeeded = failed = skipped = retry_count = 0
        failures: list[dict[str, str]] = []
        processed = 0
        for index, instrument in enumerate(instruments, start=1):
            mapping = mappings.get(instrument.id)
            if mapping is None:
                failed += 1
                failures.append(self._failure(instrument, "D01_MAPPING_MISSING"))
                processed += 1
                if progress is not None:
                    progress(index, len(instruments), instrument.symbol, "FAILED_MAPPING")
                if not continue_on_error:
                    break
                continue
            async with self._uow_factory() as uow:
                latest = await uow.market_bars.get_latest_bar(
                    instrument_id=instrument.id,
                    source_id=source.id,
                    timeframe=timeframe,
                    adjustment_type=adjustment,
                )
                earliest_in_range = await uow.market_bars.get_bars(
                    instrument_id=instrument.id,
                    source_id=source.id,
                    timeframe=timeframe,
                    adjustment_type=adjustment,
                    start=start,
                    end=end,
                    limit=1,
                )
            # A requested boundary may fall in a holiday closure or a long suspension.
            # D01-D will replace this conservative edge check with a full calendar audit.
            coverage_tolerance = timedelta(days=14)
            if (
                latest is not None
                and earliest_in_range
                and earliest_in_range[0].bar_time <= start + coverage_tolerance
                and latest.bar_time >= end - coverage_tolerance
            ):
                skipped += 1
                processed += 1
                if progress is not None:
                    progress(index, len(instruments), instrument.symbol, "SKIPPED_COVERED")
                continue
            if processed and request_interval_seconds:
                await anyio.sleep(request_interval_seconds)
            try:
                external, retries = await self._fetch_with_retry(
                    adapter=adapter,
                    symbol=mapping.external_symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                    adjustment=adjustment,
                    max_retries=max_retries,
                )
                retry_count += retries
            except MarketDataAdapterError:
                failed += 1
                failures.append(self._failure(instrument, "D01_PROVIDER_FETCH_FAILED"))
                processed += 1
                if progress is not None:
                    progress(index, len(instruments), instrument.symbol, "FAILED_PROVIDER")
                if not continue_on_error:
                    break
                continue

            received += len(external)
            valid_by_time = {}
            previous: datetime | None = None
            for item in external:
                try:
                    bar = normalize_external_bar(
                        item,
                        instrument_id=instrument.id,
                        source_id=source.id,
                        adjustment=adjustment,
                        future_tolerance=self._future_tolerance,
                    )
                    if item.symbol.upper() != mapping.external_symbol.upper():
                        raise ValueError("provider symbol mismatch")
                    if previous is not None and bar.bar_time < previous:
                        raise ValueError("bars are not ordered")
                    previous = bar.bar_time
                    if bar.bar_time in valid_by_time:
                        raise ValueError("duplicate bar time")
                    valid_by_time[bar.bar_time] = bar
                except (ArithmeticError, TypeError, ValueError):
                    rejected += 1
            valid = list(valid_by_time.values())
            if external and not valid:
                failed += 1
                failures.append(self._failure(instrument, "D01_ALL_BARS_REJECTED"))
                processed += 1
                if progress is not None:
                    progress(index, len(instruments), instrument.symbol, "FAILED_VALIDATION")
                if not continue_on_error:
                    break
                continue
            if not valid:
                skipped += 1
                processed += 1
                if progress is not None:
                    progress(index, len(instruments), instrument.symbol, "SKIPPED_NO_DATA")
                continue
            try:
                instrument_inserted = instrument_updated = instrument_unchanged = 0
                async with self._uow_factory() as uow:
                    for offset in range(0, len(valid), batch_size):
                        result = await uow.market_bars.upsert_many(
                            valid[offset : offset + batch_size]
                        )
                        instrument_inserted += result.inserted
                        instrument_updated += result.updated
                        instrument_unchanged += result.unchanged
                    await uow.commit()
                inserted += instrument_inserted
                updated += instrument_updated
                unchanged += instrument_unchanged
                succeeded += 1
                if progress is not None:
                    progress(index, len(instruments), instrument.symbol, "SUCCEEDED")
            except Exception as exc:
                if not exc.__class__.__module__.startswith(("sqlalchemy", "asyncpg")):
                    raise
                failed += 1
                failures.append(self._failure(instrument, "D01_PERSISTENCE_FAILED"))
                if progress is not None:
                    progress(index, len(instruments), instrument.symbol, "FAILED_PERSISTENCE")
                if not continue_on_error:
                    processed += 1
                    break
            processed += 1

        unprocessed = len(instruments) - processed
        if callable(close_method):
            await close_method()
        if failed and not (succeeded or skipped):
            status = MarketSyncStatus.FAILED
        elif failed or rejected or unprocessed:
            status = MarketSyncStatus.PARTIALLY_SUCCEEDED
        else:
            status = MarketSyncStatus.SUCCEEDED
        metadata: dict[str, object] = {
            **run.metadata,
            "succeeded_instrument_count": succeeded,
            "failed_instrument_count": failed,
            "skipped_instrument_count": skipped,
            "unprocessed_instrument_count": unprocessed,
            "unchanged_bar_count": unchanged,
            "retry_count": retry_count,
            "failures": failures[:100],
        }
        completed_at = datetime.now(UTC)
        error_summary = ";".join(item["code"] for item in failures[:20]) or None
        async with self._uow_factory() as uow:
            await uow.market_sync_runs.update_status(
                run.id,
                status=status,
                completed_at=completed_at,
                total_received=received,
                total_inserted=inserted,
                total_updated=updated,
                total_rejected=rejected,
                error_summary=error_summary,
                metadata=metadata,
            )
            await append_event_and_audit(
                uow,
                event_type=f"HISTORICAL_BACKFILL_{status.value}",
                entity_type="MarketSyncRun",
                entity_id=run.id,
                correlation_id=correlation_id,
                payload={
                    "status": status.value,
                    "succeeded": succeeded,
                    "failed": failed,
                    "skipped": skipped,
                },
                outcome="FAILED" if status is MarketSyncStatus.FAILED else "SUCCESS",
                source="ALPHADESK_D01",
            )
            await uow.commit()
        completed_run = MarketSyncRun(
            source_id=run.source_id,
            trigger_type=run.trigger_type,
            status=status,
            timeframe=run.timeframe,
            adjustment_type=run.adjustment_type,
            requested_symbols=run.requested_symbols,
            started_at=run.started_at,
            correlation_id=run.correlation_id,
            id=run.id,
            requested_start=start,
            requested_end=end,
            completed_at=completed_at,
            total_received=received,
            total_inserted=inserted,
            total_updated=updated,
            total_rejected=rejected,
            error_summary=error_summary,
            metadata=metadata,
        )
        return HistoricalBackfillResult(
            run=completed_run,
            requested=len(instruments),
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            unprocessed=unprocessed,
            unchanged=unchanged,
            retry_count=retry_count,
            failures=tuple(failures),
            dry_run=False,
        )

    async def _fetch_with_retry(
        self,
        *,
        adapter: MarketDataAdapter,
        symbol: str,
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        adjustment: AdjustmentType,
        max_retries: int,
    ) -> tuple[list[ExternalMarketBar], int]:
        for attempt in range(max_retries + 1):
            try:
                values = [
                    item
                    async for item in adapter.fetch_bars(
                        [symbol], timeframe, start, end, adjustment
                    )
                ]
                return values, attempt
            except MarketDataAdapterError:
                if attempt >= max_retries:
                    raise
                await anyio.sleep(min(0.25 * (2**attempt), 1.0))
        raise AssertionError("retry loop exhausted")

    @staticmethod
    def _validate(
        *,
        instruments: list[Instrument],
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        batch_size: int,
        max_retries: int,
        request_interval_seconds: float,
    ) -> tuple[datetime, datetime]:
        if not instruments or len(instruments) > MAX_RESEARCH_INSTRUMENTS:
            raise ApplicationError(
                "D01_BACKFILL_INSTRUMENT_LIMIT",
                f"单次补数需要 1 到 {MAX_RESEARCH_INSTRUMENTS} 个标的",
            )
        if len({item.id for item in instruments}) != len(instruments):
            raise ApplicationError("D01_BACKFILL_DUPLICATE_INSTRUMENT", "补数标的不得重复")
        if timeframe is not MarketTimeframe.DAY_1:
            raise ApplicationError("D01_TIMEFRAME_UNSUPPORTED", "D01-B 仅支持 DAY_1 日线")
        if start.tzinfo is None or end.tzinfo is None:
            raise ApplicationError("MARKET_DATA_INVALID_RANGE", "时间范围必须包含时区")
        normalized_start = start.astimezone(UTC)
        normalized_end = end.astimezone(UTC)
        if normalized_start > normalized_end:
            raise ApplicationError("MARKET_DATA_INVALID_RANGE", "开始时间不能晚于结束时间")
        if not 1 <= batch_size <= 5_000:
            raise ApplicationError("D01_BATCH_SIZE_INVALID", "batch_size 必须在 1 到 5000 之间")
        if not 0 <= max_retries <= 2:
            raise ApplicationError("D01_RETRY_LIMIT_INVALID", "max_retries 必须在 0 到 2 之间")
        if not 0 <= request_interval_seconds <= 10:
            raise ApplicationError("D01_THROTTLE_INVALID", "请求间隔必须在 0 到 10 秒之间")
        return normalized_start, normalized_end

    @staticmethod
    def _failure(instrument: Instrument, code: str) -> dict[str, str]:
        return {"instrument_id": str(instrument.id), "symbol": instrument.symbol, "code": code}


def _normalize_symbol(value: str) -> str:
    normalized = value.strip().upper()
    if "." in normalized:
        normalized = normalized.split(".")[-1]
    return normalized
