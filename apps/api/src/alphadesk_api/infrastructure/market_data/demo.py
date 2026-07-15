"""Deterministic offline market-data adapter for development and CI."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphadesk_domain.enums import AdjustmentType, MarketDataSourceStatus, MarketTimeframe
from alphadesk_domain.market_adapters import (
    ExternalInstrument,
    ExternalMarketBar,
    MarketDataAdapterRangeError,
    MarketDataAdapterTimeframeError,
    MarketDataHealth,
)

DEMO_INSTRUMENTS = (
    ExternalInstrument(
        symbol="600000",
        exchange="SSE",
        market="CN_A",
        name="浦发银行(演示)",
        asset_type="EQUITY",
        currency="CNY",
        lot_size="100",
        price_tick="0.01",
        timezone="Asia/Shanghai",
    ),
    ExternalInstrument(
        symbol="000001",
        exchange="SZSE",
        market="CN_A",
        name="平安银行(演示)",
        asset_type="EQUITY",
        currency="CNY",
        lot_size="100",
        price_tick="0.01",
        timezone="Asia/Shanghai",
    ),
    ExternalInstrument(
        symbol="510300",
        exchange="SSE",
        market="CN_A",
        name="沪深300ETF(演示)",
        asset_type="ETF",
        currency="CNY",
        lot_size="100",
        price_tick="0.001",
        timezone="Asia/Shanghai",
    ),
)


class DemoCsvMarketDataAdapter:
    """Generate fixed DEMO bars without network, randomness, or credentials."""

    source_code = "DEMO"
    supported_timeframes = (MarketTimeframe.DAY_1, MarketTimeframe.MINUTE_1)

    async def health_check(self) -> MarketDataHealth:
        return MarketDataHealth(
            status=MarketDataSourceStatus.ACTIVE,
            checked_at=datetime.now(UTC),
            message="offline deterministic demo source",
        )

    async def list_instruments(
        self,
        exchange: str | None = None,
        market: str | None = None,
    ) -> list[ExternalInstrument]:
        return [
            instrument
            for instrument in DEMO_INSTRUMENTS
            if (exchange is None or instrument.exchange == exchange.upper())
            and (market is None or instrument.market == market.upper())
        ]

    async def fetch_bars(
        self,
        symbols: list[str],
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        adjustment: AdjustmentType,
    ) -> AsyncIterator[ExternalMarketBar]:
        del adjustment
        if start.tzinfo is None or end.tzinfo is None:
            raise MarketDataAdapterRangeError("start and end must be timezone-aware")
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        if start > end:
            raise MarketDataAdapterRangeError("start must not be later than end")
        if timeframe not in self.supported_timeframes:
            raise MarketDataAdapterTimeframeError(f"DEMO does not support {timeframe.value}")
        known = {instrument.symbol for instrument in DEMO_INSTRUMENTS}
        requested = [symbol for symbol in symbols if symbol in known]
        for symbol_index, symbol in enumerate(requested):
            async for bar in self._bars_for_symbol(symbol, symbol_index, timeframe):
                if start <= bar.bar_time <= end:
                    yield bar

    async def _bars_for_symbol(
        self, symbol: str, symbol_index: int, timeframe: MarketTimeframe
    ) -> AsyncIterator[ExternalMarketBar]:
        if timeframe is MarketTimeframe.DAY_1:
            first = datetime(2025, 1, 1, tzinfo=UTC)
            count = 180
            step = timedelta(days=1)
        else:
            first = datetime(2025, 7, 1, 1, 30, tzinfo=UTC)
            count = 600
            step = timedelta(minutes=1)
        base = Decimal("8") + Decimal(symbol_index * 4)
        for index in range(count):
            drift = Decimal(index % 40) / Decimal("100")
            wave = Decimal((index % 7) - 3) / Decimal("100")
            open_price = base + drift
            close_price = open_price + wave
            high = max(open_price, close_price) + Decimal("0.05")
            low = min(open_price, close_price) - Decimal("0.05")
            volume = Decimal(100_000 + symbol_index * 10_000 + index * 100)
            amount = volume * close_price
            bar_time = first + step * index
            yield ExternalMarketBar(
                symbol=symbol,
                timeframe=timeframe,
                bar_time=bar_time,
                open=str(open_price),
                high=str(high),
                low=str(low),
                close=str(close_price),
                volume=str(volume),
                amount=str(amount),
                vwap=str((open_price + close_price) / Decimal("2")),
                source_updated_at=bar_time + timedelta(seconds=5),
            )
