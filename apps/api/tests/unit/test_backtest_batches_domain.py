from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_api.application.backtest_batches import _distribution, _histogram
from alphadesk_domain.backtest_batches import (
    BacktestBatch,
    BacktestBatchScope,
)


def test_batch_progress_counts_terminal_items_only() -> None:
    batch = BacktestBatch(
        idempotency_key="batch:test",
        request_fingerprint="a" * 64,
        scope=BacktestBatchScope.ALL_A_SHARES,
        name="全A股批量独立回测",
        configuration={"schema_version": 1},
        total_count=10,
        pending_count=4,
        running_count=1,
        completed_count=3,
        failed_count=2,
    )

    assert batch.progress_percent == 50


def test_watchlist_batch_requires_watchlist_id() -> None:
    with pytest.raises(ValueError, match="watchlist_id"):
        BacktestBatch(
            idempotency_key="batch:test",
            request_fingerprint="b" * 64,
            scope=BacktestBatchScope.WATCHLIST,
            name="自选组合独立回测",
            configuration={"schema_version": 1},
            total_count=1,
            pending_count=1,
        )


def test_watchlist_batch_accepts_consistent_counters() -> None:
    batch = BacktestBatch(
        idempotency_key="batch:test",
        request_fingerprint="c" * 64,
        scope=BacktestBatchScope.WATCHLIST,
        watchlist_id=uuid4(),
        name="自选组合独立回测",
        configuration={"schema_version": 1},
        total_count=2,
        pending_count=2,
    )

    assert batch.total_count == 2


def test_batch_summary_distribution_handles_zero_and_failed_only_samples() -> None:
    assert _distribution([])["count"] == 0
    assert _distribution([])["average"] is None
    assert _histogram([], 8) == []


def test_batch_summary_distribution_reports_percentiles_and_histogram() -> None:
    distribution = _distribution([Decimal("-0.2"), Decimal("0"), Decimal("0.1"), Decimal("0.5")])
    histogram = _histogram([-0.2, 0.0, 0.1, 0.5], 4)

    assert distribution["average"] == "0.1"
    assert distribution["p50"] == "0.05"
    assert sum(int(item["count"]) for item in histogram) == 4
