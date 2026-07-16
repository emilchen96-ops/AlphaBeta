"""AKShare/EastMoney free best-effort quote and recent minute-bar adapter."""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import anyio

from alphadesk_domain.enums import AdjustmentType, MarketDataSourceStatus, MarketTimeframe
from alphadesk_domain.market_adapters import (
    ExternalInstrument,
    ExternalMarketBar,
    ExternalMarketQuote,
    MarketDataAdapterError,
    MarketDataHealth,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class AkShareClient(Protocol):
    def spot_records(self) -> list[dict[str, Any]]: ...
    def minute_records(self, symbol: str) -> list[dict[str, Any]]: ...


class NativeAkShareClient:
    """Keep pandas objects inside the third-party client boundary."""

    def spot_records(self) -> list[dict[str, Any]]:
        import akshare as ak

        return list(ak.stock_zh_a_spot_em().to_dict(orient="records"))

    def minute_records(self, symbol: str) -> list[dict[str, Any]]:
        import akshare as ak

        return list(
            ak.stock_zh_a_hist_min_em(symbol=symbol, period="1", adjust="").to_dict(
                orient="records"
            )
        )


def _text(record: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = record.get(name)
        if value is not None and str(value).strip() not in {"", "-", "nan", "None"}:
            return str(value).strip()
    return None


def _minute_time(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI)
    return parsed.astimezone(UTC)


class AkShareEastMoneyRealtimeAdapter:
    source_code = "AKSHARE_EASTMONEY"

    def __init__(
        self,
        client: AkShareClient | None = None,
        run_sync: Callable[..., Any] = anyio.to_thread.run_sync,
    ) -> None:
        self._client = client or NativeAkShareClient()
        self._run_sync = run_sync

    async def health_check(self) -> MarketDataHealth:
        checked_at = datetime.now(UTC)
        try:
            records = await self._run_sync(self._client.spot_records)
        except Exception as exc:
            return MarketDataHealth(
                status=MarketDataSourceStatus.DEGRADED,
                checked_at=checked_at,
                message=f"AKShare/EastMoney unavailable: {type(exc).__name__}",
            )
        return MarketDataHealth(
            status=MarketDataSourceStatus.ACTIVE if records else MarketDataSourceStatus.DEGRADED,
            checked_at=checked_at,
            message=f"received {len(records)} snapshot rows",
        )

    async def fetch_quotes(self, symbols: list[str]) -> list[ExternalMarketQuote]:
        requested = {symbol.upper() for symbol in symbols}
        try:
            records = await self._run_sync(self._client.spot_records)
        except Exception as exc:
            raise MarketDataAdapterError(
                f"AKShare/EastMoney quote request failed: {type(exc).__name__}"
            ) from exc
        quotes: list[ExternalMarketQuote] = []
        for record in records:
            symbol = _text(record, "代码", "symbol", "code")
            price = _text(record, "最新价", "last_price")
            if symbol is None or price is None or symbol.upper() not in requested:
                continue
            quotes.append(
                ExternalMarketQuote(
                    symbol=symbol.upper(),
                    quote_time=None,
                    last_price=price,
                    previous_close=_text(record, "昨收", "previous_close"),
                    open=_text(record, "今开", "open"),
                    high=_text(record, "最高", "high"),
                    low=_text(record, "最低", "low"),
                    volume=_text(record, "成交量", "volume"),
                    amount=_text(record, "成交额", "amount"),
                )
            )
        return quotes

    async def list_instruments(
        self, exchange: str | None = None, market: str | None = None
    ) -> list[ExternalInstrument]:
        del market
        try:
            records = await self._run_sync(self._client.spot_records)
        except Exception as exc:
            raise MarketDataAdapterError(
                f"AKShare/EastMoney instrument request failed: {type(exc).__name__}"
            ) from exc
        items: list[ExternalInstrument] = []
        for record in records:
            symbol = _text(record, "代码", "symbol", "code")
            name = _text(record, "名称", "name")
            if symbol is None or name is None:
                continue
            item_exchange = (
                "SSE"
                if symbol.startswith("6")
                else "BSE"
                if symbol.startswith(("4", "8"))
                else "SZSE"
            )
            if exchange is not None and item_exchange != exchange.upper():
                continue
            items.append(
                ExternalInstrument(
                    symbol=symbol,
                    exchange=item_exchange,
                    market="CN_A",
                    name=name,
                    asset_type="STOCK",
                    currency="CNY",
                    lot_size="100",
                    price_tick="0.01",
                    timezone="Asia/Shanghai",
                )
            )
        return items

    async def fetch_bars(
        self,
        symbols: list[str],
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        adjustment: AdjustmentType,
    ) -> AsyncIterator[ExternalMarketBar]:
        if timeframe is not MarketTimeframe.MINUTE_1 or adjustment is not AdjustmentType.NONE:
            raise MarketDataAdapterError("AKShare recent bars support only unadjusted MINUTE_1")
        async for bar in self.fetch_recent_minute_bars(symbols, start, end):
            yield bar

    async def fetch_recent_minute_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> AsyncIterator[ExternalMarketBar]:
        start_utc = start.astimezone(UTC)
        end_utc = end.astimezone(UTC)
        for symbol in symbols:
            try:
                records = await self._run_sync(self._client.minute_records, symbol)
            except Exception as exc:
                raise MarketDataAdapterError(
                    f"AKShare/EastMoney minute request failed: {type(exc).__name__}"
                ) from exc
            for record in records:
                time_text = _text(record, "时间", "datetime")
                if time_text is None:
                    continue
                bar_time = _minute_time(time_text)
                if not start_utc <= bar_time <= end_utc:
                    continue
                values = {
                    name: _text(record, chinese, name)
                    for name, chinese in (
                        ("open", "开盘"),
                        ("high", "最高"),
                        ("low", "最低"),
                        ("close", "收盘"),
                        ("volume", "成交量"),
                    )
                }
                if any(value is None for value in values.values()):
                    continue
                yield ExternalMarketBar(
                    symbol=symbol.upper(),
                    timeframe=MarketTimeframe.MINUTE_1,
                    bar_time=bar_time,
                    open=values["open"] or "",
                    high=values["high"] or "",
                    low=values["low"] or "",
                    close=values["close"] or "",
                    volume=values["volume"] or "",
                    amount=_text(record, "成交额", "amount"),
                )
