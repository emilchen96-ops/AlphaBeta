from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketSyncStatus,
    MarketTimeframe,
    SyncTriggerType,
)
from alphadesk_domain.market import MarketBar, MarketDataSource, MarketSyncRun


def bar(**overrides: object) -> MarketBar:
    values: dict[str, object] = {
        "instrument_id": uuid4(),
        "source_id": uuid4(),
        "timeframe": MarketTimeframe.DAY_1,
        "adjustment_type": AdjustmentType.NONE,
        "bar_time": datetime(2025, 1, 1, tzinfo=UTC),
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10.5"),
        "volume": Decimal("100"),
        "received_at": datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
        "quality_status": MarketDataQualityStatus.NORMAL,
    }
    values.update(overrides)
    return MarketBar(**values)  # type: ignore[arg-type]


def test_source_normalizes_code_and_requires_timeframes() -> None:
    source = MarketDataSource(
        source_code="demo",
        name="Demo",
        status=MarketDataSourceStatus.ACTIVE,
        priority=0,
        supports_realtime=False,
        supported_timeframes=(MarketTimeframe.DAY_1,),
    )
    assert source.source_code == "DEMO"
    with pytest.raises(ValueError, match="supported_timeframes"):
        MarketDataSource(
            source_code="EMPTY",
            name="Empty",
            status=MarketDataSourceStatus.DISABLED,
            priority=0,
            supports_realtime=False,
            supported_timeframes=(),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("open", Decimal("0"), "positive"),
        ("high", Decimal("9"), "high"),
        ("low", Decimal("11"), "low"),
        ("volume", Decimal("-1"), "non-negative"),
        ("amount", Decimal("-1"), "non-negative"),
        ("vwap", Decimal("0"), "positive"),
        ("open_interest", Decimal("-1"), "non-negative"),
    ],
)
def test_market_bar_numeric_invariants(field: str, value: Decimal, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        bar(**{field: value})


def test_market_bar_requires_aware_and_aligned_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        bar(bar_time=datetime(2025, 1, 1))
    with pytest.raises(ValueError, match="UTC midnight"):
        bar(bar_time=datetime(2025, 1, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="align to a minute"):
        bar(
            timeframe=MarketTimeframe.MINUTE_1,
            bar_time=datetime(2025, 1, 1, 1, 30, 1, tzinfo=UTC),
        )


def test_sync_run_rejects_bad_counters_and_completion() -> None:
    started = datetime.now(UTC)
    base = {
        "source_id": uuid4(),
        "trigger_type": SyncTriggerType.CLI,
        "status": MarketSyncStatus.FAILED,
        "timeframe": MarketTimeframe.DAY_1,
        "adjustment_type": AdjustmentType.NONE,
        "requested_symbols": ("600000",),
        "started_at": started,
        "correlation_id": uuid4(),
    }
    with pytest.raises(ValueError, match="non-negative"):
        MarketSyncRun(**base, total_rejected=-1)
    with pytest.raises(ValueError, match="must not precede"):
        MarketSyncRun(**base, completed_at=started - timedelta(seconds=1))
    with pytest.raises(ValueError, match="1000"):
        MarketSyncRun(**base, error_summary="x" * 1001)
