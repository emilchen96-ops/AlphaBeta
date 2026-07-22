from datetime import date, timedelta
from time import perf_counter
from tracemalloc import get_traced_memory, start, stop

import pytest

from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.intraday import IntradayBarAggregator, IntradaySessionTemplate
from tests.unit.test_intraday_domain import minute_bar


@pytest.mark.unit
@pytest.mark.d03
def test_ten_thousand_bar_aggregation_stays_bounded() -> None:
    template = IntradaySessionTemplate()
    bars = []
    session_date = date(2026, 1, 5)
    while len(bars) < 10_000:
        if session_date.weekday() < 5:
            bars.extend(
                minute_bar(timestamp, index)
                for index, timestamp in enumerate(
                    template.expected_starts(session_date, MarketTimeframe.MINUTE_1)
                )
            )
        session_date += timedelta(days=1)
    bars = bars[:10_000]
    start()
    started = perf_counter()
    result = IntradayBarAggregator().aggregate(bars, MarketTimeframe.MINUTE_5)
    elapsed = perf_counter() - started
    _, peak = get_traced_memory()
    stop()
    print(
        {
            "input_bars": len(bars),
            "output_bars": len(result.bars),
            "elapsed_seconds": round(elapsed, 4),
            "peak_bytes": peak,
        }
    )
    assert len(result.bars) >= 1_990
    assert elapsed < 5
    assert peak < 100 * 1024 * 1024
