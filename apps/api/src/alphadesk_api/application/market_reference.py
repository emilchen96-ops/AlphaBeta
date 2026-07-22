"""D02 market-reference synchronization, query and readiness services."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, Protocol
from uuid import UUID

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import AdjustmentType, MarketTimeframe
from alphadesk_domain.market import MarketBar
from alphadesk_domain.market_reference import (
    AdjustedBar,
    AdjustedMarketBarService,
    AdjustmentFactor,
    AdjustmentFactorProvider,
    FactorConvention,
    InstrumentLifecycleEvent,
    InstrumentLifecycleProvider,
    InstrumentLifecycleType,
    InstrumentTradingStatus,
    MarketReferenceError,
    PriceAdjustmentMode,
    SuspensionProvider,
    TradingCalendarProvider,
    TradingCalendarService,
    TradingCalendarSession,
)

ReferenceKind = Literal["calendar", "adjustments", "suspensions", "instrument_lifecycle"]


class MarketReferenceProvider(
    TradingCalendarProvider,
    AdjustmentFactorProvider,
    SuspensionProvider,
    InstrumentLifecycleProvider,
    Protocol,
):
    """Combined provider contract used by the D02 synchronization service."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ReferenceSyncResult:
    kind: ReferenceKind
    provider: str
    requested: int
    received: int
    persisted: int
    dry_run: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketReferenceStatus:
    calendar_provider: str
    adjustment_provider: str
    suspension_provider: str
    provider_configured: bool
    calendar_sessions: int
    open_sessions: int
    calendar_start: date | None
    calendar_end: date | None
    latest_completed_session: date | None
    adjustment_factors: int
    adjustment_instruments: int
    latest_factor_date: date | None
    qfq_ready_instruments: int
    trading_statuses: int
    suspended_sessions: int
    latest_status_date: date | None
    lifecycle_events: int
    lifecycle_instruments: int
    raw_price_ready: bool
    adjusted_price_ready: bool
    calendar_ready: bool
    suspension_ready: bool
    scanner_ready: bool
    strategy_ready: bool
    backtest_ready: bool
    replay_ready: bool
    warnings: tuple[str, ...]


class ReferenceMarketDataSyncService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        provider: MarketReferenceProvider,
        provider_name: str,
    ) -> None:
        self._uow_factory = uow_factory
        self._provider = provider
        self._provider_name = provider_name.upper()

    async def sync_calendar(
        self, *, start: date, end: date, exchanges: tuple[str, ...], dry_run: bool
    ) -> ReferenceSyncResult:
        values: list[TradingCalendarSession] = []
        for exchange in exchanges:
            values.extend(await self._provider.fetch_calendar(exchange, start, end))
        persisted = 0
        if not dry_run:
            async with self._uow_factory() as uow:
                persisted = await uow.trading_calendar.upsert_many(values)
                await uow.commit()
        return ReferenceSyncResult(
            kind="calendar",
            provider=self._provider_name,
            requested=len(exchanges),
            received=len(values),
            persisted=persisted,
            dry_run=dry_run,
        )

    async def sync_adjustments(
        self, *, instruments: list[Instrument], start: date, end: date, dry_run: bool
    ) -> ReferenceSyncResult:
        values: list[AdjustmentFactor] = []
        warnings: list[str] = []
        for instrument in instruments:
            try:
                values.extend(await self._provider.fetch_adjustments([instrument.id], start, end))
            except Exception as exc:
                warnings.append(f"{instrument.symbol}: {type(exc).__name__}")
        persisted = 0
        if not dry_run:
            async with self._uow_factory() as uow:
                persisted = await uow.adjustment_factors.upsert_many(values)
                await uow.commit()
        return ReferenceSyncResult(
            kind="adjustments",
            provider=self._provider_name,
            requested=len(instruments),
            received=len(values),
            persisted=persisted,
            dry_run=dry_run,
            warnings=tuple(warnings),
        )

    async def sync_suspensions(
        self, *, instruments: list[Instrument], start: date, end: date, dry_run: bool
    ) -> ReferenceSyncResult:
        values: list[InstrumentTradingStatus] = []
        warnings: list[str] = []
        for instrument in instruments:
            try:
                values.extend(await self._provider.fetch_suspensions([instrument.id], start, end))
            except Exception as exc:
                warnings.append(f"{instrument.symbol}: {type(exc).__name__}")
        persisted = 0
        if not dry_run:
            async with self._uow_factory() as uow:
                persisted = await uow.instrument_trading_statuses.upsert_many(values)
                await uow.commit()
        return ReferenceSyncResult(
            kind="suspensions",
            provider=self._provider_name,
            requested=len(instruments),
            received=len(values),
            persisted=persisted,
            dry_run=dry_run,
            warnings=tuple(warnings),
        )

    async def sync_lifecycle(
        self, *, instruments: list[Instrument], dry_run: bool
    ) -> ReferenceSyncResult:
        values: list[InstrumentLifecycleEvent] = []
        warnings: list[str] = []
        for instrument in instruments:
            try:
                values.extend(await self._provider.fetch_lifecycle([instrument.id]))
            except Exception as exc:
                warnings.append(f"{instrument.symbol}: {type(exc).__name__}")
        persisted = 0
        if not dry_run:
            instruments_by_id = {item.id: item for item in instruments}
            for event in sorted(values, key=lambda item: item.event_date):
                lifecycle_instrument = instruments_by_id.get(event.instrument_id)
                if lifecycle_instrument is None:
                    continue
                if event.event_type is InstrumentLifecycleType.LISTED:
                    lifecycle_instrument.listed_at = (
                        event.event_date
                        if lifecycle_instrument.listed_at is None
                        else min(lifecycle_instrument.listed_at, event.event_date)
                    )
                elif event.event_type is InstrumentLifecycleType.DELISTED:
                    lifecycle_instrument.delisted_at = event.event_date
                    lifecycle_instrument.is_active = False
                elif (
                    event.event_type is InstrumentLifecycleType.RESUMED
                    and lifecycle_instrument.delisted_at is None
                ):
                    lifecycle_instrument.is_active = True
            async with self._uow_factory() as uow:
                persisted = await uow.instrument_lifecycle_events.upsert_many(values)
                await uow.instruments.upsert_many(instruments)
                await uow.commit()
        return ReferenceSyncResult(
            kind="instrument_lifecycle",
            provider=self._provider_name,
            requested=len(instruments),
            received=len(values),
            persisted=persisted,
            dry_run=dry_run,
            warnings=tuple(warnings),
        )


class MarketReferenceQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def calendar(
        self, *, exchange: str | None, start: date | None, end: date | None, limit: int
    ) -> list[TradingCalendarSession]:
        async with self._uow_factory() as uow:
            return await uow.trading_calendar.list(
                exchange=exchange, start=start, end=end, limit=limit
            )

    async def adjustments(
        self,
        *,
        instrument_ids: list[UUID] | None,
        start: date | None,
        end: date | None,
        limit: int,
    ) -> list[AdjustmentFactor]:
        async with self._uow_factory() as uow:
            return await uow.adjustment_factors.list(
                instrument_ids=instrument_ids,
                start=start,
                end=end,
                source=None,
                convention=None,
                limit=limit,
            )

    async def suspensions(
        self,
        *,
        instrument_ids: list[UUID] | None,
        start: date | None,
        end: date | None,
        limit: int,
    ) -> list[InstrumentTradingStatus]:
        async with self._uow_factory() as uow:
            return await uow.instrument_trading_statuses.list(
                instrument_ids=instrument_ids, start=start, end=end, limit=limit
            )

    async def lifecycle(
        self, *, instrument_ids: list[UUID] | None, limit: int
    ) -> list[InstrumentLifecycleEvent]:
        async with self._uow_factory() as uow:
            return await uow.instrument_lifecycle_events.list(
                instrument_ids=instrument_ids, limit=limit
            )

    async def status(self) -> MarketReferenceStatus:
        async with self._uow_factory() as uow:
            calendar = await uow.trading_calendar.list(
                exchange=None, start=None, end=None, limit=100_000
            )
            factors = await uow.adjustment_factors.list(
                instrument_ids=None,
                start=None,
                end=None,
                source=None,
                convention=None,
                limit=100_000,
            )
            statuses = await uow.instrument_trading_statuses.list(
                instrument_ids=None, start=None, end=None, limit=100_000
            )
            lifecycle = await uow.instrument_lifecycle_events.list(
                instrument_ids=None, limit=100_000
            )
        latest_completed: date | None = None
        warnings: list[str] = []
        if calendar:
            try:
                latest_completed = TradingCalendarService(calendar).latest_completed_session(
                    "SHSE", datetime.now(UTC)
                )
            except MarketReferenceError:
                warnings.append("SHSE 最新已完成交易日不可用")
        else:
            warnings.append("交易日历尚未同步")
        if not factors:
            warnings.append("复权因子尚未同步, QFQ 不可用")
        if not statuses:
            warnings.append("停复牌数据尚未同步, 按兼容模式运行")
        factor_instruments = {item.instrument_id for item in factors}
        lifecycle_instruments = {item.instrument_id for item in lifecycle}
        calendar_ready = bool(calendar)
        raw_ready = True
        adjusted_ready = bool(factors)
        suspension_ready = bool(statuses)

        def provider_name(values: Sequence[object]) -> str:
            sources = sorted(
                {
                    str(source)
                    for item in values
                    if (source := getattr(item, "source", None)) is not None
                }
            )
            return ",".join(sources) if sources else "NOT_SYNCED"

        return MarketReferenceStatus(
            calendar_provider=provider_name(calendar),
            adjustment_provider=provider_name(factors),
            suspension_provider=provider_name(statuses),
            provider_configured=True,
            calendar_sessions=len(calendar),
            open_sessions=sum(item.is_open for item in calendar),
            calendar_start=min((item.session_date for item in calendar), default=None),
            calendar_end=max((item.session_date for item in calendar), default=None),
            latest_completed_session=latest_completed,
            adjustment_factors=len(factors),
            adjustment_instruments=len(factor_instruments),
            latest_factor_date=max((item.trade_date for item in factors), default=None),
            qfq_ready_instruments=len(factor_instruments),
            trading_statuses=len(statuses),
            suspended_sessions=sum(item.status.value == "SUSPENDED" for item in statuses),
            latest_status_date=max((item.session_date for item in statuses), default=None),
            lifecycle_events=len(lifecycle),
            lifecycle_instruments=len(lifecycle_instruments),
            raw_price_ready=raw_ready,
            adjusted_price_ready=adjusted_ready,
            calendar_ready=calendar_ready,
            suspension_ready=suspension_ready,
            scanner_ready=raw_ready,
            strategy_ready=raw_ready,
            backtest_ready=raw_ready and calendar_ready,
            replay_ready=raw_ready and calendar_ready,
            warnings=tuple(warnings),
        )


class AdjustedHistoricalMarketDataService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory
        self._adjuster = AdjustedMarketBarService()

    async def bars(
        self,
        *,
        instrument_id: UUID,
        source_code: str,
        start: datetime,
        end: datetime,
        limit: int,
        mode: PriceAdjustmentMode,
    ) -> tuple[list[MarketBar], tuple[AdjustedBar, ...]]:
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(source_code)
            if source is None:
                raise ApplicationError("MARKET_DATA_PROVIDER_NOT_AVAILABLE", "行情源不存在")
            raw = await uow.market_bars.get_bars(
                instrument_id=instrument_id,
                source_id=source.id,
                timeframe=MarketTimeframe.DAY_1,
                adjustment_type=AdjustmentType.NONE,
                start=start,
                end=end,
                limit=limit,
            )
            factors = await uow.adjustment_factors.list(
                instrument_ids=[instrument_id],
                start=start.date(),
                end=end.date(),
                source=None,
                convention=FactorConvention.TUSHARE_CUMULATIVE,
                limit=limit,
            )
        try:
            adjusted = self._adjuster.adjust(raw, factors, mode)
        except MarketReferenceError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        return raw, adjusted

    async def adjust_existing(
        self, bars: list[MarketBar], mode: PriceAdjustmentMode
    ) -> tuple[AdjustedBar, ...]:
        if not bars:
            return ()
        if mode is PriceAdjustmentMode.RAW:
            return self._adjuster.adjust(bars, [], mode)
        instrument_ids = {item.instrument_id for item in bars}
        if len(instrument_ids) != 1:
            raise ApplicationError(
                "MARKET_ADJUSTMENT_FACTOR_NOT_AVAILABLE", "单次复权查询只能包含一个标的"
            )
        async with self._uow_factory() as uow:
            factors = await uow.adjustment_factors.list(
                instrument_ids=list(instrument_ids),
                start=min(item.bar_time.date() for item in bars),
                end=max(item.bar_time.date() for item in bars),
                source=None,
                convention=FactorConvention.TUSHARE_CUMULATIVE,
                limit=len(bars) + 10,
            )
        try:
            return self._adjuster.adjust(bars, factors, mode)
        except MarketReferenceError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
