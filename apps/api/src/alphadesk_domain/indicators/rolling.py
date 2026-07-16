"""Incremental rolling indicators with no infrastructure dependencies."""

from __future__ import annotations

from collections import deque
from decimal import Decimal


def _window(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("window must be a positive integer")
    return value


def _decimal(value: Decimal, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    return value


class SimpleMovingAverage:
    """Arithmetic mean of the most recent ``window`` values."""

    def __init__(self, window: int) -> None:
        self.window = _window(window)
        self._values: deque[Decimal] = deque()
        self._sum = Decimal("0")

    @property
    def is_ready(self) -> bool:
        return len(self._values) == self.window

    @property
    def value(self) -> Decimal | None:
        return self._sum / Decimal(self.window) if self.is_ready else None

    def update(self, value: Decimal) -> Decimal | None:
        value = _decimal(value, "value")
        if len(self._values) == self.window:
            self._sum -= self._values.popleft()
        self._values.append(value)
        self._sum += value
        return self.value

    def reset(self) -> None:
        self._values.clear()
        self._sum = Decimal("0")


class ExponentialMovingAverage:
    """EMA seeded by an SMA, then updated with alpha = 2 / (window + 1)."""

    def __init__(self, window: int) -> None:
        self.window = _window(window)
        self._alpha = Decimal("2") / Decimal(self.window + 1)
        self._seed: deque[Decimal] = deque()
        self._ema: Decimal | None = None

    @property
    def is_ready(self) -> bool:
        return self._ema is not None

    @property
    def value(self) -> Decimal | None:
        return self._ema

    def update(self, value: Decimal) -> Decimal | None:
        value = _decimal(value, "value")
        if self._ema is None:
            self._seed.append(value)
            if len(self._seed) == self.window:
                self._ema = sum(self._seed, Decimal("0")) / Decimal(self.window)
                self._seed.clear()
        else:
            self._ema = self._alpha * value + (Decimal("1") - self._alpha) * self._ema
        return self.value

    def reset(self) -> None:
        self._seed.clear()
        self._ema = None


class _RollingExtreme:
    def __init__(self, window: int) -> None:
        self.window = _window(window)
        self._values: deque[Decimal] = deque()

    @property
    def is_ready(self) -> bool:
        return len(self._values) == self.window

    def update(self, value: Decimal) -> Decimal | None:
        value = _decimal(value, "value")
        if len(self._values) == self.window:
            self._values.popleft()
        self._values.append(value)
        return self.value

    def reset(self) -> None:
        self._values.clear()

    @property
    def value(self) -> Decimal | None:
        raise NotImplementedError


class RollingHighest(_RollingExtreme):
    """Highest value in the current window; call order controls current-bar inclusion."""

    @property
    def value(self) -> Decimal | None:
        return max(self._values) if self.is_ready else None


class RollingLowest(_RollingExtreme):
    """Lowest value in the current window; call order controls current-bar inclusion."""

    @property
    def value(self) -> Decimal | None:
        return min(self._values) if self.is_ready else None


class AverageTrueRange:
    """Wilder ATR seeded by the mean of the first ``window`` true ranges."""

    def __init__(self, window: int) -> None:
        self.window = _window(window)
        self._true_ranges: deque[Decimal] = deque()
        self._previous_close: Decimal | None = None
        self._atr: Decimal | None = None

    @property
    def is_ready(self) -> bool:
        return self._atr is not None

    @property
    def value(self) -> Decimal | None:
        return self._atr

    def update(self, high: Decimal, low: Decimal, close: Decimal) -> Decimal | None:
        high = _decimal(high, "high")
        low = _decimal(low, "low")
        close = _decimal(close, "close")
        if high < low:
            raise ValueError("high must not be below low")
        true_range = high - low
        if self._previous_close is not None:
            true_range = max(
                true_range,
                abs(high - self._previous_close),
                abs(low - self._previous_close),
            )
        self._previous_close = close
        if self._atr is None:
            self._true_ranges.append(true_range)
            if len(self._true_ranges) == self.window:
                self._atr = sum(self._true_ranges, Decimal("0")) / Decimal(self.window)
                self._true_ranges.clear()
        else:
            self._atr = (self._atr * Decimal(self.window - 1) + true_range) / Decimal(self.window)
        return self.value

    def reset(self) -> None:
        self._true_ranges.clear()
        self._previous_close = None
        self._atr = None


class RollingAverageVolume(SimpleMovingAverage):
    """Arithmetic average of non-negative Decimal volume observations."""

    def update(self, value: Decimal) -> Decimal | None:
        value = _decimal(value, "volume")
        if value < 0:
            raise ValueError("volume must be non-negative")
        return super().update(value)
