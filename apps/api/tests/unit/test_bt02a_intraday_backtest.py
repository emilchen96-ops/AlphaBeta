from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_api.application.backtests import (
    _limit_locked_available_volume,
    _reliable_price_limits,
)
from alphadesk_domain.backtest import (
    ASHARE_TIMEZONE,
    BacktestConfiguration,
    BacktestError,
    BacktestExecutionPriceMode,
    backtest_configuration_from_dict,
    backtest_configuration_to_dict,
    backtest_request_fingerprint,
)
from alphadesk_domain.entities import Instrument, Order
from alphadesk_domain.enums import (
    MarketTimeframe,
    OrderSide,
    OrderStatus,
    OrderType,
    SignalType,
    TimeInForce,
)
from alphadesk_domain.intraday_backtest import (
    IntradayDailyStrategyEvaluator,
    PriceVolumeSmaRule,
    build_partial_daily_bar,
    inspect_minute_session,
    safe_prefilter_plan,
    signal_confirmation_points,
)
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.strategy import StrategyBar

pytestmark = [pytest.mark.unit, pytest.mark.bt02]


INSTRUMENT_ID = uuid4()


def _timestamp(day: date, value: time) -> datetime:
    return datetime.combine(day, value, tzinfo=ASHARE_TIMEZONE).astimezone(UTC)


def _bar(
    day: date,
    *,
    value: Decimal = Decimal("10"),
    high: Decimal | None = None,
    low: Decimal | None = None,
    volume: Decimal = Decimal("100"),
) -> StrategyBar:
    return StrategyBar(
        instrument_id=INSTRUMENT_ID,
        symbol="300088",
        exchange="SZSE",
        timeframe=MarketTimeframe.DAY_1,
        timestamp=_timestamp(day, time(15, 0)),
        open=value,
        high=high or value,
        low=low or value,
        close=value,
        volume=volume,
        amount=value * volume,
        adjustment_mode=PriceAdjustmentMode.RAW,
        raw_reference_price=value,
    )


def _minute(
    day: date,
    value: time,
    *,
    price: Decimal = Decimal("10"),
    volume: Decimal = Decimal("1"),
) -> StrategyBar:
    return StrategyBar(
        instrument_id=INSTRUMENT_ID,
        symbol="300088",
        exchange="SZSE",
        timeframe=MarketTimeframe.MINUTE_1,
        timestamp=_timestamp(day, value),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
        amount=price * volume,
        adjustment_mode=PriceAdjustmentMode.RAW,
        raw_reference_price=price,
    )


def _full_session(day: date) -> list[StrategyBar]:
    result: list[StrategyBar] = []
    current = datetime.combine(day, time(9, 30))
    while current.time() < time(11, 30):
        result.append(_minute(day, current.time()))
        current += timedelta(minutes=1)
    current = datetime.combine(day, time(13, 0))
    while current.time() < time(15, 0):
        result.append(_minute(day, current.time()))
        current += timedelta(minutes=1)
    return result


def _rule() -> PriceVolumeSmaRule:
    return PriceVolumeSmaRule(10, 10, Decimal("1.2"), 5, Decimal("100"))


def _evaluator() -> IntradayDailyStrategyEvaluator:
    return IntradayDailyStrategyEvaluator(
        strategy_key="price_volume_breakout_sma_exit",
        strategy_version="1.0.0",
        rule=_rule(),
        spec=None,
    )


def _instrument(
    *,
    symbol: str = "600000",
    exchange: str = "SSE",
    name: str = "浦发银行",
    listed_at: date | None = date(1999, 11, 10),
    metadata: dict | None = None,
) -> Instrument:
    return Instrument(
        id=INSTRUMENT_ID,
        symbol=symbol,
        exchange=exchange,
        market="CN_A",
        name=name,
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
        listed_at=listed_at,
        metadata=metadata or {},
    )


def _order(side: OrderSide) -> Order:
    return Order(
        account_id=uuid4(),
        instrument_id=INSTRUMENT_ID,
        side=side,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        requested_quantity=Decimal("100"),
        status=OrderStatus.CREATED,
        idempotency_key=f"bt02:{side.value}",
        broker_type="SIMULATED",
        correlation_id=uuid4(),
    )


def _configuration() -> BacktestConfiguration:
    return BacktestConfiguration(
        strategy_key="price_volume_breakout_sma_exit",
        strategy_version="1.0.0",
        parameters={
            "breakout_window": 10,
            "volume_window": 10,
            "volume_multiplier": Decimal("1.2"),
            "exit_sma_window": 5,
            "quantity": Decimal("100"),
        },
        instrument_ids=(INSTRUMENT_ID,),
        timeframe=MarketTimeframe.DAY_1,
        start_at=datetime(2024, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 1, tzinfo=UTC),
        initial_cash=Decimal("100000"),
        execution_price_mode=BacktestExecutionPriceMode.INTRADAY_NEXT_MINUTE,
        signal_timeframe=MarketTimeframe.MINUTE_1,
        data_source_code="MINIQMT",
    )


def test_partial_daily_bar_uses_only_supplied_closed_minutes() -> None:
    day = date(2026, 7, 30)
    partial = build_partial_daily_bar(
        _bar(day, value=Decimal("99")),
        [
            _minute(day, time(9, 30), price=Decimal("10"), volume=Decimal("2")),
            _minute(day, time(9, 31), price=Decimal("12"), volume=Decimal("3")),
            _minute(day, time(9, 32), price=Decimal("11"), volume=Decimal("5")),
        ],
    )

    assert (partial.open, partial.high, partial.low, partial.close) == (
        Decimal("10"),
        Decimal("12"),
        Decimal("10"),
        Decimal("11"),
    )
    assert partial.volume == Decimal("10")
    assert partial.timestamp == _timestamp(day, time(9, 32))


def test_partial_daily_bar_rejects_another_instrument() -> None:
    day = date(2026, 7, 30)
    foreign = replace(_minute(day, time(9, 30)), instrument_id=uuid4())
    with pytest.raises(ValueError, match="another instrument"):
        build_partial_daily_bar(_bar(day), [foreign])


def test_one_minute_signal_confirms_after_every_closed_bar() -> None:
    day = date(2026, 7, 30)
    bars = [_minute(day, time(9, 30 + offset)) for offset in range(4)]
    assert signal_confirmation_points(bars, MarketTimeframe.MINUTE_1) == (0, 1, 2, 3)


def test_five_minute_confirmation_resets_across_lunch() -> None:
    day = date(2026, 7, 30)
    bars = [_minute(day, time(9, 30 + offset)) for offset in range(6)] + [
        _minute(day, time(13, offset)) for offset in range(5)
    ]
    assert signal_confirmation_points(bars, MarketTimeframe.MINUTE_5) == (4, 10)


def test_fifteen_minute_confirmation_uses_completed_buckets_only() -> None:
    day = date(2026, 7, 30)
    bars = [_minute(day, time(9, 30 + offset)) for offset in range(29)]
    assert signal_confirmation_points(bars, MarketTimeframe.MINUTE_15) == (14,)


def test_confirmation_rejects_unsupported_signal_timeframe() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        signal_confirmation_points(
            [_minute(date(2026, 7, 30), time(9, 30))], MarketTimeframe.MINUTE_30
        )


def test_reference_entry_uses_prior_completed_days_and_current_partial_only() -> None:
    current = date(2026, 7, 30)
    history = [_bar(date(2026, 7, 1) + timedelta(days=index)) for index in range(10)]
    evaluator = _evaluator()
    before = _bar(current, value=Decimal("11"), high=Decimal("11"), volume=Decimal("120"))
    trigger = replace(before, volume=Decimal("121"), timestamp=_timestamp(current, time(10, 1)))

    assert (
        evaluator.evaluate(
            completed_daily_bars=history,
            partial_daily_bar=before,
            generated_at=_timestamp(current, time(10, 0)),
        )
        == []
    )
    signals = evaluator.evaluate(
        completed_daily_bars=history,
        partial_daily_bar=trigger,
        generated_at=_timestamp(current, time(10, 2)),
    )
    assert len(signals) == 1
    assert signals[0].signal_type is SignalType.ENTRY
    assert signals[0].side is OrderSide.BUY


def test_sustained_true_entry_condition_emits_only_once() -> None:
    current = date(2026, 7, 30)
    history = [_bar(date(2026, 7, 1) + timedelta(days=index)) for index in range(10)]
    partial = _bar(current, value=Decimal("11"), high=Decimal("11"), volume=Decimal("121"))
    evaluator = _evaluator()

    first = evaluator.evaluate(
        completed_daily_bars=history,
        partial_daily_bar=partial,
        generated_at=_timestamp(current, time(10, 0)),
    )
    second = evaluator.evaluate(
        completed_daily_bars=history,
        partial_daily_bar=replace(partial, timestamp=_timestamp(current, time(10, 1))),
        generated_at=_timestamp(current, time(10, 2)),
    )
    assert len(first) == 1
    assert second == []


def test_dynamic_exit_sma_uses_four_completed_closes_and_current_minute() -> None:
    current = date(2026, 7, 30)
    history = [_bar(date(2026, 7, 1) + timedelta(days=index)) for index in range(10)]
    evaluator = _evaluator()
    entry = _bar(current, value=Decimal("11"), high=Decimal("11"), volume=Decimal("121"))
    entry_signals = evaluator.evaluate(
        completed_daily_bars=history,
        partial_daily_bar=entry,
        generated_at=_timestamp(current, time(10, 0)),
    )
    assert len(entry_signals) == 1
    evaluator.record_fill(INSTRUMENT_ID, OrderSide.BUY)
    exit_bar = _bar(current, value=Decimal("9"), high=Decimal("11"), volume=Decimal("130"))
    signals = evaluator.evaluate(
        completed_daily_bars=history,
        partial_daily_bar=replace(exit_bar, timestamp=_timestamp(current, time(10, 1))),
        generated_at=_timestamp(current, time(10, 2)),
    )
    assert len(signals) == 1
    assert signals[0].signal_type is SignalType.EXIT
    assert signals[0].side is OrderSide.SELL


def test_unfilled_entry_signal_does_not_create_phantom_exit() -> None:
    current = date(2026, 7, 30)
    history = [_bar(date(2026, 7, 1) + timedelta(days=index)) for index in range(10)]
    evaluator = _evaluator()
    entry = _bar(current, value=Decimal("11"), high=Decimal("11"), volume=Decimal("121"))
    assert evaluator.evaluate(
        completed_daily_bars=history,
        partial_daily_bar=entry,
        generated_at=_timestamp(current, time(10, 0)),
    )
    exit_bar = _bar(current, value=Decimal("9"), high=Decimal("11"), volume=Decimal("130"))
    assert (
        evaluator.evaluate(
            completed_daily_bars=history,
            partial_daily_bar=replace(exit_bar, timestamp=_timestamp(current, time(10, 1))),
            generated_at=_timestamp(current, time(10, 2)),
        )
        == []
    )


def test_safe_prefilter_excludes_mathematically_impossible_days() -> None:
    start = date(2026, 7, 1)
    bars = [_bar(start + timedelta(days=index)) for index in range(12)]
    plan = safe_prefilter_plan(bars, _rule())
    assert plan.safe is True
    assert plan.candidate_entry_dates == frozenset()
    assert plan.replay_dates == frozenset()


def test_safe_prefilter_replays_every_session_after_first_candidate_for_exits() -> None:
    start = date(2026, 7, 1)
    bars = [_bar(start + timedelta(days=index)) for index in range(10)]
    candidate = _bar(
        start + timedelta(days=10),
        value=Decimal("11"),
        high=Decimal("11"),
        volume=Decimal("121"),
    )
    following = _bar(start + timedelta(days=11), value=Decimal("9"), volume=Decimal("80"))
    plan = safe_prefilter_plan([*bars, candidate, following], _rule())
    assert plan.candidate_entry_dates == frozenset({_bar_date(candidate)})
    assert plan.replay_dates == frozenset({_bar_date(candidate), _bar_date(following)})


def test_safe_prefilter_and_full_minute_scan_emit_identical_reference_signals() -> None:
    start = date(2026, 7, 1)
    daily_bars = [_bar(start + timedelta(days=index)) for index in range(10)]
    daily_bars.extend(
        [
            _bar(
                start + timedelta(days=10),
                value=Decimal("11"),
                high=Decimal("11"),
                low=Decimal("10"),
                volume=Decimal("130"),
            ),
            _bar(
                start + timedelta(days=11),
                value=Decimal("9"),
                high=Decimal("11"),
                low=Decimal("9"),
                volume=Decimal("130"),
            ),
        ]
    )

    def session(day: date, *, final_price: Decimal) -> list[StrategyBar]:
        return [
            _minute(day, time(9, 30), price=Decimal("10"), volume=Decimal("30")),
            _minute(day, time(9, 31), price=Decimal("10"), volume=Decimal("30")),
            _minute(day, time(9, 32), price=Decimal("10"), volume=Decimal("30")),
            _minute(day, time(9, 33), price=final_price, volume=Decimal("40")),
        ]

    sessions = {
        _bar_date(item): session(
            _bar_date(item), final_price=item.close
        )
        for item in daily_bars
    }

    def replay(allowed_dates: frozenset[date]) -> list[tuple[date, OrderSide]]:
        evaluator = _evaluator()
        emitted: list[tuple[date, OrderSide]] = []
        for index, daily_bar in enumerate(daily_bars):
            trading_date = _bar_date(daily_bar)
            if trading_date not in allowed_dates:
                continue
            minutes = sessions[trading_date]
            for minute_index, minute_bar in enumerate(minutes):
                partial = build_partial_daily_bar(
                    daily_bar, minutes[: minute_index + 1]
                )
                signals = evaluator.evaluate(
                    completed_daily_bars=daily_bars[:index],
                    partial_daily_bar=partial,
                    generated_at=minute_bar.timestamp + timedelta(minutes=1),
                )
                for signal in signals:
                    emitted.append((trading_date, signal.side))
                    evaluator.record_fill(INSTRUMENT_ID, signal.side)
        return emitted

    full_dates = frozenset(_bar_date(item) for item in daily_bars)
    plan = safe_prefilter_plan(daily_bars, _rule())

    assert replay(plan.replay_dates) == replay(full_dates) == [
        (start + timedelta(days=10), OrderSide.BUY),
        (start + timedelta(days=11), OrderSide.SELL),
    ]


def test_unknown_strategy_prefilter_is_conservative() -> None:
    bars = [_bar(date(2026, 7, 1)), _bar(date(2026, 7, 2))]
    plan = safe_prefilter_plan(bars, None)
    assert plan.safe is False
    assert plan.replay_dates == frozenset({_bar_date(item) for item in bars})


def test_complete_minute_session_matches_authoritative_daily_bar() -> None:
    day = date(2026, 7, 30)
    quality = inspect_minute_session(_bar(day, volume=Decimal("240")), _full_session(day))
    assert quality.usable is True
    assert quality.issues == ()
    assert quality.minute_count == 240


def test_genuine_intraday_gap_is_a_warning_when_daily_envelope_still_matches() -> None:
    day = date(2026, 7, 30)
    bars = [item for item in _full_session(day) if item.timestamp != _timestamp(day, time(10, 0))]
    quality = inspect_minute_session(_bar(day, volume=Decimal("239")), bars)
    assert quality.usable is True
    assert quality.warnings == ("INTRADAY_GAP",)


def test_missing_session_close_is_not_usable() -> None:
    day = date(2026, 7, 30)
    bars = _full_session(day)[:-1]
    quality = inspect_minute_session(_bar(day, volume=Decimal("239")), bars)
    assert quality.usable is False
    assert "SESSION_CLOSE_MISSING" in quality.issues


def test_duplicate_minute_is_not_usable() -> None:
    day = date(2026, 7, 30)
    bars = _full_session(day)
    quality = inspect_minute_session(_bar(day, volume=Decimal("241")), [*bars, bars[0]])
    assert quality.usable is False
    assert "DUPLICATE_MINUTE" in quality.issues


def test_daily_minute_price_conflict_is_not_usable() -> None:
    day = date(2026, 7, 30)
    quality = inspect_minute_session(
        _bar(day, value=Decimal("11"), volume=Decimal("240")), _full_session(day)
    )
    assert quality.usable is False
    assert "DAILY_OPEN_MISMATCH" in quality.issues


def test_minute_outside_ashare_session_is_not_usable() -> None:
    day = date(2026, 7, 30)
    bars = [*_full_session(day), _minute(day, time(12, 0))]
    quality = inspect_minute_session(_bar(day, volume=Decimal("241")), bars)
    assert quality.usable is False
    assert "OUTSIDE_ASHARE_SESSION" in quality.issues


def test_standard_sse_price_limits_are_derived_from_previous_close() -> None:
    assert _reliable_price_limits(_instrument(), date(2026, 7, 30), Decimal("10"), 100) == (
        Decimal("11.00"),
        Decimal("9.00"),
    )


def test_chinext_and_bse_use_their_reliable_board_limits() -> None:
    chinext = _instrument(symbol="300088", exchange="SZSE")
    bse = _instrument(symbol="920001", exchange="BSE")
    assert _reliable_price_limits(chinext, date(2026, 7, 30), Decimal("10"), 100) == (
        Decimal("12.00"),
        Decimal("8.00"),
    )
    assert _reliable_price_limits(bse, date(2026, 7, 30), Decimal("10"), 100) == (
        Decimal("13.00"),
        Decimal("7.00"),
    )


def test_st_and_new_listing_limits_are_not_guessed() -> None:
    st = _instrument(name="ST示例", metadata={"is_st": True})
    new = _instrument(listed_at=date(2026, 7, 28))
    assert _reliable_price_limits(st, date(2026, 7, 30), Decimal("10"), 100) == (None, None)
    assert _reliable_price_limits(new, date(2026, 7, 30), Decimal("10"), 2) == (None, None)


def test_explicit_historical_price_limits_take_precedence() -> None:
    instrument = _instrument(
        metadata={
            "price_limits": {
                "2026-07-30": {"upper": "10.55", "lower": "9.45"},
            }
        }
    )
    assert _reliable_price_limits(instrument, date(2026, 7, 30), Decimal("10"), 100) == (
        Decimal("10.55"),
        Decimal("9.45"),
    )


def test_one_price_limit_up_blocks_buy_but_not_sell() -> None:
    minute = _minute(date(2026, 7, 30), time(10, 0), price=Decimal("11"))
    assert _limit_locked_available_volume(
        order=_order(OrderSide.BUY),
        minute_bar=minute,
        ordinary_available_volume=Decimal("1000"),
        price_limit_up=Decimal("11"),
        price_limit_down=Decimal("9"),
    ) == Decimal("0")
    assert _limit_locked_available_volume(
        order=_order(OrderSide.SELL),
        minute_bar=minute,
        ordinary_available_volume=Decimal("1000"),
        price_limit_up=Decimal("11"),
        price_limit_down=Decimal("9"),
    ) == Decimal("1000")


def test_one_price_limit_down_blocks_sell_but_not_buy() -> None:
    minute = _minute(date(2026, 7, 30), time(10, 0), price=Decimal("9"))
    assert _limit_locked_available_volume(
        order=_order(OrderSide.SELL),
        minute_bar=minute,
        ordinary_available_volume=Decimal("1000"),
        price_limit_up=Decimal("11"),
        price_limit_down=Decimal("9"),
    ) == Decimal("0")
    assert _limit_locked_available_volume(
        order=_order(OrderSide.BUY),
        minute_bar=minute,
        ordinary_available_volume=Decimal("1000"),
        price_limit_up=Decimal("11"),
        price_limit_down=Decimal("9"),
    ) == Decimal("1000")


def test_intraday_configuration_round_trip_and_fingerprint() -> None:
    configured = _configuration()
    restored = backtest_configuration_from_dict(backtest_configuration_to_dict(configured))
    assert restored.signal_timeframe is MarketTimeframe.MINUTE_1
    assert restored.auto_prepare_minute_data is True
    assert restored.optimistic_fill_assumption is False
    assert backtest_request_fingerprint(restored) == backtest_request_fingerprint(configured)


def test_signal_close_requires_explicit_optimistic_assumption() -> None:
    with pytest.raises(BacktestError, match="optimistic_fill_assumption"):
        replace(
            _configuration(),
            execution_price_mode=BacktestExecutionPriceMode.INTRADAY_SIGNAL_CLOSE,
        )
    optimistic = replace(
        _configuration(),
        execution_price_mode=BacktestExecutionPriceMode.INTRADAY_SIGNAL_CLOSE,
        optimistic_fill_assumption=True,
    )
    assert optimistic.optimistic_fill_assumption is True


def _bar_date(bar: StrategyBar) -> date:
    return bar.timestamp.astimezone(ASHARE_TIMEZONE).date()
