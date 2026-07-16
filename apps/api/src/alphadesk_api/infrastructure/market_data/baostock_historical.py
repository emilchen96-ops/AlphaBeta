"""BaoStock free best-effort historical market-data adapter."""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import anyio

from alphadesk_domain.enums import AdjustmentType, MarketDataSourceStatus, MarketTimeframe
from alphadesk_domain.market_adapters import (
    ExternalInstrument,
    ExternalMarketBar,
    MarketDataAdapterError,
    MarketDataAdapterTimeframeError,
    MarketDataHealth,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
FREQUENCIES = {
    MarketTimeframe.DAY_1: "d",
    MarketTimeframe.MINUTE_5: "5",
    MarketTimeframe.MINUTE_15: "15",
    MarketTimeframe.MINUTE_30: "30",
    MarketTimeframe.MINUTE_60: "60",
}
ADJUSTMENTS = {AdjustmentType.NONE: "3", AdjustmentType.FORWARD: "2", AdjustmentType.BACKWARD: "1"}


class BaoStockClient(Protocol):
    def health(self) -> tuple[bool, str]: ...
    def history(
        self, symbol: str, fields: str, start: str, end: str, frequency: str, adjustment: str
    ) -> list[dict[str, str]]: ...


class NativeBaoStockClient:
    def health(self) -> tuple[bool, str]:
        import baostock as bs

        result = bs.login()
        try:
            return result.error_code == "0", str(result.error_msg)
        finally:
            bs.logout()

    def history(
        self, symbol: str, fields: str, start: str, end: str, frequency: str, adjustment: str
    ) -> list[dict[str, str]]:
        import baostock as bs

        login = bs.login()
        if login.error_code != "0":
            raise RuntimeError(f"BaoStock login failed: {login.error_msg}")
        try:
            result = bs.query_history_k_data_plus(
                symbol,
                fields,
                start_date=start,
                end_date=end,
                frequency=frequency,
                adjustflag=adjustment,
            )
            if result.error_code != "0":
                raise RuntimeError(f"BaoStock query failed: {result.error_msg}")
            rows: list[dict[str, str]] = []
            while result.next():
                rows.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
            return rows
        finally:
            bs.logout()


def _symbol(value: str) -> str:
    lowered = value.lower()
    if lowered.startswith(("sh.", "sz.", "bj.")):
        return lowered
    prefix = "sh" if value.startswith("6") else "bj" if value.startswith(("4", "8")) else "sz"
    return f"{prefix}.{value}"


def _time(row: dict[str, str], timeframe: MarketTimeframe) -> datetime:
    if timeframe is MarketTimeframe.DAY_1:
        return datetime.strptime(row["date"], "%Y-%m-%d").replace(tzinfo=UTC)
    raw = row.get("time", "")
    parsed = datetime.strptime(raw[:14], "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
    return parsed.astimezone(UTC)


class BaoStockHistoricalMarketDataAdapter:
    source_code = "BAOSTOCK"

    def __init__(
        self,
        client: BaoStockClient | None = None,
        run_sync: Callable[..., Any] = anyio.to_thread.run_sync,
    ) -> None:
        self._client = client or NativeBaoStockClient()
        self._run_sync = run_sync

    async def health_check(self) -> MarketDataHealth:
        checked_at = datetime.now(UTC)
        try:
            ok, message = await self._run_sync(self._client.health)
        except Exception as exc:
            ok, message = False, f"BaoStock unavailable: {type(exc).__name__}"
        return MarketDataHealth(
            status=MarketDataSourceStatus.ACTIVE if ok else MarketDataSourceStatus.DEGRADED,
            checked_at=checked_at,
            message=message,
        )

    async def list_instruments(
        self, exchange: str | None = None, market: str | None = None
    ) -> list[ExternalInstrument]:
        del exchange, market
        return []

    async def fetch_bars(
        self,
        symbols: list[str],
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        adjustment: AdjustmentType,
    ) -> AsyncIterator[ExternalMarketBar]:
        frequency = FREQUENCIES.get(timeframe)
        if frequency is None:
            raise MarketDataAdapterTimeframeError(f"BaoStock does not support {timeframe.value}")
        # BaoStock rejects the `time` field for daily requests. It is available
        # only for intraday frequencies, so build the field list by timeframe.
        fields = "date,code,open,high,low,close,volume,amount"
        if timeframe is not MarketTimeframe.DAY_1:
            fields = "date,time,code,open,high,low,close,volume,amount"
        for requested in symbols:
            try:
                rows = await self._run_sync(
                    self._client.history,
                    _symbol(requested),
                    fields,
                    start.date().isoformat(),
                    end.date().isoformat(),
                    frequency,
                    ADJUSTMENTS[adjustment],
                )
            except Exception as exc:
                raise MarketDataAdapterError(
                    f"BaoStock history request failed: {type(exc).__name__}"
                ) from exc
            for row in rows:
                if not all(row.get(name) for name in ("open", "high", "low", "close", "volume")):
                    continue
                yield ExternalMarketBar(
                    symbol=requested.upper(),
                    timeframe=timeframe,
                    bar_time=_time(row, timeframe),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    amount=row.get("amount") or None,
                )
