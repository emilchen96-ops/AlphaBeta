from decimal import Decimal

import pytest

from alphadesk_domain.indicators import (
    AverageTrueRange,
    ExponentialMovingAverage,
    RollingAverageVolume,
    RollingHighest,
    RollingLowest,
    SimpleMovingAverage,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("window", (0, -1, True, Decimal("2")))
@pytest.mark.parametrize(
    "indicator_type",
    (SimpleMovingAverage, ExponentialMovingAverage, RollingHighest, RollingLowest),
)
def test_indicators_reject_invalid_windows(indicator_type, window) -> None:
    with pytest.raises(ValueError):
        indicator_type(window)


def test_sma_readiness_rolling_update_and_reset() -> None:
    indicator = SimpleMovingAverage(3)
    assert indicator.update(Decimal("1")) is None
    assert indicator.update(Decimal("2")) is None
    assert indicator.update(Decimal("3")) == Decimal("2")
    assert indicator.update(Decimal("6")) == Decimal("11") / Decimal("3")
    indicator.reset()
    assert not indicator.is_ready and indicator.value is None


def test_ema_uses_sma_seed_and_decimal_recurrence() -> None:
    indicator = ExponentialMovingAverage(3)
    assert [indicator.update(Decimal(value)) for value in ("1", "2", "3")] == [
        None,
        None,
        Decimal("2"),
    ]
    assert indicator.update(Decimal("4")) == Decimal("3")


def test_ema_reset_restores_seed_phase() -> None:
    indicator = ExponentialMovingAverage(2)
    indicator.update(Decimal("2"))
    indicator.update(Decimal("4"))
    indicator.reset()
    assert indicator.update(Decimal("10")) is None


def test_rolling_extremes_and_call_order_exclude_current_value() -> None:
    highest, lowest = RollingHighest(2), RollingLowest(2)
    for value in (Decimal("3"), Decimal("5")):
        highest.update(value)
        lowest.update(value)
    assert highest.value == Decimal("5") and lowest.value == Decimal("3")
    prior_high = highest.value
    assert Decimal("6") > prior_high
    highest.update(Decimal("6"))
    assert highest.value == Decimal("6")


def test_atr_true_range_seed_and_wilder_recurrence() -> None:
    indicator = AverageTrueRange(2)
    assert indicator.update(Decimal("11"), Decimal("9"), Decimal("10")) is None
    assert indicator.update(Decimal("13"), Decimal("12"), Decimal("12")) == Decimal("2.5")
    assert indicator.update(Decimal("15"), Decimal("14"), Decimal("14")) == Decimal("2.75")


def test_atr_validates_range_and_reset() -> None:
    indicator = AverageTrueRange(2)
    with pytest.raises(ValueError, match="high"):
        indicator.update(Decimal("1"), Decimal("2"), Decimal("1.5"))
    indicator.update(Decimal("2"), Decimal("1"), Decimal("1.5"))
    indicator.reset()
    assert indicator.value is None and not indicator.is_ready


def test_average_volume_requires_non_negative_decimal() -> None:
    indicator = RollingAverageVolume(2)
    assert indicator.update(Decimal("100")) is None
    assert indicator.update(Decimal("200")) == Decimal("150")
    with pytest.raises(ValueError, match="non-negative"):
        indicator.update(Decimal("-1"))


@pytest.mark.parametrize("bad", (1, 1.0, Decimal("NaN")))
def test_indicators_never_coerce_non_decimal_or_non_finite_inputs(bad) -> None:
    indicator = SimpleMovingAverage(2)
    with pytest.raises((TypeError, ValueError)):
        indicator.update(bad)


def test_same_decimal_inputs_are_deterministic() -> None:
    first, second = ExponentialMovingAverage(3), ExponentialMovingAverage(3)
    values = [Decimal(value) for value in ("1.1", "2.2", "3.3", "4.4")]
    assert [first.update(value) for value in values] == [second.update(value) for value in values]
