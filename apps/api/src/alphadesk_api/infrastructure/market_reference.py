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

# Exchange-verified A-share weekday closures.  Weekend dates are intentionally
# omitted because they are derived below.  Keep whole published holiday
# schedules together: adding one incident date would recreate the exact class
# of calendar mismatch CAL01-R fixes.
VERIFIED_A_SHARE_HOLIDAYS = {
    date(2024, 1, 1),
    date(2024, 2, 9),
    date(2024, 2, 12),
    date(2024, 2, 13),
    date(2024, 2, 14),
    date(2024, 2, 15),
    date(2024, 2, 16),
    date(2024, 4, 4),
    date(2024, 4, 5),
    date(2024, 5, 1),
    date(2024, 5, 2),
    date(2024, 5, 3),
    date(2024, 6, 10),
    date(2024, 9, 16),
    date(2024, 9, 17),
    date(2024, 10, 1),
    date(2024, 10, 2),
    date(2024, 10, 3),
    date(2024, 10, 4),
    date(2024, 10, 7),
    date(2025, 1, 1),
    date(2025, 1, 28),
    date(2025, 1, 29),
    date(2025, 1, 30),
    date(2025, 1, 31),
    date(2025, 2, 3),
    date(2025, 2, 4),
    date(2025, 4, 4),
    date(2025, 5, 1),
    date(2025, 5, 2),
    date(2025, 5, 5),
    date(2025, 6, 2),
    date(2025, 10, 1),
    date(2025, 10, 2),
    date(2025, 10, 3),
    date(2025, 10, 6),
    date(2025, 10, 7),
    date(2025, 10, 8),
    date(2026, 1, 1),
    date(2026, 1, 2),
    date(2026, 2, 16),
    date(2026, 2, 17),
    date(2026, 2, 18),
    date(2026, 2, 19),
    date(2026, 2, 20),
    date(2026, 2, 23),
    date(2026, 4, 6),
    date(2026, 5, 1),
    date(2026, 5, 4),
    date(2026, 5, 5),
    date(2026, 6, 19),
    date(2026, 9, 25),
    date(2026, 10, 1),
    date(2026, 10, 2),
    date(2026, 10, 5),
    date(2026, 10, 6),
    date(2026, 10, 7),
}

# Fixture remains available for deterministic tests, but no longer means
# "Monday to Friday".  Production uses the separately named verified provider
# so persisted provenance cannot be confused with test data.
FIXTURE_HOLIDAYS = VERIFIED_A_SHARE_HOLIDAYS


class FixtureMarketReferenceProvider:
    source = "FIXTURE"

    async def fetch_calendar(
        self, exchange: str, start: date, end: date
    ) -> list[TradingCalendarSession]:
        now = datetime.now(UTC)
        dates: list[date] = []
        context_dates: list[date] = []
        current = start - timedelta(days=14)
        while current <= end + timedelta(days=14):
            context_dates.append(current)
            if start <= current <= end:
                dates.append(current)
            current += timedelta(days=1)
        open_dates = [
            value
            for value in context_dates
            if value.weekday() < 5 and value not in FIXTURE_HOLIDAYS
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


class VerifiedAshareMarketReferenceProvider(FixtureMarketReferenceProvider):
    """Auditable calendar built from published SSE/SZSE closure schedules."""

    source = "VERIFIED_CN_A_CALENDAR"
