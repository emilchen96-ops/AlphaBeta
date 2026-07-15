"""Read-only market-data adapter port and external DTOs."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from alphadesk_domain.enums import AdjustmentType, MarketDataSourceStatus, MarketTimeframe


class MarketDataAdapterError(Exception):
    """Controlled adapter failure safe for application handling."""


class MarketDataAdapterDisabledError(MarketDataAdapterError):
    """Raised when an explicitly disabled adapter is invoked."""


class MarketDataAdapterRangeError(MarketDataAdapterError):
    """Raised when a requested range is invalid."""


class MarketDataAdapterTimeframeError(MarketDataAdapterError):
    """Raised when an adapter does not support a requested timeframe."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketDataHealth:
    status: MarketDataSourceStatus
    checked_at: datetime
    message: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalInstrument:
    symbol: str
    exchange: str
    market: str
    name: str
    asset_type: str
    currency: str
    lot_size: str
    price_tick: str
    timezone: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalMarketBar:
    symbol: str
    timeframe: MarketTimeframe
    bar_time: datetime
    open: str
    high: str
    low: str
    close: str
    volume: str
    amount: str | None = None
    vwap: str | None = None
    open_interest: str | None = None
    source_updated_at: datetime | None = None


class MarketDataAdapter(Protocol):
    @property
    def source_code(self) -> str: ...

    async def health_check(self) -> MarketDataHealth: ...

    async def list_instruments(
        self,
        exchange: str | None = None,
        market: str | None = None,
    ) -> list[ExternalInstrument]: ...

    def fetch_bars(
        self,
        symbols: list[str],
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        adjustment: AdjustmentType,
    ) -> AsyncIterator[ExternalMarketBar]: ...
