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
    def instruments(self) -> list[dict[str, str]]: ...
    def history(
        self, symbol: str, fields: str, start: str, end: str, frequency: str, adjustment: str
    ) -> list[dict[str, str]]: ...


class NativeBaoStockClient:
    def __init__(self) -> None:
        self._session_open = False

    def open(self) -> None:
        if self._session_open:
            return
        import baostock as bs

        result = bs.login()
        if result.error_code != "0":
            raise RuntimeError(f"BaoStock login failed: {result.error_msg}")
        self._session_open = True

    def close(self) -> None:
        if not self._session_open:
            return
        import baostock as bs

        bs.logout()
        self._session_open = False

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

        owns_session = not self._session_open
        if owns_session:
            self.open()
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
            if owns_session:
                self.close()

    def instruments(self) -> list[dict[str, str]]:
        import baostock as bs

        login = bs.login()
        if login.error_code != "0":
            raise RuntimeError(f"BaoStock login failed: {login.error_msg}")
        try:
            result = bs.query_stock_basic()
            if result.error_code != "0":
                raise RuntimeError(f"BaoStock instrument query failed: {result.error_msg}")
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


def _instrument_identity(code: str) -> tuple[str, str] | None:
    normalized = code.strip().lower()
    if normalized.startswith("sh.6"):
        return normalized[3:], "SSE"
    if normalized.startswith("sz.") and normalized[3:].startswith(("0", "3")):
        return normalized[3:], "SZSE"
    if normalized.startswith("bj.") and normalized[3:].startswith(("4", "8")):
        return normalized[3:], "BSE"
    return None


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

    async def open(self) -> None:
        method = getattr(self._client, "open", None)
        if method is None:
            return
        try:
            await self._run_sync(method)
        except Exception as exc:
            raise MarketDataAdapterError(
                f"BaoStock session open failed: {type(exc).__name__}"
            ) from exc

    async def close(self) -> None:
        method = getattr(self._client, "close", None)
        if method is not None:
            await self._run_sync(method)

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
        try:
            rows = await self._run_sync(self._client.instruments)
        except Exception as exc:
            raise MarketDataAdapterError(
                f"BaoStock instrument request failed: {type(exc).__name__}"
            ) from exc
        values: list[ExternalInstrument] = []
        for row in rows:
            if row.get("type") not in (None, "", "1"):
                continue
            identity = _instrument_identity(row.get("code", ""))
            if identity is None:
                continue
            symbol, resolved_exchange = identity
            if exchange and resolved_exchange != exchange.upper():
                continue
            if market and market.upper() != "CN_A":
                continue
            values.append(
                ExternalInstrument(
                    symbol=symbol,
                    exchange=resolved_exchange,
                    market="CN_A",
                    name=row.get("code_name") or symbol,
                    asset_type="STOCK",
                    currency="CNY",
                    lot_size="100",
                    price_tick="0.01",
                    timezone="Asia/Shanghai",
                    is_active=row.get("status", "1") == "1" and not row.get("outDate"),
                    metadata={
                        "provider_code": row.get("code", ""),
                        "ipo_date": row.get("ipoDate") or None,
                        "out_date": row.get("outDate") or None,
                        "provider_status": row.get("status") or None,
                    },
                )
            )
        return sorted(values, key=lambda item: (item.exchange, item.symbol))

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
        fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg,tradestatus"
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
                    metadata={
                        "pre_close": row.get("preclose") or None,
                        "pct_change": row.get("pctChg") or None,
                        "trading_status": row.get("tradestatus") or None,
                    },
                )
