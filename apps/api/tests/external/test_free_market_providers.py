import os

import pytest

from alphadesk_api.infrastructure.market_data import (
    AkShareEastMoneyRealtimeAdapter,
    BaoStockHistoricalMarketDataAdapter,
)
from alphadesk_domain.enums import MarketDataSourceStatus

pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        os.getenv("ALPHADESK_EXTERNAL_FREE_MARKET_TESTS") != "true",
        reason="external provider tests require explicit opt-in",
    ),
]


@pytest.mark.asyncio
async def test_akshare_eastmoney_returns_a_share_snapshot() -> None:
    adapter = AkShareEastMoneyRealtimeAdapter()
    quotes = await adapter.fetch_quotes(["600000", "000001"])
    assert quotes
    assert all(item.last_price and item.symbol in {"600000", "000001"} for item in quotes)


@pytest.mark.asyncio
async def test_baostock_login_health() -> None:
    health = await BaoStockHistoricalMarketDataAdapter().health_check()
    assert health.status is MarketDataSourceStatus.ACTIVE, health.message
