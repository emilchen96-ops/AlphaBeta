"""Offline fixture adapters for D02 market-reference provider ports."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from alphadesk_domain.market_reference import (
    AdjustmentFactor,
    CalendarSessionType,
    FactorConvention,
    InstrumentLifecycleEvent,
    InstrumentLifecycleType,
    InstrumentTradingState,
    InstrumentTradingStatus,
    TradingCalendarSession,
)

# Explicit deterministic fixture closures. It is not presented as an authoritative live calendar.
FIXTURE_HOLIDAYS = {
    date(2024, 1, 1),
    date(2024, 2, 9),
    date(2024, 2, 12),
    date(2024, 2, 13),
    date(2024, 2, 14),
    date(2024, 2, 15),
    date(2024, 2, 16),
    date(2024, 4, 4),
    date(2024, 5, 1),
    date(2024, 10, 1),
    date(2025, 1, 1),
    date(2026, 1, 1),
}


class FixtureMarketReferenceProvider:
    source = "FIXTURE"

    async def fetch_calendar(
        self, exchange: str, start: date, end: date
    ) -> list[TradingCalendarSession]:
        now = datetime.now(UTC)
        dates: list[date] = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
        open_dates = [
            value for value in dates if value.weekday() < 5 and value not in FIXTURE_HOLIDAYS
        ]
        values: list[TradingCalendarSession] = []
        for value in dates:
            is_weekend = value.weekday() >= 5
            is_holiday = value in FIXTURE_HOLIDAYS
            is_open = not is_weekend and not is_holiday
            previous = max((item for item in open_dates if item < value), default=None)
            following = min((item for item in open_dates if item > value), default=None)
            values.append(
                TradingCalendarSession(
                    exchange=exchange,
                    session_date=value,
                    is_open=is_open,
                    previous_open_date=previous,
                    next_open_date=following,
                    session_type=(
                        CalendarSessionType.NORMAL
                        if is_open
                        else CalendarSessionType.WEEKEND
                        if is_weekend
                        else CalendarSessionType.HOLIDAY
                    ),
                    source=self.source,
                    fetched_at=now,
                )
            )
        return values

    async def fetch_adjustments(
        self, instrument_ids: list[UUID], start: date, end: date
    ) -> list[AdjustmentFactor]:
        now = datetime.now(UTC)
        values: list[AdjustmentFactor] = []
        current = start
        while current <= end:
            if current.weekday() < 5 and current not in FIXTURE_HOLIDAYS:
                values.extend(
                    AdjustmentFactor(
                        instrument_id=instrument_id,
                        trade_date=current,
                        factor=Decimal("1"),
                        factor_convention=FactorConvention.TUSHARE_CUMULATIVE,
                        source=self.source,
                        fetched_at=now,
                    )
                    for instrument_id in instrument_ids
                )
            current += timedelta(days=1)
        return values

    async def fetch_suspensions(
        self, instrument_ids: list[UUID], start: date, end: date
    ) -> list[InstrumentTradingStatus]:
        now = datetime.now(UTC)
        values: list[InstrumentTradingStatus] = []
        current = start
        while current <= end:
            if current.weekday() < 5 and current not in FIXTURE_HOLIDAYS:
                values.extend(
                    InstrumentTradingStatus(
                        instrument_id=instrument_id,
                        session_date=current,
                        status=InstrumentTradingState.TRADING,
                        source=self.source,
                        fetched_at=now,
                    )
                    for instrument_id in instrument_ids
                )
            current += timedelta(days=1)
        return values

    async def fetch_lifecycle(self, instrument_ids: list[UUID]) -> list[InstrumentLifecycleEvent]:
        now = datetime.now(UTC)
        return [
            InstrumentLifecycleEvent(
                instrument_id=instrument_id,
                event_date=date(1990, 1, 1),
                event_type=InstrumentLifecycleType.LISTED,
                source=self.source,
                fetched_at=now,
                reason="fixture listing baseline",
            )
            for instrument_id in instrument_ids
        ]
