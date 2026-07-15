"""Explicit disabled entry for a future external read-only provider."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from alphadesk_domain.enums import AdjustmentType, MarketDataSourceStatus, MarketTimeframe
from alphadesk_domain.market_adapters import (
    ExternalInstrument,
    ExternalMarketBar,
    MarketDataAdapterDisabledError,
    MarketDataHealth,
)


class DisabledExternalMarketDataAdapter:
    """Never contacts the internet and fails with a controlled disabled error."""

    source_code = "EXTERNAL_DISABLED"

    async def health_check(self) -> MarketDataHealth:
        return MarketDataHealth(
            status=MarketDataSourceStatus.DISABLED,
            checked_at=datetime.now(UTC),
            message="external provider is not configured",
        )

    async def list_instruments(
        self,
        exchange: str | None = None,
        market: str | None = None,
    ) -> list[ExternalInstrument]:
        del exchange, market
        raise MarketDataAdapterDisabledError("external market-data adapter is disabled")

    async def fetch_bars(
        self,
        symbols: list[str],
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        adjustment: AdjustmentType,
    ) -> AsyncIterator[ExternalMarketBar]:
        del symbols, timeframe, start, end, adjustment
        raise MarketDataAdapterDisabledError("external market-data adapter is disabled")
        yield  # pragma: no cover - preserves async-generator protocol
