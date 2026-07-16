from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from alphadesk_api.application.free_market_data import strict_decimal
from alphadesk_api.infrastructure.market_data.akshare_eastmoney import (
    AkShareEastMoneyRealtimeAdapter,
)
from alphadesk_api.infrastructure.market_data.baostock_historical import (
    BaoStockHistoricalMarketDataAdapter,
)
from alphadesk_api.infrastructure.provider_resilience import (
    ProviderCallGuard,
    ProviderCircuitOpenError,
)
from alphadesk_api.workers.free_market_data import is_cn_a_active_session
from alphadesk_domain.enums import (
    AdjustmentType,
    CircuitState,
    MarketDataQualityStatus,
    MarketTimeframe,
)
from alphadesk_domain.realtime_market import MarketQuote


async def direct_run_sync(function: Any, *args: Any) -> Any:
    return function(*args)


class FakeAkShareClient:
    def spot_records(self) -> list[dict[str, Any]]:
        return [
            {
                "代码": "600000",
                "名称": "浦发银行",
                "最新价": "10.25",
                "昨收": "10.00",
                "今开": "10.01",
                "最高": "10.30",
                "最低": "9.98",
                "成交量": "12300",
                "成交额": "126000.50",
            }
        ]

    def minute_records(self, symbol: str) -> list[dict[str, Any]]:
        assert symbol == "600000"
        return [
            {
                "时间": "2026-07-15 09:31:00",
                "开盘": "10.00",
                "收盘": "10.10",
                "最高": "10.12",
                "最低": "9.99",
                "成交量": "1000",
                "成交额": "10050",
            }
        ]


class FakeBaoStockClient:
    def health(self) -> tuple[bool, str]:
        return True, "success"

    def history(
        self, symbol: str, fields: str, start: str, end: str, frequency: str, adjustment: str
    ) -> list[dict[str, str]]:
        assert (symbol, frequency, adjustment) == ("sh.600000", "d", "3")
        assert "open" in fields and "time" not in fields and start <= end
        return [
            {
                "date": "2026-07-14",
                "time": "",
                "code": symbol,
                "open": "10.00",
                "high": "10.20",
                "low": "9.90",
                "close": "10.10",
                "volume": "1000",
                "amount": "10050",
            }
        ]


def test_strict_decimal_rejects_float_and_non_finite_values() -> None:
    assert strict_decimal("10.1250", "price") == Decimal("10.1250")
    with pytest.raises(ValueError, match="string"):
        strict_decimal(10.1, "price")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        strict_decimal("NaN", "price")


def test_market_quote_requires_decimal_and_does_not_invent_quote_time() -> None:
    quote = MarketQuote(
        instrument_id=uuid4(),
        source_code="akshare_eastmoney",
        symbol="600000",
        quote_time=None,
        received_at=datetime.now(UTC),
        last_price=Decimal("10.25"),
        quality_status=MarketDataQualityStatus.INCOMPLETE,
        quality_flags={"MISSING_UPSTREAM_QUOTE_TIME": True},
    )
    assert quote.quote_time is None
    assert quote.source_code == "AKSHARE_EASTMONEY"
    with pytest.raises(TypeError, match="Decimal"):
        MarketQuote(
            instrument_id=uuid4(),
            source_code="TEST",
            symbol="1",
            quote_time=None,
            received_at=datetime.now(UTC),
            last_price=10.25,  # type: ignore[arg-type]
        )


def test_cn_a_session_excludes_lunch_and_weekends() -> None:
    assert is_cn_a_active_session(datetime(2026, 7, 15, 1, 30, tzinfo=UTC))
    assert not is_cn_a_active_session(datetime(2026, 7, 15, 3, 30, tzinfo=UTC))
    assert is_cn_a_active_session(datetime(2026, 7, 15, 5, 0, tzinfo=UTC))
    assert not is_cn_a_active_session(datetime(2026, 7, 18, 1, 30, tzinfo=UTC))


@pytest.mark.asyncio
async def test_akshare_adapter_maps_snapshot_and_recent_minute_bar() -> None:
    adapter = AkShareEastMoneyRealtimeAdapter(FakeAkShareClient(), direct_run_sync)
    quotes = await adapter.fetch_quotes(["600000"])
    assert len(quotes) == 1
    assert quotes[0].last_price == "10.25"
    assert quotes[0].quote_time is None
    instruments = await adapter.list_instruments()
    assert instruments[0].exchange == "SSE"
    start = datetime(2026, 7, 15, 1, 30, tzinfo=UTC)
    bars = [
        item
        async for item in adapter.fetch_bars(
            ["600000"],
            MarketTimeframe.MINUTE_1,
            start,
            start + timedelta(minutes=2),
            AdjustmentType.NONE,
        )
    ]
    assert bars[0].bar_time == datetime(2026, 7, 15, 1, 31, tzinfo=UTC)
    assert bars[0].close == "10.10"


@pytest.mark.asyncio
async def test_baostock_adapter_maps_daily_history_without_float_conversion() -> None:
    adapter = BaoStockHistoricalMarketDataAdapter(FakeBaoStockClient(), direct_run_sync)
    bars = [
        item
        async for item in adapter.fetch_bars(
            ["600000"],
            MarketTimeframe.DAY_1,
            datetime(2026, 7, 14, tzinfo=UTC),
            datetime(2026, 7, 15, tzinfo=UTC),
            AdjustmentType.NONE,
        )
    ]
    assert bars[0].bar_time == datetime(2026, 7, 14, tzinfo=UTC)
    assert bars[0].amount == "10050"


@pytest.mark.asyncio
async def test_provider_guard_opens_after_threshold() -> None:
    guard = ProviderCallGuard(
        min_interval_seconds=0,
        max_retries=0,
        failure_threshold=2,
        open_seconds=600,
    )

    async def fail() -> None:
        raise RuntimeError("provider failed")

    with pytest.raises(RuntimeError):
        await guard.call(fail)
    with pytest.raises(RuntimeError):
        await guard.call(fail)
    assert guard.state is CircuitState.OPEN
    with pytest.raises(ProviderCircuitOpenError):
        await guard.call(fail)
