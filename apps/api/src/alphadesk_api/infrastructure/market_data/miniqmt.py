"""XtQuant boundary for MiniQMT read-only market data.

This module deliberately imports only ``xtquant.xtdata``.  It never imports
``xttrader`` and exposes no account, order, fill, position or cancellation API.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from alphadesk_domain.miniqmt_market import MiniQMTTradingDisabledError

SHANGHAI = ZoneInfo("Asia/Shanghai")
QuoteCallback = Callable[[str, dict[str, Any]], None]
BarCallback = Callable[[str, dict[str, Any]], None]


class MiniQMTNotAvailableError(RuntimeError):
    pass


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    parsed = Decimal(str(value))
    return parsed if parsed.is_finite() else None


def _market_time(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=SHANGHAI).astimezone(UTC)
        return value.astimezone(UTC)
    # pandas commonly exposes QMT's millisecond epoch as a floating-point
    # scalar (for example ``1784683800000.0``).
    milliseconds = int(Decimal(str(value)))
    return datetime.fromtimestamp(milliseconds / 1000, tz=SHANGHAI).astimezone(UTC)


def _daily_bar_time(value: object) -> datetime:
    """Normalize a QMT trading date to UTC midnight without shifting its date."""

    trading_date = _market_time(value).astimezone(SHANGHAI).date()
    return datetime.combine(trading_date, time.min, tzinfo=UTC)


def _minute_bar_start(value: object) -> datetime | None:
    """Convert QMT's one-minute end label to AlphaDesk's bar-start convention."""

    end = _market_time(value).astimezone(SHANGHAI).replace(second=0, microsecond=0)
    # QMT exposes the 09:30 opening-auction aggregate in addition to the 240
    # continuous-auction minute bars. D03 models only regular sessions.
    if end.time() in {time(9, 30), time(13, 0)}:
        return None
    return (end - timedelta(minutes=1)).astimezone(UTC)


def _latest_callback_row(value: object) -> dict[str, Any] | None:
    """Accept the native callback's dict/list/array/DataFrame variants."""

    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return _latest_callback_row(value[-1]) if value else None
    if hasattr(value, "iloc"):
        if len(cast(Any, value)) == 0:
            return None
        row = cast(Any, value).iloc[-1]
        return dict(row.to_dict()) if hasattr(row, "to_dict") else None
    names = getattr(getattr(value, "dtype", None), "names", None)
    if names and len(value):  # type: ignore[arg-type]
        row = value[-1]  # type: ignore[index]
        return {name: item.item() if hasattr(item := row[name], "item") else item for name in names}
    return None


class MiniQMTMarketDataProvider:
    """A small, explicit read-only wrapper around ``xtquant.xtdata``."""

    market_data_capability = "ENABLED"
    trading_capability = "DISABLED"

    def __init__(self, *, data_path: str, xtquant_path: str | None = None) -> None:
        self.data_path = str(Path(data_path))
        if xtquant_path:
            normalized = str(Path(xtquant_path))
            if normalized not in sys.path:
                sys.path.insert(0, normalized)
        try:
            from xtquant import xtdata  # type: ignore[import-untyped]
        except ImportError as exc:
            raise MiniQMTNotAvailableError(
                "未安装XtQuant行情SDK; 请在Windows行情代理环境安装alphadesk-api[miniqmt]。"
            ) from exc
        self._xtdata = xtdata
        configured_path = Path(self.data_path)
        if configured_path.name.lower() == "datadir":
            configured_path = configured_path.parent
        elif (configured_path / "userdata_mini").is_dir():
            configured_path /= "userdata_mini"
        self._xtdata.data_dir = str(configured_path)
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        try:
            self._xtdata.connect()
            client = self._xtdata.get_client()
            if client is None:
                raise MiniQMTNotAvailableError("MINIQMT_NOT_CONNECTED")
            self._connected = True
        except Exception as exc:
            self._connected = False
            if isinstance(exc, MiniQMTNotAvailableError):
                raise
            raise MiniQMTNotAvailableError("MINIQMT_NOT_CONNECTED") from exc

    def instrument_detail(self, provider_symbol: str) -> dict[str, Any]:
        self._require_connection()
        value = self._xtdata.get_instrument_detail(provider_symbol, iscomplete=True)
        return dict(value or {})

    def instrument_catalog(self) -> list[dict[str, object]]:
        """Return the active A-share and ETF catalog exposed by MiniQMT."""

        self._require_connection()
        try:
            available = set(self._xtdata.get_sector_list() or [])
        except Exception:
            available = set()
        preferred = (
            "沪深京A股",
            "沪深A股",
            "上证A股",
            "京市A股",
            "深证A股",
            "北证A股",
            "沪深ETF",
            "沪市ETF",
            "深市ETF",
            "ETF基金",
        )
        sector_names = [name for name in preferred if not available or name in available]
        stock_symbols: set[str] = set()
        etf_symbols: set[str] = set()
        for sector in sector_names:
            try:
                values = set(self._xtdata.get_stock_list_in_sector(sector) or [])
            except Exception:
                continue
            if "ETF" in sector:
                etf_symbols.update(values)
            else:
                stock_symbols.update(values)
        etf_symbols = {str(value).upper() for value in etf_symbols}
        stock_symbols = {str(value).upper() for value in stock_symbols}
        symbols = {
            value
            for value in stock_symbols | etf_symbols
            if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", value)
            and (value in etf_symbols or self._is_a_share_symbol(value))
        }
        output: list[dict[str, object]] = []
        for provider_symbol in sorted(symbols):
            try:
                detail = self.instrument_detail(provider_symbol)
            except Exception:
                continue
            symbol, suffix = provider_symbol.split(".", 1)
            exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[suffix]
            name = str(
                detail.get("InstrumentName")
                or detail.get("instrument_name")
                or detail.get("Name")
                or provider_symbol
            ).strip()
            listed_at = self._catalog_date(
                detail.get("OpenDate") or detail.get("open_date") or detail.get("ListDate")
            )
            delisted_at = self._catalog_date(
                detail.get("ExpireDate") or detail.get("expire_date") or detail.get("DelistDate")
            )
            if listed_at is not None and delisted_at is not None and delisted_at < listed_at:
                delisted_at = None
            is_active = delisted_at is None or date.fromisoformat(delisted_at) >= date.today()
            asset_type = (
                "ETF"
                if provider_symbol in etf_symbols or "ETF" in name.upper() or "交易型开放式" in name
                else "STOCK"
            )
            output.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "market": "CN_A",
                    "name": name,
                    "asset_type": asset_type,
                    "currency": "CNY",
                    "lot_size": "100",
                    "price_tick": "0.001" if asset_type == "ETF" else "0.01",
                    "timezone": "Asia/Shanghai",
                    "is_active": is_active,
                    "listed_at": listed_at,
                    "delisted_at": delisted_at,
                    "provider_symbol": provider_symbol,
                }
            )
        return output

    @staticmethod
    def _is_a_share_symbol(provider_symbol: str) -> bool:
        symbol, _, suffix = provider_symbol.upper().partition(".")
        if suffix == "SH":
            return symbol.startswith(("60", "68"))
        if suffix == "SZ":
            return symbol.startswith(("00", "30"))
        if suffix == "BJ":
            return symbol.startswith(("43", "83", "87", "88", "92"))
        return False

    @staticmethod
    def _catalog_date(value: object) -> str | None:
        text = str(value or "").strip().replace("-", "")
        if (
            text in {"", "0", "None", "nan"}
            or text.startswith("9999")
            or not re.fullmatch(r"\d{8}", text)
        ):
            return None
        year = int(text[:4])
        if year < 1900:
            return None
        normalized = f"{text[:4]}-{text[4:6]}-{text[6:]}"
        try:
            date.fromisoformat(normalized)
        except ValueError:
            return None
        return normalized

    def latest_raw_snapshot(self, provider_symbol: str) -> dict[str, Any] | None:
        self._require_connection()
        value = self._xtdata.get_full_tick([provider_symbol]).get(provider_symbol)
        return None if value is None else dict(value)

    def subscribe_quote(
        self,
        provider_symbol: str,
        callback: QuoteCallback,
        *,
        period: str = "tick",
    ) -> int:
        self._require_connection()

        def on_data(payload: object) -> None:
            if isinstance(payload, dict):
                raw = _latest_callback_row(payload.get(provider_symbol, payload))
                if raw is not None:
                    callback(provider_symbol, raw)

        subscription_id = int(
            self._xtdata.subscribe_quote(
                provider_symbol,
                period=period,
                start_time="",
                end_time="",
                count=0,
                callback=on_data,
            )
        )
        if subscription_id < 0:
            raise MiniQMTNotAvailableError("MINIQMT_SUBSCRIPTION_FAILED")
        return subscription_id

    def unsubscribe(self, subscription_id: int) -> None:
        self._require_connection()
        self._xtdata.unsubscribe_quote(subscription_id)

    def normalize_quote(self, raw: dict[str, Any]) -> dict[str, object]:
        bid_price = raw.get("bidPrice") or []
        ask_price = raw.get("askPrice") or []
        bid_volume = raw.get("bidVol") or []
        ask_volume = raw.get("askVol") or []
        return {
            "market_time": _market_time(raw["time"]),
            "last_price": _decimal(raw.get("lastPrice")),
            "open_price": _decimal(raw.get("open")),
            "high_price": _decimal(raw.get("high")),
            "low_price": _decimal(raw.get("low")),
            "previous_close": _decimal(raw.get("lastClose")),
            "volume": _decimal(raw.get("volume")),
            "amount": _decimal(raw.get("amount")),
            "bid_price_1": _decimal(bid_price[0]) if bid_price else None,
            "ask_price_1": _decimal(ask_price[0]) if ask_price else None,
            "bid_volume_1": _decimal(bid_volume[0]) if bid_volume else None,
            "ask_volume_1": _decimal(ask_volume[0]) if ask_volume else None,
            "upper_limit_price": _decimal(raw.get("upperLimit") or raw.get("upStopPrice")),
            "lower_limit_price": _decimal(raw.get("lowerLimit") or raw.get("downStopPrice")),
            "stock_status": raw.get("stockStatus"),
            "source_sequence": str(raw["transactionNum"])
            if raw.get("transactionNum") is not None
            else None,
        }

    def normalize_minute_bar(self, raw: dict[str, Any]) -> dict[str, object]:
        market_time = _market_time(raw["time"]).astimezone(SHANGHAI)
        start = _minute_bar_start(raw["time"])
        if start is None:
            raise ValueError("MINIQMT_OPENING_AUCTION_BAR_IGNORED")
        return {
            "bar_time": start,
            "open": str(raw["open"]),
            "high": str(raw["high"]),
            "low": str(raw["low"]),
            "close": str(raw.get("close", raw.get("lastPrice"))),
            "volume": str(raw["volume"]),
            "amount": str(raw["amount"]) if raw.get("amount") is not None else None,
            "source_updated_at": market_time.astimezone(UTC),
        }

    def history(
        self,
        provider_symbols: tuple[str, ...],
        *,
        period: str,
        start_time: str,
        end_time: str,
    ) -> list[dict[str, object]]:
        self._require_connection()
        if period not in {"1d", "1m"}:
            raise ValueError("MINIQMT_HISTORY_PERIOD_NOT_ALLOWED")
        self._xtdata.download_history_data2(
            list(provider_symbols),
            period=period,
            start_time=start_time,
            end_time=end_time,
        )
        fields = ["time", "open", "high", "low", "close", "volume", "amount"]
        frames = self._xtdata.get_market_data_ex(
            fields,
            list(provider_symbols),
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=-1,
            dividend_type="none",
            fill_data=False,
        )
        output: list[dict[str, object]] = []
        for symbol, frame in frames.items():
            for _, row in frame.iterrows():
                bar_time = (
                    _daily_bar_time(row["time"])
                    if period == "1d"
                    else _minute_bar_start(row["time"])
                )
                if bar_time is None:
                    continue
                output.append(
                    {
                        "provider_symbol": symbol,
                        "bar_time": bar_time,
                        "open": str(row["open"]),
                        "high": str(row["high"]),
                        "low": str(row["low"]),
                        "close": str(row["close"]),
                        "volume": str(row["volume"]),
                        "amount": str(row["amount"]) if row.get("amount") is not None else None,
                    }
                )
        return output

    def reject_trading_command(self, _message: object) -> None:
        raise MiniQMTTradingDisabledError()

    def _require_connection(self) -> None:
        if not self._connected:
            raise MiniQMTNotAvailableError("MINIQMT_NOT_CONNECTED")
