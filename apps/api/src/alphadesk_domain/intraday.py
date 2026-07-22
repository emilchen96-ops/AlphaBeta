"""Pure D03 intraday time, provider and aggregation contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from alphadesk_domain.enums import AdjustmentType, MarketTimeframe
from alphadesk_domain.market import MarketBar

SHANGHAI = ZoneInfo("Asia/Shanghai")
AGGREGATION_VERSION = "D03_SESSION_V1"
INTRADAY_TIMEFRAMES = (
    MarketTimeframe.MINUTE_1,
    MarketTimeframe.MINUTE_5,
    MarketTimeframe.MINUTE_15,
    MarketTimeframe.MINUTE_30,
    MarketTimeframe.MINUTE_60,
)
TIMEFRAME_MINUTES = {
    MarketTimeframe.MINUTE_1: 1,
    MarketTimeframe.MINUTE_5: 5,
    MarketTimeframe.MINUTE_15: 15,
    MarketTimeframe.MINUTE_30: 30,
    MarketTimeframe.MINUTE_60: 60,
}
INTRADAY_QUALITY_ISSUE_TYPES = (
    "INTRADAY_TIMESTAMP_MISALIGNED",
    "INTRADAY_OUTSIDE_SESSION",
    "INTRADAY_LUNCH_BREAK_BAR",
    "INTRADAY_DUPLICATE_BAR",
    "INTRADAY_MISSING_BAR",
    "INTRADAY_UNEXPECTED_BAR_COUNT",
    "INTRADAY_OHLC_INVALID",
    "INTRADAY_NEGATIVE_VOLUME",
    "INTRADAY_AMOUNT_INVALID",
    "INTRADAY_AGGREGATION_MISMATCH",
    "INTRADAY_CROSS_SESSION_AGGREGATION",
    "INTRADAY_SOURCE_CONFLICT",
    "INTRADAY_TIMEZONE_AMBIGUOUS",
    "INTRADAY_ADJUSTMENT_FACTOR_MISSING",
)


class IntradayProviderHealth(StrEnum):
    AVAILABLE = "AVAILABLE"
    DISABLED = "DISABLED"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"


class IntradayConflictPolicy(StrEnum):
    REJECT = "reject"
    KEEP_EXISTING = "keep_existing"
    UPDATE_SAME_SOURCE = "update_same_source"


class IntradayWindowPolicy(StrEnum):
    STRICT_COMPLETE_WINDOW = "STRICT_COMPLETE_WINDOW"
    ALLOW_PARTIAL_WINDOW = "ALLOW_PARTIAL_WINDOW"


@dataclass(frozen=True, slots=True, kw_only=True)
class IntradayProviderStatus:
    provider_key: str
    health: IntradayProviderHealth
    supported_timeframes: tuple[MarketTimeframe, ...]
    input_types: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class IntradayExternalBar:
    symbol: str
    exchange: str
    timestamp: datetime
    timeframe: MarketTimeframe
    open: str
    high: str
    low: str
    close: str
    volume: str
    amount: str | None = None
    source: str | None = None
    adjustment_mode: AdjustmentType = AdjustmentType.NONE
    metadata: dict[str, object] = field(default_factory=dict)


class IntradayMarketDataProvider(Protocol):
    @property
    def provider_key(self) -> str: ...

    @property
    def supported_timeframes(self) -> tuple[MarketTimeframe, ...]: ...

    def validate_configuration(self) -> None: ...

    async def health_status(self) -> IntradayProviderStatus: ...

    def fetch_bars(self) -> AsyncIterator[IntradayExternalBar]: ...


@dataclass(frozen=True, slots=True)
class SessionSegment:
    start: time
    end: time


class IntradaySessionTemplate:
    """First-version regular A-share continuous-auction session template."""

    segments = (
        SessionSegment(time(9, 30), time(11, 30)),
        SessionSegment(time(13, 0), time(15, 0)),
    )

    def normalize(self, value: datetime, source_timezone: str | None = None) -> datetime:
        if value.tzinfo is None:
            if source_timezone is None:
                raise ValueError("INTRADAY_TIMEZONE_REQUIRED")
            value = value.replace(tzinfo=ZoneInfo(source_timezone))
        return value.astimezone(UTC)

    def local(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(SHANGHAI)

    def segment_for(self, value: datetime) -> SessionSegment | None:
        local_time = self.local(value).time().replace(tzinfo=None)
        return next(
            (segment for segment in self.segments if segment.start <= local_time < segment.end),
            None,
        )

    def validate_bar_start(self, value: datetime, timeframe: MarketTimeframe) -> bool:
        if timeframe not in TIMEFRAME_MINUTES:
            return False
        local = self.local(value)
        segment = self.segment_for(value)
        if segment is None or local.second or local.microsecond:
            return False
        elapsed = local.hour * 60 + local.minute - segment.start.hour * 60 - segment.start.minute
        return elapsed % TIMEFRAME_MINUTES[timeframe] == 0

    def window_start(self, value: datetime, timeframe: MarketTimeframe) -> datetime:
        local = self.local(value)
        segment = self.segment_for(value)
        if segment is None:
            raise ValueError("INTRADAY_OUTSIDE_SESSION")
        minutes = TIMEFRAME_MINUTES[timeframe]
        elapsed = local.hour * 60 + local.minute - segment.start.hour * 60 - segment.start.minute
        start_minutes = (
            segment.start.hour * 60 + segment.start.minute + elapsed // minutes * minutes
        )
        result = datetime.combine(
            local.date(), time(start_minutes // 60, start_minutes % 60), tzinfo=SHANGHAI
        )
        return result.astimezone(UTC)

    def expected_starts(
        self, session_date: date, timeframe: MarketTimeframe
    ) -> tuple[datetime, ...]:
        minutes = TIMEFRAME_MINUTES[timeframe]
        values: list[datetime] = []
        for segment in self.segments:
            cursor = datetime.combine(session_date, segment.start, tzinfo=SHANGHAI)
            end = datetime.combine(session_date, segment.end, tzinfo=SHANGHAI)
            while cursor < end:
                values.append(cursor.astimezone(UTC))
                cursor += timedelta(minutes=minutes)
        return tuple(values)

    def expected_count(self, timeframe: MarketTimeframe) -> int:
        return len(self.expected_starts(date(2026, 1, 5), timeframe))


@dataclass(frozen=True, slots=True)
class AggregationResult:
    bars: tuple[MarketBar, ...]
    incomplete_windows: tuple[datetime, ...]


class IntradayBarAggregator:
    def __init__(self, template: IntradaySessionTemplate | None = None) -> None:
        self._template = template or IntradaySessionTemplate()

    def aggregate(
        self,
        bars: Iterable[MarketBar],
        target: MarketTimeframe,
        policy: IntradayWindowPolicy = IntradayWindowPolicy.STRICT_COMPLETE_WINDOW,
    ) -> AggregationResult:
        if target not in INTRADAY_TIMEFRAMES[1:]:
            raise ValueError("INTRADAY_TIMEFRAME_NOT_SUPPORTED")
        ordered = sorted(bars, key=lambda bar: (bar.bar_time, str(bar.instrument_id), bar.id or 0))
        if any(bar.timeframe is not MarketTimeframe.MINUTE_1 for bar in ordered):
            raise ValueError("aggregation source must be MINUTE_1")
        grouped: dict[tuple[object, object, datetime], list[MarketBar]] = {}
        for bar in ordered:
            if not self._template.validate_bar_start(bar.bar_time, MarketTimeframe.MINUTE_1):
                continue
            key = (
                bar.instrument_id,
                bar.source_id,
                self._template.window_start(bar.bar_time, target),
            )
            grouped.setdefault(key, []).append(bar)
        expected = TIMEFRAME_MINUTES[target]
        output: list[MarketBar] = []
        incomplete: list[datetime] = []
        for (_, _, start), window in sorted(grouped.items(), key=lambda item: item[0][2]):
            unique = {bar.bar_time: bar for bar in window}
            values = [unique[key] for key in sorted(unique)]
            complete = len(values) == expected and all(
                values[index].bar_time == start + timedelta(minutes=index)
                for index in range(len(values))
            )
            if not complete and policy is IntradayWindowPolicy.STRICT_COMPLETE_WINDOW:
                incomplete.append(start)
                continue
            first, last = values[0], values[-1]
            amounts = [bar.amount for bar in values if bar.amount is not None]
            flags = dict(first.quality_flags)
            flags.update(
                {
                    "source_timeframe": MarketTimeframe.MINUTE_1.value,
                    "aggregation_version": AGGREGATION_VERSION,
                    "input_bar_count": len(values),
                    "window_policy": policy.value,
                }
            )
            output.append(
                replace(
                    first,
                    id=None,
                    timeframe=target,
                    bar_time=start,
                    open=first.open,
                    high=max(bar.high for bar in values),
                    low=min(bar.low for bar in values),
                    close=last.close,
                    volume=sum((bar.volume for bar in values), Decimal("0")),
                    amount=sum(amounts, Decimal("0")) if amounts else None,
                    vwap=None,
                    quality_flags=flags,
                )
            )
        return AggregationResult(tuple(output), tuple(incomplete))


@dataclass(frozen=True, slots=True)
class AggregationMismatch:
    bar_time: datetime
    fields: tuple[str, ...]


class IntradayAggregationIntegrityService:
    def __init__(self) -> None:
        self._aggregator = IntradayBarAggregator()

    def compare(
        self,
        one_minute: Iterable[MarketBar],
        aggregated: Iterable[MarketBar],
        target: MarketTimeframe,
    ) -> tuple[AggregationMismatch, ...]:
        expected = {
            bar.bar_time: bar for bar in self._aggregator.aggregate(one_minute, target).bars
        }
        actual = {bar.bar_time: bar for bar in aggregated}
        mismatches: list[AggregationMismatch] = []
        for bar_time in sorted(set(expected) | set(actual)):
            left, right = expected.get(bar_time), actual.get(bar_time)
            if left is None or right is None:
                mismatches.append(AggregationMismatch(bar_time, ("missing",)))
                continue
            fields = tuple(
                name
                for name in ("open", "high", "low", "close", "volume", "amount")
                if getattr(left, name) != getattr(right, name)
            )
            if right.quality_flags.get("aggregation_version") != AGGREGATION_VERSION:
                fields += ("aggregation_version",)
            if fields:
                mismatches.append(AggregationMismatch(bar_time, fields))
        return tuple(mismatches)
