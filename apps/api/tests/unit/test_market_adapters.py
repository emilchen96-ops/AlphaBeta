from datetime import UTC, datetime
from pathlib import Path

import pytest

from alphadesk_api.infrastructure.market_data import (
    DemoCsvMarketDataAdapter,
    DisabledExternalMarketDataAdapter,
    LocalCsvMarketDataAdapter,
)
from alphadesk_domain.enums import AdjustmentType, MarketDataSourceStatus, MarketTimeframe
from alphadesk_domain.market_adapters import (
    MarketDataAdapterDisabledError,
    MarketDataAdapterTimeframeError,
)


async def collect_demo() -> list[object]:
    adapter = DemoCsvMarketDataAdapter()
    return [
        item
        async for item in adapter.fetch_bars(
            ["600000"],
            MarketTimeframe.DAY_1,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 3, tzinfo=UTC),
            AdjustmentType.NONE,
        )
    ]


@pytest.mark.asyncio
async def test_demo_adapter_is_deterministic_and_offline() -> None:
    first = await collect_demo()
    second = await collect_demo()
    assert first == second
    assert len(first) == 3
    health = await DemoCsvMarketDataAdapter().health_check()
    assert health.status is MarketDataSourceStatus.ACTIVE


@pytest.mark.asyncio
async def test_demo_rejects_unsupported_timeframe() -> None:
    adapter = DemoCsvMarketDataAdapter()
    with pytest.raises(MarketDataAdapterTimeframeError):
        _ = [
            item
            async for item in adapter.fetch_bars(
                ["600000"],
                MarketTimeframe.WEEK_1,
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 2, tzinfo=UTC),
                AdjustmentType.NONE,
            )
        ]


@pytest.mark.asyncio
async def test_external_adapter_is_controlled_disabled() -> None:
    adapter = DisabledExternalMarketDataAdapter()
    assert (await adapter.health_check()).status is MarketDataSourceStatus.DISABLED
    with pytest.raises(MarketDataAdapterDisabledError):
        await adapter.list_instruments()


def test_csv_rejects_remote_and_oversized_paths(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ValueError)):
        LocalCsvMarketDataAdapter(
            Path("https://example.invalid/bars.csv"),
            source_code="DEMO",
            timeframe=MarketTimeframe.DAY_1,
            max_bytes=100,
            max_rows=10,
        )
    path = tmp_path / "large.csv"
    path.write_text("x" * 101, encoding="utf-8")
    with pytest.raises(ValueError, match="byte limit"):
        LocalCsvMarketDataAdapter(
            path,
            source_code="DEMO",
            timeframe=MarketTimeframe.DAY_1,
            max_bytes=100,
            max_rows=10,
        )


@pytest.mark.asyncio
async def test_csv_reads_bounded_valid_rows(tmp_path: Path) -> None:
    path = tmp_path / "bars.csv"
    path.write_text(
        "symbol,bar_time,open,high,low,close,volume\n"
        "600000,2025-01-01T00:00:00+00:00,10,11,9,10.5,100\n",
        encoding="utf-8",
    )
    adapter = LocalCsvMarketDataAdapter(
        path,
        source_code="DEMO",
        timeframe=MarketTimeframe.DAY_1,
        max_bytes=1000,
        max_rows=10,
    )
    values = [
        item
        async for item in adapter.fetch_bars(
            ["600000"],
            MarketTimeframe.DAY_1,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            AdjustmentType.NONE,
        )
    ]
    assert adapter.symbols == ["600000"]
    assert len(values) == 1
