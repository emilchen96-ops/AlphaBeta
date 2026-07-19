from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from alphadesk_api.cli.market_data import (
    build_parser,
    daily_timeframe,
    date_or_datetime,
    read_symbol_file,
)
from alphadesk_api.infrastructure.market_data.baostock_historical import (
    BaoStockHistoricalMarketDataAdapter,
)
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_adapters import MarketDataAdapterError


async def direct_run_sync(function: Any, *args: Any) -> Any:
    return function(*args)


class InstrumentClient:
    def health(self) -> tuple[bool, str]:
        return True, "ok"

    def instruments(self) -> list[dict[str, str]]:
        return [
            {
                "code": "sh.600000",
                "code_name": "浦发银行",
                "ipoDate": "1999-11-10",
                "outDate": "",
                "type": "1",
                "status": "1",
            },
            {
                "code": "sz.000001",
                "code_name": "平安银行",
                "ipoDate": "1991-04-03",
                "outDate": "2020-01-01",
                "type": "1",
                "status": "0",
            },
            {"code": "sh.000001", "code_name": "上证指数", "type": "2", "status": "1"},
            {"code": "hk.00700", "code_name": "腾讯", "type": "1", "status": "1"},
        ]

    def history(
        self, symbol: str, fields: str, start: str, end: str, frequency: str, adjustment: str
    ) -> list[dict[str, str]]:
        del symbol, fields, start, end, frequency, adjustment
        return []


class FailingInstrumentClient(InstrumentClient):
    def instruments(self) -> list[dict[str, str]]:
        raise TimeoutError("secret upstream text")


@pytest.mark.asyncio
async def test_baostock_instrument_catalog_filters_non_a_share_and_maps_status() -> None:
    adapter = BaoStockHistoricalMarketDataAdapter(InstrumentClient(), direct_run_sync)
    values = await adapter.list_instruments(market="CN_A")
    assert [(item.exchange, item.symbol) for item in values] == [
        ("SSE", "600000"),
        ("SZSE", "000001"),
    ]
    assert values[0].is_active is True
    assert values[1].is_active is False
    assert values[0].metadata == {
        "provider_code": "sh.600000",
        "ipo_date": "1999-11-10",
        "out_date": None,
        "provider_status": "1",
    }


@pytest.mark.asyncio
async def test_baostock_instrument_catalog_honors_exchange_filter() -> None:
    adapter = BaoStockHistoricalMarketDataAdapter(InstrumentClient(), direct_run_sync)
    values = await adapter.list_instruments(exchange="SZSE")
    assert [item.symbol for item in values] == ["000001"]


@pytest.mark.asyncio
async def test_baostock_instrument_error_is_controlled_and_does_not_leak_message() -> None:
    adapter = BaoStockHistoricalMarketDataAdapter(FailingInstrumentClient(), direct_run_sync)
    with pytest.raises(MarketDataAdapterError, match="TimeoutError") as captured:
        await adapter.list_instruments()
    assert "secret upstream text" not in str(captured.value)


@pytest.mark.parametrize("value", ["DAY", "day", "DAY_1"])
def test_daily_timeframe_accepts_day_aliases(value: str) -> None:
    assert daily_timeframe(value) is MarketTimeframe.DAY_1


def test_daily_timeframe_rejects_minute() -> None:
    with pytest.raises(Exception, match="DAY"):
        daily_timeframe("MINUTE_1")


def test_date_or_datetime_normalizes_dates_and_offsets() -> None:
    assert date_or_datetime("2026-01-02") == datetime(2026, 1, 2, tzinfo=UTC)
    assert date_or_datetime("2026-01-02T08:00:00+08:00") == datetime(2026, 1, 2, tzinfo=UTC)


def test_code_file_accepts_lines_commas_and_provider_codes(tmp_path: Path) -> None:
    path = tmp_path / "codes.txt"
    path.write_text("600000, sz.000001\n300001\n", encoding="utf-8")
    assert read_symbol_file(str(path)) == {"600000", "sz.000001", "300001"}


def test_code_file_rejects_missing_or_empty_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        read_symbol_file(str(tmp_path / "missing.txt"))
    empty = tmp_path / "empty.txt"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="1 to 10000"):
        read_symbol_file(str(empty))


def test_cli_exposes_d01_commands_and_bounded_defaults() -> None:
    parser = build_parser()
    sync = parser.parse_args(["sync-instruments", "--provider", "baostock", "--dry-run"])
    assert sync.provider == "baostock" and sync.dry_run is True
    universe = parser.parse_args(["create-research-universe"])
    assert universe.limit == 300
    backfill = parser.parse_args(["backfill", "--start", "2025-01-01", "--timeframe", "DAY"])
    assert backfill.limit == 300
    assert backfill.max_retries is None
    assert backfill.continue_on_error is True
