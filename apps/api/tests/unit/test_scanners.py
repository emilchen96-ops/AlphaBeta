from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.scanners import (
    LimitUpPullbackScanner,
    ScannerContext,
    ScannerError,
    ScannerRegistry,
    VolumeAnomalyScanner,
    is_delisting_instrument,
    is_st_instrument,
    register_builtin_scanners,
)
from alphadesk_domain.strategy import StrategyBar


def instrument() -> Instrument:
    return Instrument(
        id=uuid4(),
        symbol="600000",
        exchange="SSE",
        market="CN",
        name="测试股票",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
    )


def bars(item: Instrument, closes: list[str], volumes: list[str]) -> list[StrategyBar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        StrategyBar(
            instrument_id=item.id,
            symbol=item.symbol,
            exchange=item.exchange,
            timeframe=MarketTimeframe.DAY_1,
            timestamp=start + timedelta(days=index),
            open=Decimal(close),
            high=Decimal(close) * Decimal("1.01"),
            low=Decimal(close) * Decimal("0.99"),
            close=Decimal(close),
            volume=Decimal(volume),
            amount=Decimal(close) * Decimal(volume),
        )
        for index, (close, volume) in enumerate(zip(closes, volumes, strict=True))
    ]


def context(latest: StrategyBar, parameters: dict[str, object]) -> ScannerContext:
    return ScannerContext(
        as_of=latest.timestamp,
        timeframe=MarketTimeframe.DAY_1,
        parameters=parameters,
    )


def test_volume_anomaly_excludes_current_bar_from_average() -> None:
    item = instrument()
    values = bars(item, ["10", "10", "10"], ["100", "100", "300"])
    candidate = VolumeAnomalyScanner().scan(
        context(values[-1], {"volume_window": 2, "minimum_volume_ratio": Decimal("2")}),
        item,
        values,
    )
    assert candidate is not None
    assert candidate.score == Decimal("3")
    assert candidate.metrics["average_volume"] == Decimal("1E+2")
    assert candidate.metrics["current_volume"] == Decimal("3E+2")


def test_volume_anomaly_requires_complete_history_and_applies_filters() -> None:
    item = instrument()
    values = bars(item, ["10", "11"], ["100", "500"])
    scanner = VolumeAnomalyScanner()
    assert scanner.scan(context(values[-1], {"volume_window": 2}), item, values) is None
    values = bars(item, ["10", "10", "11"], ["100", "100", "500"])
    assert (
        scanner.scan(
            context(
                values[-1],
                {
                    "volume_window": 2,
                    "minimum_amount": Decimal("999999"),
                },
            ),
            item,
            values,
        )
        is None
    )


def test_scanner_parameter_validation_rejects_float_and_unknown_parameter() -> None:
    scanner = VolumeAnomalyScanner()
    with pytest.raises(ScannerError, match="decimal string"):
        scanner.validate_parameters({"minimum_volume_ratio": 2.0})
    with pytest.raises(ScannerError, match="unknown scanner parameter"):
        scanner.validate_parameters({"mystery": 1})
    with pytest.raises(ScannerError, match="below its minimum"):
        LimitUpPullbackScanner().validate_parameters({"lookback_days": 1})


def test_limit_up_pullback_uses_previous_close_as_baseline() -> None:
    item = instrument()
    values = bars(
        item,
        ["10", "11", "10.70", "10.30", "10.20"],
        ["100", "500", "300", "200", "180"],
    )
    candidate = LimitUpPullbackScanner().scan(
        context(
            values[-1],
            {
                "lookback_days": 4,
                "limit_up_threshold": Decimal("0.095"),
                "baseline_tolerance": Decimal("0.05"),
                "minimum_days_after_limit_up": 2,
            },
        ),
        item,
        values,
    )
    assert candidate is not None
    assert candidate.metrics["baseline_price"] == Decimal("1E+1")
    assert candidate.metrics["days_since_limit_up"] == 3
    assert candidate.reason_code == "LIMIT_UP_PULLBACK_APPROXIMATION"
    assert "并非交易所权威" in candidate.reason


def test_limit_up_pullback_respects_distance_and_above_baseline() -> None:
    item = instrument()
    values = bars(item, ["10", "11", "10.5", "9.9"], ["100", "500", "200", "150"])
    scanner = LimitUpPullbackScanner()
    assert scanner.scan(context(values[-1], {}), item, values) is None
    candidate = scanner.scan(
        context(values[-1], {"require_current_above_baseline": False}), item, values
    )
    assert candidate is not None


def test_registry_returns_new_instances_in_stable_order() -> None:
    registry = ScannerRegistry()
    register_builtin_scanners(registry)
    assert [item.scanner_key for item in registry.list_metadata()] == [
        "limit_up_pullback",
        "volume_anomaly",
    ]
    assert registry.create("volume_anomaly") is not registry.create("volume_anomaly")


def test_special_treatment_classification_is_centralized() -> None:
    st = instrument()
    st.name = "*ST测试"
    assert is_st_instrument(st)
    st.name = "普通名称"
    st.metadata["is_st"] = True
    assert is_st_instrument(st)

    delisting = instrument()
    delisting.name = "退市测试"
    assert is_delisting_instrument(delisting)
    delisting.name = "普通名称"
    delisting.metadata["security_status"] = "DELISTING_CONSOLIDATION"
    assert is_delisting_instrument(delisting)
