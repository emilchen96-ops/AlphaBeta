from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_api.infrastructure.market_reference import FixtureMarketReferenceProvider
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataQualityStatus,
    MarketTimeframe,
)
from alphadesk_domain.market import MarketBar
from alphadesk_domain.market_reference import (
    AdjustedMarketBarService,
    AdjustmentFactor,
    CalendarSessionType,
    FactorConvention,
    InstrumentTradingState,
    InstrumentTradingStatus,
    MarketReferenceError,
    PriceAdjustmentMode,
    TradingCalendarService,
    TradingCalendarSession,
    TradingStatusService,
)

NOW = datetime(2024, 1, 3, 8, tzinfo=UTC)


def session(exchange: str, value: date, *, is_open: bool = True) -> TradingCalendarSession:
    return TradingCalendarSession(
        exchange=exchange,
        session_date=value,
        is_open=is_open,
        session_type=CalendarSessionType.NORMAL if is_open else CalendarSessionType.HOLIDAY,
        source="FIXTURE",
        fetched_at=NOW,
    )


def bar(value: date, close: str, *, bar_id: int) -> MarketBar:
    price = Decimal(close)
    return MarketBar(
        id=bar_id,
        instrument_id=uuid4(),
        source_id=uuid4(),
        timeframe=MarketTimeframe.DAY_1,
        adjustment_type=AdjustmentType.NONE,
        bar_time=datetime(value.year, value.month, value.day, tzinfo=UTC),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1000"),
        amount=Decimal("10000"),
        received_at=NOW,
        quality_status=MarketDataQualityStatus.NORMAL,
    )


def factor(instrument_id, value: date, amount: str) -> AdjustmentFactor:
    return AdjustmentFactor(
        instrument_id=instrument_id,
        trade_date=value,
        factor=Decimal(amount),
        factor_convention=FactorConvention.TUSHARE_CUMULATIVE,
        source="FIXTURE",
        fetched_at=NOW,
    )


@pytest.mark.asyncio
async def test_fixture_calendar_distinguishes_open_weekend_and_holiday() -> None:
    values = await FixtureMarketReferenceProvider().fetch_calendar(
        "SHSE", date(2024, 1, 1), date(2024, 1, 7)
    )
    by_date = {item.session_date: item for item in values}
    assert by_date[date(2024, 1, 1)].session_type is CalendarSessionType.HOLIDAY
    assert by_date[date(2024, 1, 2)].is_open is True
    assert by_date[date(2024, 1, 6)].session_type is CalendarSessionType.WEEKEND


def test_calendar_previous_next_latest_and_common_sessions() -> None:
    values = [
        session(exchange, value)
        for exchange in ("SHSE", "SZSE")
        for value in (date(2024, 1, 2), date(2024, 1, 3))
    ]
    service = TradingCalendarService(values)
    assert service.previous_open_date("SHSE", date(2024, 1, 3)) == date(2024, 1, 2)
    assert service.next_open_date("SZSE", date(2024, 1, 2)) == date(2024, 1, 3)
    assert service.latest_completed_session(
        "SHSE", datetime(2024, 1, 3, 14, tzinfo=service_timezone())
    ) == date(2024, 1, 2)
    assert service.common_a_share_sessions(date(2024, 1, 2), date(2024, 1, 3)) == (
        date(2024, 1, 2),
        date(2024, 1, 3),
    )


def service_timezone():
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Shanghai")


def test_missing_calendar_is_controlled() -> None:
    with pytest.raises(MarketReferenceError) as captured:
        TradingCalendarService([]).sessions_between("SHSE", date(2024, 1, 1), date(2024, 1, 2))
    assert captured.value.code == "MARKET_CALENDAR_NOT_AVAILABLE"


def test_raw_is_unchanged_and_qfq_is_deterministic_without_mutating_raw() -> None:
    first = bar(date(2024, 1, 2), "10.123456", bar_id=1)
    second = bar(date(2024, 1, 3), "20.246912", bar_id=2)
    factors = [
        factor(first.instrument_id, date(2024, 1, 2), "1"),
        factor(first.instrument_id, date(2024, 1, 3), "2"),
    ]
    second.instrument_id = first.instrument_id
    service = AdjustedMarketBarService()
    raw = service.adjust([first, second], factors, PriceAdjustmentMode.RAW)
    adjusted = service.adjust([first, second], factors, PriceAdjustmentMode.QFQ)
    assert raw[0].as_market_bar() is first
    assert adjusted[0].as_market_bar().close == Decimal("5.0617280")
    assert adjusted[1].as_market_bar().close == Decimal("20.246912")
    assert adjusted[0].as_market_bar().volume == Decimal("1000")
    assert adjusted[0].as_market_bar().amount == Decimal("10000")
    assert adjusted[0].raw_bar_id == 1
    assert first.close == Decimal("10.123456")
    assert service.adjust([first, second], factors, PriceAdjustmentMode.QFQ) == adjusted


def test_adjustment_factor_validation_and_missing_factor() -> None:
    instrument_id = uuid4()
    with pytest.raises(TypeError):
        AdjustmentFactor(
            instrument_id=instrument_id,
            trade_date=date(2024, 1, 2),
            factor=1.0,  # type: ignore[arg-type]
            factor_convention=FactorConvention.NONE,
            source="FIXTURE",
            fetched_at=NOW,
        )
    with pytest.raises(MarketReferenceError):
        factor(instrument_id, date(2024, 1, 2), "0")
    raw_bar = bar(date(2024, 1, 2), "10", bar_id=1)
    with pytest.raises(MarketReferenceError) as captured:
        AdjustedMarketBarService().adjust([raw_bar], [], PriceAdjustmentMode.QFQ)
    assert captured.value.code == "MARKET_ADJUSTMENT_FACTOR_NOT_AVAILABLE"


def test_trading_status_keeps_unknown_distinct_from_suspended_and_resumed() -> None:
    instrument_id = uuid4()
    statuses = [
        InstrumentTradingStatus(
            instrument_id=instrument_id,
            session_date=date(2024, 1, 2),
            status=InstrumentTradingState.SUSPENDED,
            source="FIXTURE",
            fetched_at=NOW,
        ),
        InstrumentTradingStatus(
            instrument_id=instrument_id,
            session_date=date(2024, 1, 3),
            status=InstrumentTradingState.RESUMED,
            source="FIXTURE",
            fetched_at=NOW,
        ),
    ]
    service = TradingStatusService(statuses)
    assert service.is_tradable(instrument_id, date(2024, 1, 2)) is False
    assert service.is_tradable(instrument_id, date(2024, 1, 3)) is True
    assert service.is_tradable(instrument_id, date(2024, 1, 4)) is None
    assert service.suspended_sessions(instrument_id, date(2024, 1, 1), date(2024, 1, 5)) == (
        date(2024, 1, 2),
    )
