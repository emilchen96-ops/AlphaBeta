"""Explicitly registered S02-A strategies built from incremental indicators."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from alphadesk_domain.enums import MarketTimeframe, OrderSide, SignalType
from alphadesk_domain.indicators import (
    AverageTrueRange,
    ExponentialMovingAverage,
    RollingAverageVolume,
    RollingHighest,
    RollingLowest,
    SimpleMovingAverage,
)
from alphadesk_domain.strategy import (
    SignalDraft,
    StrategyBar,
    StrategyContext,
    StrategyError,
    StrategyMetadata,
    StrategyParameterDefinition,
    StrategyParameterType,
    StrategyParameterValue,
    StrategyRegistry,
    validate_strategy_parameters,
)

SUPPORTED_TIMEFRAMES = (
    MarketTimeframe.MINUTE_1,
    MarketTimeframe.MINUTE_5,
    MarketTimeframe.MINUTE_15,
    MarketTimeframe.MINUTE_30,
    MarketTimeframe.MINUTE_60,
    MarketTimeframe.DAY_1,
)


def _integer(parameters: Mapping[str, StrategyParameterValue], name: str) -> int:
    value = parameters[name]
    if type(value) is not int:
        raise StrategyError("STRATEGY_INVALID_PARAMETER", f"parameter '{name}' must be integer")
    return value


def _decimal(parameters: Mapping[str, StrategyParameterValue], name: str) -> Decimal:
    value = parameters[name]
    if not isinstance(value, Decimal):
        raise StrategyError("STRATEGY_INVALID_PARAMETER", f"parameter '{name}' must be Decimal")
    return value


def _check_bar(
    metadata: StrategyMetadata, last_timestamp: datetime | None, bar: StrategyBar
) -> None:
    if bar.timeframe not in metadata.supported_timeframes:
        raise StrategyError("STRATEGY_INVALID_BAR", f"timeframe '{bar.timeframe}' is not supported")
    if last_timestamp is not None and bar.timestamp <= last_timestamp:
        raise StrategyError("STRATEGY_INVALID_BAR", "bars must arrive in strictly increasing order")


def _signal(
    metadata: StrategyMetadata,
    context: StrategyContext,
    bar: StrategyBar,
    side: OrderSide,
    quantity: Decimal,
    reason: str,
) -> SignalDraft:
    return SignalDraft(
        strategy_key=metadata.strategy_key,
        strategy_version=metadata.version,
        instrument_id=bar.instrument_id,
        signal_type=SignalType.ENTRY if side is OrderSide.BUY else SignalType.EXIT,
        side=side,
        generated_at=context.current_time,
        bar_timestamp=bar.timestamp,
        quantity=quantity,
        reference_price=bar.close,
        reason=reason,
    )


VOLUME_BREAKOUT_METADATA = StrategyMetadata(
    strategy_key="volume_breakout",
    display_name="Volume Breakout",
    description="Requires a prior-window price breakout confirmed by relative volume.",
    version="1.0.0",
    supported_timeframes=SUPPORTED_TIMEFRAMES,
)
VOLUME_BREAKOUT_PARAMETERS = (
    StrategyParameterDefinition(
        name="breakout_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=20,
        min_value=2,
        description="Prior high lookback.",
    ),
    StrategyParameterDefinition(
        name="volume_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=20,
        min_value=2,
        description="Prior average-volume lookback.",
    ),
    StrategyParameterDefinition(
        name="volume_multiplier",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("1.5"),
        min_value=Decimal("0.00000001"),
        description="Minimum multiple of prior average volume.",
    ),
    StrategyParameterDefinition(
        name="exit_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=10,
        min_value=2,
        description="Prior low exit lookback.",
    ),
    StrategyParameterDefinition(
        name="quantity",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("100"),
        min_value=Decimal("0.00000001"),
        description="Reference signal quantity.",
    ),
)


@dataclass(slots=True)
class _VolumeState:
    highs: RollingHighest
    lows: RollingLowest
    volumes: RollingAverageVolume
    last_timestamp: datetime | None = None
    is_long: bool = False


class VolumeBreakoutStrategy:
    metadata = VOLUME_BREAKOUT_METADATA

    def __init__(self, parameters: Mapping[str, StrategyParameterValue]) -> None:
        values = validate_strategy_parameters(VOLUME_BREAKOUT_PARAMETERS, parameters)
        self._breakout_window = _integer(values, "breakout_window")
        self._volume_window = _integer(values, "volume_window")
        self._exit_window = _integer(values, "exit_window")
        self._volume_multiplier = _decimal(values, "volume_multiplier")
        self._quantity = _decimal(values, "quantity")
        if self._exit_window >= self._breakout_window:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", "exit_window must be below breakout_window"
            )

    def initialize(self, context: StrategyContext) -> None:
        context.set_state(self.metadata.strategy_key, {})

    def on_bar(self, context: StrategyContext, bar: StrategyBar) -> list[SignalDraft]:
        states = context.get_state(self.metadata.strategy_key)
        if not isinstance(states, dict):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy must be initialized first")
        state = states.setdefault(
            str(bar.instrument_id),
            _VolumeState(
                RollingHighest(self._breakout_window),
                RollingLowest(self._exit_window),
                RollingAverageVolume(self._volume_window),
            ),
        )
        if not isinstance(state, _VolumeState):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy state is invalid")
        _check_bar(self.metadata, state.last_timestamp, bar)
        prior_high, prior_low, prior_volume = (
            state.highs.value,
            state.lows.value,
            state.volumes.value,
        )
        side: OrderSide | None = None
        if (
            not state.is_long
            and prior_high is not None
            and prior_volume is not None
            and bar.close > prior_high
            and bar.volume >= prior_volume * self._volume_multiplier
        ):
            side = OrderSide.BUY
            state.is_long = True
        elif state.is_long and prior_low is not None and bar.close < prior_low:
            side = OrderSide.SELL
            state.is_long = False
        state.highs.update(bar.high)
        state.lows.update(bar.low)
        state.volumes.update(bar.volume)
        state.last_timestamp = bar.timestamp
        if side is None:
            return []
        reason = (
            f"volume breakout: prior_high={prior_high}, prior_low={prior_low}, "
            f"prior_average_volume={prior_volume}, volume_multiplier={self._volume_multiplier}, "
            f"close={bar.close}, volume={bar.volume}"
        )
        return [_signal(self.metadata, context, bar, side, self._quantity, reason)]

    def finalize(self, context: StrategyContext) -> None:
        del context


PRICE_VOLUME_BREAKOUT_SMA_EXIT_METADATA = StrategyMetadata(
    strategy_key="price_volume_breakout_sma_exit",
    display_name="Price-Volume Breakout with SMA Exit",
    description=(
        "Enters on a prior-window price breakout confirmed by relative volume "
        "and exits when the close falls below its simple moving average."
    ),
    version="1.0.0",
    supported_timeframes=(MarketTimeframe.DAY_1,),
)
PRICE_VOLUME_BREAKOUT_SMA_EXIT_PARAMETERS = (
    StrategyParameterDefinition(
        name="breakout_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=10,
        min_value=2,
        description="Prior high lookback.",
    ),
    StrategyParameterDefinition(
        name="volume_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=10,
        min_value=2,
        description="Prior average-volume lookback.",
    ),
    StrategyParameterDefinition(
        name="volume_multiplier",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("1.2"),
        min_value=Decimal("0.00000001"),
        description="Minimum multiple of prior average volume.",
    ),
    StrategyParameterDefinition(
        name="exit_sma_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=5,
        min_value=2,
        description="Simple moving-average exit window.",
    ),
    StrategyParameterDefinition(
        name="quantity",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("100"),
        min_value=Decimal("0.00000001"),
        description="Reference signal quantity.",
    ),
)


@dataclass(slots=True)
class _PriceVolumeSmaExitState:
    highs: RollingHighest
    volumes: RollingAverageVolume
    exit_sma: SimpleMovingAverage
    last_timestamp: datetime | None = None
    is_long: bool = False


class PriceVolumeBreakoutSmaExitStrategy:
    """Daily price-volume breakout with an inclusive-current-bar SMA exit."""

    metadata = PRICE_VOLUME_BREAKOUT_SMA_EXIT_METADATA

    def __init__(self, parameters: Mapping[str, StrategyParameterValue]) -> None:
        values = validate_strategy_parameters(PRICE_VOLUME_BREAKOUT_SMA_EXIT_PARAMETERS, parameters)
        self._breakout_window = _integer(values, "breakout_window")
        self._volume_window = _integer(values, "volume_window")
        self._volume_multiplier = _decimal(values, "volume_multiplier")
        self._exit_sma_window = _integer(values, "exit_sma_window")
        self._quantity = _decimal(values, "quantity")

    def initialize(self, context: StrategyContext) -> None:
        context.set_state(self.metadata.strategy_key, {})

    def on_bar(self, context: StrategyContext, bar: StrategyBar) -> list[SignalDraft]:
        states = context.get_state(self.metadata.strategy_key)
        if not isinstance(states, dict):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy must be initialized first")
        state = states.setdefault(
            str(bar.instrument_id),
            _PriceVolumeSmaExitState(
                RollingHighest(self._breakout_window),
                RollingAverageVolume(self._volume_window),
                SimpleMovingAverage(self._exit_sma_window),
            ),
        )
        if not isinstance(state, _PriceVolumeSmaExitState):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy state is invalid")
        _check_bar(self.metadata, state.last_timestamp, bar)

        prior_high = state.highs.value
        prior_volume = state.volumes.value
        exit_sma = state.exit_sma.update(bar.close)
        side: OrderSide | None = None
        if (
            not state.is_long
            and prior_high is not None
            and prior_volume is not None
            and bar.close > prior_high
            and bar.volume >= prior_volume * self._volume_multiplier
        ):
            side = OrderSide.BUY
            state.is_long = True
        elif state.is_long and exit_sma is not None and bar.close < exit_sma:
            side = OrderSide.SELL
            state.is_long = False

        state.highs.update(bar.high)
        state.volumes.update(bar.volume)
        state.last_timestamp = bar.timestamp
        if side is None:
            return []
        reason = (
            f"price-volume breakout with SMA exit: prior_high={prior_high}, "
            f"prior_average_volume={prior_volume}, volume_multiplier={self._volume_multiplier}, "
            f"exit_sma={exit_sma}, close={bar.close}, volume={bar.volume}"
        )
        return [_signal(self.metadata, context, bar, side, self._quantity, reason)]

    def finalize(self, context: StrategyContext) -> None:
        del context


TREND_PULLBACK_METADATA = StrategyMetadata(
    strategy_key="trend_pullback",
    display_name="Trend Pullback",
    description="Enters when price reclaims the fast EMA after a bounded pullback.",
    version="1.0.0",
    supported_timeframes=SUPPORTED_TIMEFRAMES,
)
TREND_PULLBACK_PARAMETERS = (
    StrategyParameterDefinition(
        name="fast_ema",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=10,
        min_value=2,
        description="Fast EMA window.",
    ),
    StrategyParameterDefinition(
        name="slow_ema",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=30,
        min_value=3,
        description="Slow EMA window.",
    ),
    StrategyParameterDefinition(
        name="pullback_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=5,
        min_value=2,
        description="Maximum bars from pullback to reclaim.",
    ),
    StrategyParameterDefinition(
        name="pullback_tolerance",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("0"),
        min_value=Decimal("0"),
        description="Non-negative ratio above fast EMA still treated as near.",
    ),
    StrategyParameterDefinition(
        name="quantity",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("100"),
        min_value=Decimal("0.00000001"),
        description="Reference signal quantity.",
    ),
)


@dataclass(slots=True)
class _PullbackState:
    fast: ExponentialMovingAverage
    slow: ExponentialMovingAverage
    last_timestamp: datetime | None = None
    pullback_age: int | None = None
    is_long: bool = False


class TrendPullbackStrategy:
    metadata = TREND_PULLBACK_METADATA

    def __init__(self, parameters: Mapping[str, StrategyParameterValue]) -> None:
        values = validate_strategy_parameters(TREND_PULLBACK_PARAMETERS, parameters)
        self._fast_window = _integer(values, "fast_ema")
        self._slow_window = _integer(values, "slow_ema")
        self._pullback_window = _integer(values, "pullback_window")
        self._tolerance = _decimal(values, "pullback_tolerance")
        self._quantity = _decimal(values, "quantity")
        if self._slow_window <= self._fast_window:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", "slow_ema must be greater than fast_ema"
            )

    def initialize(self, context: StrategyContext) -> None:
        context.set_state(self.metadata.strategy_key, {})

    def on_bar(self, context: StrategyContext, bar: StrategyBar) -> list[SignalDraft]:
        states = context.get_state(self.metadata.strategy_key)
        if not isinstance(states, dict):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy must be initialized first")
        state = states.setdefault(
            str(bar.instrument_id),
            _PullbackState(
                ExponentialMovingAverage(self._fast_window),
                ExponentialMovingAverage(self._slow_window),
            ),
        )
        if not isinstance(state, _PullbackState):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy state is invalid")
        _check_bar(self.metadata, state.last_timestamp, bar)
        fast, slow = state.fast.update(bar.close), state.slow.update(bar.close)
        state.last_timestamp = bar.timestamp
        if fast is None or slow is None:
            return []
        side: OrderSide | None = None
        if state.is_long and fast < slow:
            side = OrderSide.SELL
            state.is_long = False
            state.pullback_age = None
        elif fast > slow:
            if bar.close <= fast * (Decimal("1") + self._tolerance):
                state.pullback_age = 0
            elif state.pullback_age is not None:
                state.pullback_age += 1
                if (
                    state.pullback_age <= self._pullback_window
                    and not state.is_long
                    and bar.close > fast
                ):
                    side = OrderSide.BUY
                    state.is_long = True
                    state.pullback_age = None
                elif state.pullback_age > self._pullback_window:
                    state.pullback_age = None
        else:
            state.pullback_age = None
        if side is None:
            return []
        pullback_state = "reclaimed" if side is OrderSide.BUY else "trend_broken"
        reason = (
            f"trend pullback: fast_ema={fast}, slow_ema={slow}, pullback_state={pullback_state}"
        )
        return [_signal(self.metadata, context, bar, side, self._quantity, reason)]

    def finalize(self, context: StrategyContext) -> None:
        del context


ATR_CHANNEL_METADATA = StrategyMetadata(
    strategy_key="atr_channel",
    display_name="ATR Channel",
    description="Uses current-bar EMA and Wilder ATR to form dynamic trend channels.",
    version="1.0.0",
    supported_timeframes=SUPPORTED_TIMEFRAMES,
)
ATR_CHANNEL_PARAMETERS = (
    StrategyParameterDefinition(
        name="ema_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=20,
        min_value=2,
        description="Channel centre EMA window.",
    ),
    StrategyParameterDefinition(
        name="atr_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=14,
        min_value=2,
        description="Wilder ATR window.",
    ),
    StrategyParameterDefinition(
        name="entry_atr_multiplier",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("1.0"),
        min_value=Decimal("0.00000001"),
        description="Entry channel ATR multiple.",
    ),
    StrategyParameterDefinition(
        name="exit_atr_multiplier",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("1.0"),
        min_value=Decimal("0.00000001"),
        description="Exit channel ATR multiple.",
    ),
    StrategyParameterDefinition(
        name="quantity",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("100"),
        min_value=Decimal("0.00000001"),
        description="Reference signal quantity.",
    ),
)


@dataclass(slots=True)
class _AtrChannelState:
    ema: ExponentialMovingAverage
    atr: AverageTrueRange
    last_timestamp: datetime | None = None
    was_above_entry: bool | None = None
    is_long: bool = False


class AtrChannelStrategy:
    metadata = ATR_CHANNEL_METADATA

    def __init__(self, parameters: Mapping[str, StrategyParameterValue]) -> None:
        values = validate_strategy_parameters(ATR_CHANNEL_PARAMETERS, parameters)
        self._ema_window = _integer(values, "ema_window")
        self._atr_window = _integer(values, "atr_window")
        self._entry_multiplier = _decimal(values, "entry_atr_multiplier")
        self._exit_multiplier = _decimal(values, "exit_atr_multiplier")
        self._quantity = _decimal(values, "quantity")

    def initialize(self, context: StrategyContext) -> None:
        context.set_state(self.metadata.strategy_key, {})

    def on_bar(self, context: StrategyContext, bar: StrategyBar) -> list[SignalDraft]:
        states = context.get_state(self.metadata.strategy_key)
        if not isinstance(states, dict):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy must be initialized first")
        state = states.setdefault(
            str(bar.instrument_id),
            _AtrChannelState(
                ExponentialMovingAverage(self._ema_window), AverageTrueRange(self._atr_window)
            ),
        )
        if not isinstance(state, _AtrChannelState):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy state is invalid")
        _check_bar(self.metadata, state.last_timestamp, bar)
        # The current close/OHLC update EMA and ATR first; this bar is then compared to its channel.
        ema, atr = state.ema.update(bar.close), state.atr.update(bar.high, bar.low, bar.close)
        state.last_timestamp = bar.timestamp
        if ema is None or atr is None:
            return []
        upper = ema + self._entry_multiplier * atr
        lower = ema - self._exit_multiplier * atr
        above = bar.close > upper
        side: OrderSide | None = None
        if not state.is_long and state.was_above_entry is False and above:
            side = OrderSide.BUY
            state.is_long = True
        elif state.is_long and bar.close < lower:
            side = OrderSide.SELL
            state.is_long = False
        state.was_above_entry = above
        if side is None:
            return []
        reason = (
            f"ATR channel: ema={ema}, atr={atr}, entry_upper={upper}, "
            f"exit_lower={lower}, close={bar.close}"
        )
        return [_signal(self.metadata, context, bar, side, self._quantity, reason)]

    def finalize(self, context: StrategyContext) -> None:
        del context


def register_strategy_library(registry: StrategyRegistry) -> None:
    """Register S02-A built-ins explicitly and without global instances."""

    registry.register(VOLUME_BREAKOUT_METADATA, VOLUME_BREAKOUT_PARAMETERS, VolumeBreakoutStrategy)
    registry.register(
        PRICE_VOLUME_BREAKOUT_SMA_EXIT_METADATA,
        PRICE_VOLUME_BREAKOUT_SMA_EXIT_PARAMETERS,
        PriceVolumeBreakoutSmaExitStrategy,
    )
    registry.register(TREND_PULLBACK_METADATA, TREND_PULLBACK_PARAMETERS, TrendPullbackStrategy)
    registry.register(ATR_CHANNEL_METADATA, ATR_CHANNEL_PARAMETERS, AtrChannelStrategy)
