"""Async provider rate limit, retry and circuit-breaker primitives."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from alphadesk_domain.enums import CircuitState

T = TypeVar("T")


class ProviderCircuitOpenError(RuntimeError):
    pass


class ProviderCallGuard:
    def __init__(
        self,
        *,
        min_interval_seconds: float = 5,
        max_retries: int = 2,
        failure_threshold: int = 5,
        open_seconds: int = 600,
        random_source: random.Random | None = None,
    ) -> None:
        self._semaphore = asyncio.Semaphore(1)
        self._min_interval = min_interval_seconds
        self._max_retries = max_retries
        self._failure_threshold = failure_threshold
        self._open_duration = timedelta(seconds=open_seconds)
        self._random = random_source or random.Random()
        self._last_started = 0.0
        self._failures = 0
        self._opened_at: datetime | None = None
        self._state = CircuitState.CLOSED
        self._half_open_in_flight = False

    @property
    def state(self) -> CircuitState:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and datetime.now(UTC) - self._opened_at >= self._open_duration
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._failures

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        state = self.state
        if state is CircuitState.OPEN or (
            state is CircuitState.HALF_OPEN and self._half_open_in_flight
        ):
            raise ProviderCircuitOpenError("provider circuit is open")
        if state is CircuitState.HALF_OPEN:
            self._half_open_in_flight = True
        try:
            async with self._semaphore:
                for attempt in range(self._max_retries + 1):
                    loop = asyncio.get_running_loop()
                    delay = self._min_interval - (loop.time() - self._last_started)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    self._last_started = loop.time()
                    try:
                        result = await operation()
                    except Exception:
                        if attempt >= self._max_retries:
                            self._record_failure()
                            raise
                        base = 5 if attempt == 0 else 15
                        await asyncio.sleep(base + self._random.uniform(0, 1))
                    else:
                        self._record_success()
                        return result
        finally:
            self._half_open_in_flight = False
        raise AssertionError("unreachable")

    def _record_failure(self) -> None:
        self._failures += 1
        if self._state is CircuitState.HALF_OPEN or self._failures >= self._failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = datetime.now(UTC)

    def _record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._state = CircuitState.CLOSED
