"""Explicitly registered, deterministic example strategies."""

from collections.abc import Mapping
from decimal import Decimal

from alphadesk_domain.enums import MarketTimeframe, OrderSide, SignalType
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

SMA_CROSSOVER_METADATA = StrategyMetadata(
    strategy_key="sma_crossover",
    display_name="SMA Crossover",
    description="Emits one signal when short and long Decimal moving averages cross.",
    version="1.0.0",
    supported_timeframes=(
        MarketTimeframe.MINUTE_1,
        MarketTimeframe.MINUTE_5,
        MarketTimeframe.MINUTE_15,
        MarketTimeframe.MINUTE_30,
        MarketTimeframe.MINUTE_60,
        MarketTimeframe.DAY_1,
    ),
    parameter_schema_version=1,
)

SMA_CROSSOVER_PARAMETERS = (
    StrategyParameterDefinition(
        name="short_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=5,
        description="Number of closing prices in the short moving average.",
        min_value=1,
    ),
    StrategyParameterDefinition(
        name="long_window",
        parameter_type=StrategyParameterType.INTEGER,
        required=False,
        default=20,
        description="Number of closing prices in the long moving average.",
        min_value=2,
    ),
    StrategyParameterDefinition(
        name="quantity",
        parameter_type=StrategyParameterType.DECIMAL,
        required=False,
        default=Decimal("100"),
        description="Reference signal quantity; it is not an order quantity.",
        min_value=Decimal("0.00000001"),
    ),
)


class SmaCrossoverStrategy:
    metadata = SMA_CROSSOVER_METADATA

    def __init__(self, parameters: Mapping[str, StrategyParameterValue]) -> None:
        validated = validate_strategy_parameters(SMA_CROSSOVER_PARAMETERS, parameters)
        short_window = validated["short_window"]
        long_window = validated["long_window"]
        quantity = validated["quantity"]
        if type(short_window) is not int or type(long_window) is not int:
            raise StrategyError("STRATEGY_INVALID_PARAMETER", "SMA windows must be integers")
        if not isinstance(quantity, Decimal):
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", "parameter 'quantity' must be Decimal"
            )
        self._short_window = short_window
        self._long_window = long_window
        self._quantity = quantity
        if self._short_window >= self._long_window:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER",
                "parameter 'short_window' must be less than 'long_window'",
            )

    @staticmethod
    def _state_key(bar: StrategyBar) -> str:
        return str(bar.instrument_id)

    def initialize(self, context: StrategyContext) -> None:
        context.set_state("sma_crossover", {})

    def on_bar(self, context: StrategyContext, bar: StrategyBar) -> list[SignalDraft]:
        if bar.timeframe not in self.metadata.supported_timeframes:
            raise StrategyError(
                "STRATEGY_INVALID_BAR", f"timeframe '{bar.timeframe}' is not supported"
            )
        raw_state = context.get_state("sma_crossover")
        if not isinstance(raw_state, dict):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy must be initialized first")
        instrument_state = raw_state.setdefault(
            self._state_key(bar), {"closes": [], "last_timestamp": None, "relation": None}
        )
        if not isinstance(instrument_state, dict):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy state is invalid")
        last_timestamp = instrument_state["last_timestamp"]
        if last_timestamp is not None and bar.timestamp <= last_timestamp:
            raise StrategyError(
                "STRATEGY_INVALID_BAR", "bars must arrive in strictly increasing time order"
            )
        closes = instrument_state["closes"]
        if not isinstance(closes, list):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "strategy close window is invalid")
        closes.append(bar.close)
        if len(closes) > self._long_window:
            del closes[0]
        instrument_state["last_timestamp"] = bar.timestamp
        if len(closes) < self._long_window:
            return []

        short_average = sum(closes[-self._short_window :], Decimal("0")) / Decimal(
            self._short_window
        )
        long_average = sum(closes, Decimal("0")) / Decimal(self._long_window)
        relation = (short_average > long_average) - (short_average < long_average)
        previous_relation = instrument_state["relation"]
        instrument_state["relation"] = relation
        if previous_relation is None:
            return []

        side: OrderSide | None = None
        signal_type: SignalType | None = None
        direction = ""
        if previous_relation <= 0 and relation > 0:
            side = OrderSide.BUY
            signal_type = SignalType.ENTRY
            direction = "upward"
        elif previous_relation >= 0 and relation < 0:
            side = OrderSide.SELL
            signal_type = SignalType.EXIT
            direction = "downward"
        if side is None or signal_type is None:
            return []

        return [
            SignalDraft(
                strategy_key=self.metadata.strategy_key,
                strategy_version=self.metadata.version,
                instrument_id=bar.instrument_id,
                signal_type=signal_type,
                side=side,
                generated_at=context.current_time,
                bar_timestamp=bar.timestamp,
                quantity=self._quantity,
                reference_price=bar.close,
                reason=(f"SMA {direction} crossover: short={short_average}, long={long_average}"),
                metadata={
                    "short_window": self._short_window,
                    "long_window": self._long_window,
                    "direction": direction,
                },
            )
        ]

    def finalize(self, context: StrategyContext) -> None:
        del context


def register_builtin_strategies(registry: StrategyRegistry) -> None:
    """Register trusted built-ins without import-time global side effects."""

    registry.register(
        SMA_CROSSOVER_METADATA,
        SMA_CROSSOVER_PARAMETERS,
        SmaCrossoverStrategy,
    )
