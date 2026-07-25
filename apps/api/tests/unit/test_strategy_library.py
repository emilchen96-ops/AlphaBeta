from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_domain.enums import MarketTimeframe, OrderSide
from alphadesk_domain.strategy import (
    SignalDraft,
    StrategyBar,
    StrategyContext,
    StrategyEnvironment,
    StrategyError,
    StrategyRegistry,
)
from alphadesk_domain.strategy_examples import register_builtin_strategies
from alphadesk_domain.strategy_library import (
    AtrChannelStrategy,
    PriceVolumeBreakoutSmaExitStrategy,
    TrendPullbackStrategy,
    VolumeBreakoutStrategy,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 7, 1, tzinfo=UTC)
INSTRUMENT = uuid4()


def make_bar(
    close: str, index: int, *, volume: str = "100", high: str | None = None, low: str | None = None
) -> StrategyBar:
    price = Decimal(close)
    return StrategyBar(
        instrument_id=INSTRUMENT,
        symbol="600000",
        exchange="SSE",
        timeframe=MarketTimeframe.DAY_1,
        timestamp=NOW + timedelta(days=index),
        open=price,
        high=Decimal(high) if high else price + Decimal("1"),
        low=Decimal(low) if low else price - Decimal("1"),
        close=price,
        volume=Decimal(volume),
    )


def run(strategy_key: str, parameters: dict, bars: list[StrategyBar]) -> list[SignalDraft]:
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    strategy = registry.create_instance(strategy_key, parameters)
    context = StrategyContext(
        strategy_key=strategy.metadata.strategy_key,
        strategy_version=strategy.metadata.version,
        run_id=uuid4(),
        current_time=NOW,
        parameters=parameters,
        environment=StrategyEnvironment.RESEARCH,
    )
    strategy.initialize(context)
    signals: list[SignalDraft] = []
    for item in bars:
        context.advance_time(item.timestamp)
        signals.extend(strategy.on_bar(context, item))
    strategy.finalize(context)
    return signals


def volume_bars() -> list[StrategyBar]:
    return [
        make_bar("10", 0, high="11", low="9"),
        make_bar("11", 1, high="12", low="10"),
        make_bar("11.5", 2, high="12", low="10.5"),
        make_bar("12.5", 3, volume="200", high="13", low="12"),
        make_bar("13", 4, volume="250", high="14", low="12.5"),
        make_bar("9", 5, high="10", low="8"),
    ]


VOLUME_PARAMS = {
    "breakout_window": 3,
    "volume_window": 2,
    "exit_window": 2,
    "volume_multiplier": Decimal("1.5"),
    "quantity": Decimal("100"),
}


def test_registry_catalog_contains_all_s02_strategies_and_instances_are_isolated() -> None:
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    assert {item.strategy_key for item in registry.list_metadata()} >= {
        "price_volume_breakout_sma_exit",
        "volume_breakout",
        "trend_pullback",
        "atr_channel",
    }
    assert registry.create_instance(
        "volume_breakout", VOLUME_PARAMS
    ) is not registry.create_instance("volume_breakout", VOLUME_PARAMS)


@pytest.mark.parametrize(
    ("key", "parameters", "message"),
    [
        ("volume_breakout", {**VOLUME_PARAMS, "exit_window": 3}, "exit_window"),
        ("trend_pullback", {"fast_ema": 3, "slow_ema": 3}, "slow_ema"),
    ],
)
def test_cross_parameter_validation(key: str, parameters: dict, message: str) -> None:
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    with pytest.raises(StrategyError, match=message):
        registry.create_instance(key, parameters)


def test_volume_breakout_requires_both_prior_high_and_volume_confirmation() -> None:
    no_volume = [
        *volume_bars()[:3],
        make_bar("12.5", 3, volume="100", high="13", low="12"),
    ]
    no_price = [
        *volume_bars()[:3],
        make_bar("11.5", 3, volume="200", high="12", low="11"),
    ]
    assert run("volume_breakout", VOLUME_PARAMS, no_volume) == []
    assert run("volume_breakout", VOLUME_PARAMS, no_price) == []


def test_volume_breakout_uses_prior_bars_and_emits_single_buy_then_sell() -> None:
    signals = run("volume_breakout", VOLUME_PARAMS, volume_bars())
    assert [signal.side for signal in signals] == [OrderSide.BUY, OrderSide.SELL]
    assert signals[0].reference_price == Decimal("12.5")
    assert "prior_high=12" in signals[0].reason and "volume_multiplier=1.5" in signals[0].reason


def test_volume_breakout_can_reenter_after_exit() -> None:
    bars = [
        *volume_bars(),
        make_bar("10", 6),
        make_bar("11", 7),
        make_bar("12", 8),
        make_bar("14", 9, volume="300", high="15", low="13"),
    ]
    assert [item.side for item in run("volume_breakout", VOLUME_PARAMS, bars)] == [
        OrderSide.BUY,
        OrderSide.SELL,
        OrderSide.BUY,
    ]


PRICE_VOLUME_SMA_PARAMS = {
    "breakout_window": 3,
    "volume_window": 2,
    "volume_multiplier": Decimal("1.5"),
    "exit_sma_window": 3,
    "quantity": Decimal("100"),
}


def test_price_volume_breakout_sma_exit_uses_prior_entry_windows_and_current_sma() -> None:
    bars = [
        make_bar("10", 0, high="10", volume="100"),
        make_bar("10", 1, high="10", volume="100"),
        make_bar("10", 2, high="10", volume="100"),
        make_bar("12", 3, high="12", volume="200"),
        make_bar("12", 4, high="12", volume="100"),
        make_bar("9", 5, high="9", volume="100"),
    ]

    signals = run("price_volume_breakout_sma_exit", PRICE_VOLUME_SMA_PARAMS, bars)

    assert [item.side for item in signals] == [OrderSide.BUY, OrderSide.SELL]
    assert "prior_high=10" in signals[0].reason
    assert "exit_sma=11" in signals[1].reason


def test_price_volume_breakout_sma_exit_requires_daily_bars() -> None:
    bar = replace(make_bar("10", 0), timeframe=MarketTimeframe.MINUTE_1)

    with pytest.raises(StrategyError, match="not supported"):
        run("price_volume_breakout_sma_exit", PRICE_VOLUME_SMA_PARAMS, [bar])


TREND_PARAMS = {
    "fast_ema": 2,
    "slow_ema": 3,
    "pullback_window": 3,
    "pullback_tolerance": Decimal("0"),
    "quantity": Decimal("100"),
}


def test_trend_pullback_needs_trend_and_pullback_then_reclaim() -> None:
    no_pullback = [
        make_bar(value, index) for index, value in enumerate(("10", "11", "12", "13", "14"))
    ]
    assert run("trend_pullback", TREND_PARAMS, no_pullback) == []
    bars = [make_bar(value, index) for index, value in enumerate(("10", "11", "12", "11", "13"))]
    signals = run("trend_pullback", TREND_PARAMS, bars)
    assert [item.side for item in signals] == [OrderSide.BUY]
    assert "pullback_state=reclaimed" in signals[0].reason


def test_trend_pullback_does_not_repeat_and_exits_on_ema_trend_break() -> None:
    bars = [
        make_bar(value, index)
        for index, value in enumerate(("10", "11", "12", "11", "13", "14", "8", "7"))
    ]
    assert [item.side for item in run("trend_pullback", TREND_PARAMS, bars)] == [
        OrderSide.BUY,
        OrderSide.SELL,
    ]


ATR_PARAMS = {
    "ema_window": 2,
    "atr_window": 2,
    "entry_atr_multiplier": Decimal("0.2"),
    "exit_atr_multiplier": Decimal("0.2"),
    "quantity": Decimal("100"),
}


def test_atr_channel_waits_for_indicators_and_requires_crossing() -> None:
    assert run("atr_channel", ATR_PARAMS, [make_bar("10", 0)]) == []
    flat = [make_bar("10", index) for index in range(4)]
    assert run("atr_channel", ATR_PARAMS, flat) == []


def test_atr_channel_current_bar_order_emits_one_buy_then_sell_deterministically() -> None:
    bars = [
        make_bar(value, index) for index, value in enumerate(("10", "10", "10", "14", "15", "7"))
    ]
    first = run("atr_channel", ATR_PARAMS, bars)
    second = run("atr_channel", ATR_PARAMS, bars)
    assert [item.side for item in first] == [OrderSide.BUY, OrderSide.SELL]
    assert [(item.side, item.reason) for item in first] == [
        (item.side, item.reason) for item in second
    ]


@pytest.mark.parametrize(
    ("strategy_type", "parameters"),
    [
        (VolumeBreakoutStrategy, VOLUME_PARAMS),
        (PriceVolumeBreakoutSmaExitStrategy, PRICE_VOLUME_SMA_PARAMS),
        (TrendPullbackStrategy, TREND_PARAMS),
        (AtrChannelStrategy, ATR_PARAMS),
    ],
)
def test_strategies_emit_only_signal_drafts(strategy_type, parameters) -> None:
    strategy = strategy_type(parameters)
    assert not hasattr(strategy, "repository") and not hasattr(strategy, "order_service")
    assert all(
        type(item) is SignalDraft
        for item in run(strategy.metadata.strategy_key, parameters, volume_bars())
    )


def test_strategy_rejects_out_of_order_bars() -> None:
    with pytest.raises(StrategyError, match=r"backwards|increasing"):
        run("volume_breakout", VOLUME_PARAMS, [make_bar("10", 1), make_bar("11", 0)])
