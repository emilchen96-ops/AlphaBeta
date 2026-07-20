from datetime import UTC, datetime
from uuid import uuid4

import pytest

from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataQualityStatus,
    MarketDataReadinessStatus,
)
from alphadesk_domain.strategy_runs import HistoricalDataReadiness

pytestmark = pytest.mark.unit


def test_historical_readiness_normalizes_deterministic_authority_contract() -> None:
    missing = uuid4()
    readiness = HistoricalDataReadiness(
        status=MarketDataReadinessStatus.PARTIAL,
        source_code="baostock",
        adjustment_type=AdjustmentType.NONE,
        accepted_quality_statuses=(
            MarketDataQualityStatus.NORMAL,
            MarketDataQualityStatus.NORMAL,
        ),
        requested_instrument_count=2,
        ready_instrument_count=1,
        minimum_bars_per_instrument=20,
        total_bar_count=25,
        missing_instrument_ids=(missing,),
        earliest_bar=datetime(2025, 1, 1, tzinfo=UTC),
        latest_bar=datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert readiness.source_code == "BAOSTOCK"
    assert readiness.accepted_quality_statuses == (MarketDataQualityStatus.NORMAL,)
    assert readiness.missing_instrument_ids == (missing,)


def test_historical_readiness_rejects_inconsistent_missing_count() -> None:
    with pytest.raises(ValueError, match="missing instruments"):
        HistoricalDataReadiness(
            status=MarketDataReadinessStatus.PARTIAL,
            source_code="BAOSTOCK",
            adjustment_type=AdjustmentType.NONE,
            accepted_quality_statuses=(MarketDataQualityStatus.NORMAL,),
            requested_instrument_count=2,
            ready_instrument_count=1,
            minimum_bars_per_instrument=1,
            total_bar_count=1,
            missing_instrument_ids=(),
        )
