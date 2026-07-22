from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_domain.enums import AdjustmentType, MarketDataQualityStatus, MarketTimeframe
from alphadesk_domain.intraday import (
    AGGREGATION_VERSION,
    INTRADAY_QUALITY_ISSUE_TYPES,
    IntradayAggregationIntegrityService,
    IntradayBarAggregator,
    IntradaySessionTemplate,
)
from alphadesk_domain.market import MarketBar


def minute_bar(at: datetime, index: int = 0) -> MarketBar:
    price = Decimal("10") + Decimal(index) / Decimal("100")
    return MarketBar(
        instrument_id=INSTRUMENT_ID,
        source_id=SOURCE_ID,
        timeframe=MarketTimeframe.MINUTE_1,
        adjustment_type=AdjustmentType.NONE,
        bar_time=at,
        open=price,
        high=price + Decimal("0.02"),
        low=price - Decimal("0.01"),
        close=price + Decimal("0.01"),
        volume=Decimal("100"),
        amount=Decimal("1000"),
        received_at=datetime(2026, 7, 20, tzinfo=UTC),
        quality_status=MarketDataQualityStatus.NORMAL,
    )


INSTRUMENT_ID = uuid4()
SOURCE_ID = uuid4()


@pytest.mark.unit
def test_session_timezone_boundaries_and_expected_counts() -> None:
    template = IntradaySessionTemplate()
    assert template.normalize(datetime(2026, 7, 6, 9, 30), "Asia/Shanghai") == datetime(
        2026, 7, 6, 1, 30, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="INTRADAY_TIMEZONE_REQUIRED"):
        template.normalize(datetime(2026, 7, 6, 9, 30))
    for hour, minute, valid in (
        (9, 30, True),
        (11, 29, True),
        (11, 30, False),
        (12, 0, False),
        (13, 0, True),
        (14, 59, True),
        (15, 0, False),
    ):
        value = datetime(2026, 7, 6, hour - 8, minute, tzinfo=UTC)
        assert template.validate_bar_start(value, MarketTimeframe.MINUTE_1) is valid
    assert [
        template.expected_count(value)
        for value in MarketTimeframe
        if value.value.startswith("MINUTE_")
    ] == [240, 48, 16, 8, 4]
    assert len(INTRADAY_QUALITY_ISSUE_TYPES) == 14


@pytest.mark.unit
@pytest.mark.parametrize(
    ("target", "count"),
    [
        (MarketTimeframe.MINUTE_5, 48),
        (MarketTimeframe.MINUTE_15, 16),
        (MarketTimeframe.MINUTE_30, 8),
        (MarketTimeframe.MINUTE_60, 4),
    ],
)
def test_aggregation_is_session_anchored_and_deterministic(
    target: MarketTimeframe, count: int
) -> None:
    starts = IntradaySessionTemplate().expected_starts(date(2026, 7, 6), MarketTimeframe.MINUTE_1)
    source = [minute_bar(value, index) for index, value in enumerate(starts)]
    result = IntradayBarAggregator().aggregate(reversed(source), target)
    assert len(result.bars) == count
    assert not result.incomplete_windows
    assert result.bars[0].bar_time == datetime(2026, 7, 6, 1, 30, tzinfo=UTC)
    assert result.bars[count // 2].bar_time == datetime(2026, 7, 6, 5, 0, tzinfo=UTC)
    assert result.bars[0].quality_flags["aggregation_version"] == AGGREGATION_VERSION


@pytest.mark.unit
def test_strict_window_skips_missing_input_and_integrity_reports_mismatch() -> None:
    start = datetime(2026, 7, 6, 1, 30, tzinfo=UTC)
    source = [minute_bar(start + timedelta(minutes=index), index) for index in range(5)]
    partial = IntradayBarAggregator().aggregate(source[:-1], MarketTimeframe.MINUTE_5)
    assert not partial.bars
    assert partial.incomplete_windows == (start,)
    complete = IntradayBarAggregator().aggregate(source, MarketTimeframe.MINUTE_5)
    changed = complete.bars[0]
    changed.close += Decimal("1")
    mismatch = IntradayAggregationIntegrityService().compare(
        source, [changed], MarketTimeframe.MINUTE_5
    )
    assert mismatch[0].fields == ("close",)
