"""Read-only ephemeral account valuation using Redis quotes with daily-bar fallback."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.infrastructure.free_market_cache import QuoteCache
from alphadesk_domain.enums import AdjustmentType, MarketTimeframe, QuoteFreshnessStatus
from alphadesk_domain.market import MarketBar
from alphadesk_domain.realtime_market import AccountLiveValuation, PositionLiveValuation


class LiveAccountValuationService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        quote_cache: QuoteCache,
        stale_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._quote_cache = quote_cache
        self._stale_seconds = stale_seconds

    async def value(self, account_id: UUID) -> AccountLiveValuation:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            account = await uow.accounts.get_by_id(account_id)
            if account is None:
                raise ApplicationError("ACCOUNT_NOT_FOUND", "账户不存在")
            balances = await uow.cash_balances.list_for_account(account_id)
            positions = [
                item
                for item in await uow.positions.list_for_account(account_id)
                if item.total_quantity > 0
            ]
            instruments = await uow.instruments.get_many(
                [position.instrument_id for position in positions]
            )
            sources = await uow.market_data_sources.list_active()
            fallback: dict[UUID, tuple[MarketBar, str]] = {}
            for source in sources:
                bars = await uow.market_bars.get_latest_for_instruments(
                    instrument_ids=[position.instrument_id for position in positions],
                    source_id=source.id,
                    timeframe=MarketTimeframe.DAY_1,
                    adjustment_type=AdjustmentType.NONE,
                )
                for bar in bars:
                    fallback.setdefault(bar.instrument_id, (bar, source.source_code))

        snapshots = {
            item.quote.instrument_id: item
            for item in await self._quote_cache.get_many(
                [position.instrument_id for position in positions]
            )
        }
        instruments_by_id = {item.id: item for item in instruments}
        values: list[PositionLiveValuation] = []
        total_market_value = Decimal("0")
        missing = 0
        stale = 0
        for position in positions:
            snapshot = snapshots.get(position.instrument_id)
            price: Decimal | None = None
            price_source: str | None = None
            price_time = None
            freshness = QuoteFreshnessStatus.MISSING
            if snapshot is not None:
                price = snapshot.quote.last_price
                price_source = snapshot.quote.source_code
                price_time = snapshot.quote.quote_time
                age = max(0, int((now - snapshot.quote.received_at).total_seconds()))
                freshness = (
                    QuoteFreshnessStatus.FRESH
                    if age <= self._stale_seconds
                    else QuoteFreshnessStatus.STALE
                )
            elif position.instrument_id in fallback:
                bar, source_code = fallback[position.instrument_id]
                price = bar.close
                price_source = f"{source_code}:DAY_1_FALLBACK"
                price_time = bar.bar_time
                freshness = QuoteFreshnessStatus.STALE
            if freshness is QuoteFreshnessStatus.MISSING:
                missing += 1
            elif freshness is QuoteFreshnessStatus.STALE:
                stale += 1
            market_value = None if price is None else position.total_quantity * price
            unrealized_pnl = None if market_value is None else market_value - position.cost_basis
            if market_value is not None:
                total_market_value += market_value
            instrument = instruments_by_id.get(position.instrument_id)
            values.append(
                PositionLiveValuation(
                    instrument_id=position.instrument_id,
                    symbol=instrument.symbol
                    if instrument is not None
                    else str(position.instrument_id),
                    quantity=position.total_quantity,
                    price=price,
                    market_value=market_value,
                    unrealized_pnl=unrealized_pnl,
                    price_source=price_source,
                    quote_time=price_time,
                    freshness=freshness,
                )
            )
        cash = sum(
            (item.total_cash for item in balances if item.currency == account.base_currency),
            start=Decimal("0"),
        )
        status = "UNAVAILABLE" if missing else "STALE" if stale else "COMPLETE"
        return AccountLiveValuation(
            account_id=account_id,
            cash_balance=cash,
            positions_market_value=total_market_value,
            total_equity=cash + total_market_value,
            status=status,
            calculated_at=now,
            positions=tuple(values),
        )
