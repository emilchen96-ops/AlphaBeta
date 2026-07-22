import asyncio
from pathlib import Path

import pytest

from alphadesk_api.infrastructure.intraday_provider import (
    LocalFileIntradayMarketDataProvider,
)
from alphadesk_domain.enums import MarketTimeframe


def write_csv(path: Path, timestamp: str = "2026-07-06T09:30:00") -> None:
    path.write_text(
        "symbol,exchange,timestamp,timeframe,open,high,low,close,volume,amount\n"
        f"600000,SSE,{timestamp},1m,10,10.1,9.9,10.05,100,1005\n",
        encoding="utf-8",
    )


async def collect(provider: LocalFileIntradayMarketDataProvider):
    return [item async for item in provider.fetch_bars()]


@pytest.mark.unit
def test_local_csv_streams_decimal_strings_and_applies_explicit_timezone(tmp_path: Path) -> None:
    path = tmp_path / "bars.csv"
    write_csv(path)
    provider = LocalFileIntradayMarketDataProvider(
        path,
        source_timezone="Asia/Shanghai",
        max_bytes=10_000,
        max_rows=10,
        allowed_root=tmp_path,
    )
    rows = asyncio.run(collect(provider))
    assert rows[0].timeframe is MarketTimeframe.MINUTE_1
    assert rows[0].timestamp.isoformat() == "2026-07-06T09:30:00+08:00"
    assert rows[0].open == "10"


@pytest.mark.unit
def test_local_csv_requires_timezone_for_naive_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "bars.csv"
    write_csv(path)
    provider = LocalFileIntradayMarketDataProvider(
        path,
        source_timezone=None,
        max_bytes=10_000,
        max_rows=10,
        allowed_root=tmp_path,
    )
    with pytest.raises(ValueError, match="INTRADAY_TIMEZONE_REQUIRED"):
        asyncio.run(collect(provider))


@pytest.mark.unit
def test_local_file_rejects_parquet_size_and_path_escape(tmp_path: Path) -> None:
    parquet = tmp_path / "bars.parquet"
    parquet.write_bytes(b"PAR1")
    with pytest.raises(ValueError, match="INTRADAY_FILE_FORMAT_NOT_SUPPORTED"):
        LocalFileIntradayMarketDataProvider(
            parquet,
            source_timezone="Asia/Shanghai",
            max_bytes=10_000,
            max_rows=10,
            allowed_root=tmp_path,
        )
    csv_path = tmp_path / "large.csv"
    write_csv(csv_path)
    with pytest.raises(ValueError, match="INTRADAY_FILE_TOO_LARGE"):
        LocalFileIntradayMarketDataProvider(
            csv_path,
            source_timezone="Asia/Shanghai",
            max_bytes=10,
            max_rows=10,
            allowed_root=tmp_path,
        )
    outside = tmp_path.parent / "outside.csv"
    write_csv(outside)
    try:
        with pytest.raises(ValueError, match="INTRADAY_FILE_NOT_FOUND"):
            LocalFileIntradayMarketDataProvider(
                outside,
                source_timezone="Asia/Shanghai",
                max_bytes=10_000,
                max_rows=10,
                allowed_root=tmp_path,
            )
    finally:
        outside.unlink()
