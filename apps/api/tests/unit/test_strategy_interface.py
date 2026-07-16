from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from alphadesk_domain.enums import MarketTimeframe, OrderSide, SignalType
from alphadesk_domain.strategy import (
    SignalDraft,
    StrategyBar,
    StrategyContext,
    StrategyEnvironment,
    StrategyError,
    StrategyMetadata,
    StrategyParameterDefinition,
    StrategyParameterType,
    StrategyRegistry,
    validate_strategy_parameters,
)
from alphadesk_domain.strategy_examples import (
    SMA_CROSSOVER_METADATA,
    SmaCrossoverStrategy,
    register_builtin_strategies,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 16, 8, tzinfo=UTC)
INSTRUMENT_ID = uuid4()


def context(parameters=None, *, current_time=NOW) -> StrategyContext:
    return StrategyContext(
        strategy_key="sma_crossover",
        strategy_version="1.0.0",
        run_id=uuid4(),
        current_time=current_time,
        parameters=parameters or {},
        environment=StrategyEnvironment.RESEARCH,
    )


def bar(price_text: str, index: int = 0, **changes) -> StrategyBar:
    price = Decimal(price_text)
    values = {
        "instrument_id": INSTRUMENT_ID,
        "symbol": "600000",
        "exchange": "SSE",
        "timeframe": MarketTimeframe.DAY_1,
        "timestamp": datetime(2026, 7, 1, tzinfo=UTC) + timedelta(days=index),
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": Decimal("1000"),
        "amount": Decimal("10000"),
    }
    values.update(changes)
    return StrategyBar(**values)


def draft(**changes) -> SignalDraft:
    values = {
        "strategy_key": "sma_crossover",
        "strategy_version": "1.0.0",
        "instrument_id": INSTRUMENT_ID,
        "signal_type": SignalType.ENTRY,
        "side": OrderSide.BUY,
        "generated_at": NOW,
        "bar_timestamp": NOW,
        "quantity": Decimal("100"),
        "reference_price": Decimal("10"),
        "confidence": Decimal("0.8"),
        "reason": "test signal",
        "metadata": {"source": "unit"},
    }
    values.update(changes)
    return SignalDraft(**values)


def test_context_requires_aware_datetime_and_normalizes_to_utc() -> None:
    with pytest.raises(StrategyError) as error:
        context(current_time=datetime(2026, 7, 16, 8))
    assert error.value.code == "STRATEGY_INVALID_CONTEXT"

    china_time = datetime(2026, 7, 16, 16, tzinfo=timezone(timedelta(hours=8)))
    assert context(current_time=china_time).current_time == NOW
    assert context(current_time=china_time).current_time.tzinfo is UTC


def test_context_parameters_are_read_only_but_state_uses_explicit_mutator() -> None:
    strategy_context = context({"window": 5})
    with pytest.raises(TypeError):
        strategy_context.parameters["window"] = 10  # type: ignore[index]
    strategy_context.set_state("prices", [Decimal("1")])
    assert strategy_context.get_state("prices") == [Decimal("1")]
    with pytest.raises(TypeError):
        strategy_context.state["prices"] = []  # type: ignore[index]
    with pytest.raises(AttributeError):
        strategy_context._current_time = NOW + timedelta(days=1)  # type: ignore[misc]


@pytest.mark.parametrize("field_name", ("open", "high", "low", "close", "volume", "amount"))
def test_strategy_bar_rejects_float(field_name: str) -> None:
    with pytest.raises(StrategyError) as error:
        bar("10", **{field_name: 10.0})
    assert error.value.code == "STRATEGY_INVALID_BAR"


@pytest.mark.parametrize(
    "changes",
    (
        {"open": Decimal("11"), "high": Decimal("10")},
        {"close": Decimal("9"), "low": Decimal("10")},
    ),
)
def test_strategy_bar_validates_ohlc_relationships(changes) -> None:
    with pytest.raises(StrategyError, match=r"high|low"):
        bar("10", **changes)


def test_strategy_bar_rejects_negative_volume_and_normalizes_timestamp() -> None:
    with pytest.raises(StrategyError, match="volume"):
        bar("10", volume=Decimal("-1"))
    china_time = datetime(2026, 7, 1, 8, tzinfo=timezone(timedelta(hours=8)))
    assert bar("10", timestamp=china_time).timestamp == datetime(2026, 7, 1, tzinfo=UTC)


def test_signal_draft_validates_exclusive_sizing_and_confidence() -> None:
    with pytest.raises(StrategyError, match="mutually exclusive"):
        draft(target_weight=Decimal("0.5"))
    with pytest.raises(StrategyError, match="confidence"):
        draft(confidence=Decimal("1.01"))


def test_signal_draft_rejects_float_and_unsafe_metadata() -> None:
    with pytest.raises(StrategyError, match="Decimal"):
        draft(quantity=100.0)
    with pytest.raises(StrategyError, match="JSON-safe"):
        draft(metadata={"invalid": object()})
    with pytest.raises(StrategyError, match="JSON-safe"):
        draft(metadata={"decimal_must_be_serialized": Decimal("1")})


def test_signal_draft_is_immutable_and_reference_price_is_only_data() -> None:
    signal = draft()
    with pytest.raises(FrozenInstanceError):
        signal.quantity = Decimal("200")  # type: ignore[misc]
    assert signal.reference_price == Decimal("10")
    assert not hasattr(signal, "order_id")


def definitions() -> tuple[StrategyParameterDefinition, ...]:
    return (
        StrategyParameterDefinition(
            name="count",
            parameter_type=StrategyParameterType.INTEGER,
            required=False,
            default=5,
            description="count",
            min_value=1,
            max_value=10,
        ),
        StrategyParameterDefinition(
            name="threshold",
            parameter_type=StrategyParameterType.DECIMAL,
            required=True,
            description="threshold",
            min_value=Decimal("0"),
        ),
        StrategyParameterDefinition(
            name="enabled",
            parameter_type=StrategyParameterType.BOOLEAN,
            required=False,
            default=True,
            description="enabled",
        ),
        StrategyParameterDefinition(
            name="label",
            parameter_type=StrategyParameterType.STRING,
            required=False,
            default="demo",
            description="label",
        ),
        StrategyParameterDefinition(
            name="mode",
            parameter_type=StrategyParameterType.ENUM,
            required=False,
            default="fast",
            description="mode",
            choices=("fast", "slow"),
        ),
    )


def test_parameter_validation_applies_defaults_and_returns_read_only_mapping() -> None:
    result = validate_strategy_parameters(definitions(), {"threshold": Decimal("0.5")})
    assert result == {
        "count": 5,
        "enabled": True,
        "label": "demo",
        "mode": "fast",
        "threshold": Decimal("0.5"),
    }
    with pytest.raises(TypeError):
        result["count"] = 6  # type: ignore[index]


def test_parameter_validation_rejects_missing_unknown_range_enum_and_float() -> None:
    with pytest.raises(StrategyError, match="threshold"):
        validate_strategy_parameters(definitions(), {})
    with pytest.raises(StrategyError) as unknown:
        validate_strategy_parameters(definitions(), {"threshold": Decimal("1"), "mystery": "x"})
    assert unknown.value.code == "STRATEGY_UNKNOWN_PARAMETER"
    with pytest.raises(StrategyError, match="count"):
        validate_strategy_parameters(definitions(), {"threshold": Decimal("1"), "count": 11})
    with pytest.raises(StrategyError, match="mode"):
        validate_strategy_parameters(definitions(), {"threshold": Decimal("1"), "mode": "invalid"})
    with pytest.raises(StrategyError, match="threshold"):
        validate_strategy_parameters(definitions(), {"threshold": 0.5})


def test_registry_registers_lists_and_creates_independent_instances() -> None:
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    first = registry.create_instance("sma_crossover", {"short_window": 2, "long_window": 3})
    second = registry.create_instance("sma_crossover", {"short_window": 2, "long_window": 3})
    assert isinstance(first, SmaCrossoverStrategy)
    assert first is not second
    assert registry.get("sma_crossover") == SMA_CROSSOVER_METADATA


def test_registry_rejects_duplicate_and_missing_strategies() -> None:
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    with pytest.raises(StrategyError) as duplicate:
        register_builtin_strategies(registry)
    assert duplicate.value.code == "STRATEGY_ALREADY_REGISTERED"
    with pytest.raises(StrategyError) as missing:
        registry.create_instance("missing")
    assert missing.value.code == "STRATEGY_NOT_FOUND"


def test_registry_metadata_order_is_stable_and_unregister_is_controlled() -> None:
    second_metadata = StrategyMetadata(
        strategy_key="alpha_demo",
        display_name="Alpha",
        description="Stable sorting test strategy.",
        version="1.0.0",
        supported_timeframes=(MarketTimeframe.DAY_1,),
    )
    registry = StrategyRegistry(allow_unregister=True)
    register_builtin_strategies(registry)
    registry.register(second_metadata, (), lambda _: NoSignalStrategy(second_metadata))
    assert [item.strategy_key for item in registry.list_metadata()] == [
        "alpha_demo",
        "sma_crossover",
    ]
    registry.unregister("alpha_demo")
    assert [item.strategy_key for item in registry.list_metadata()] == ["sma_crossover"]


class NoSignalStrategy:
    def __init__(self, metadata: StrategyMetadata) -> None:
        self.metadata = metadata

    def initialize(self, strategy_context: StrategyContext) -> None:
        del strategy_context

    def on_bar(self, strategy_context: StrategyContext, strategy_bar: StrategyBar):
        del strategy_context, strategy_bar
        return []

    def finalize(self, strategy_context: StrategyContext) -> None:
        del strategy_context


def sma_strategy() -> SmaCrossoverStrategy:
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    result = registry.create_instance(
        "sma_crossover",
        {"short_window": 2, "long_window": 3, "quantity": Decimal("100")},
    )
    assert isinstance(result, SmaCrossoverStrategy)
    return result


def run_prices(prices: list[str]) -> list[SignalDraft]:
    strategy = sma_strategy()
    strategy_context = context()
    strategy.initialize(strategy_context)
    signals = []
    for index, price in enumerate(prices):
        signals.extend(strategy.on_bar(strategy_context, bar(price, index)))
    strategy.finalize(strategy_context)
    return signals


def test_sma_parameter_relationship_is_validated() -> None:
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    with pytest.raises(StrategyError, match="short_window"):
        registry.create_instance("sma_crossover", {"short_window": 3, "long_window": 3})
    with pytest.raises(StrategyError, match="quantity"):
        SmaCrossoverStrategy({"quantity": Decimal("0")})


def test_sma_direct_construction_applies_defaults() -> None:
    strategy = SmaCrossoverStrategy({})
    strategy_context = context()
    strategy.initialize(strategy_context)
    assert strategy.on_bar(strategy_context, bar("10")) == []


def test_sma_insufficient_data_emits_no_signal() -> None:
    assert run_prices(["3", "2", "1"]) == []


def test_sma_upward_cross_emits_one_buy_without_repetition() -> None:
    signals = run_prices(["3", "2", "1", "4", "5"])
    assert len(signals) == 1
    assert signals[0].side is OrderSide.BUY
    assert signals[0].signal_type is SignalType.ENTRY
    assert signals[0].reference_price == Decimal("4")
    assert "upward" in signals[0].reason


def test_sma_downward_cross_emits_one_sell() -> None:
    signals = run_prices(["3", "2", "1", "4", "5", "0.5"])
    assert [item.side for item in signals] == [OrderSide.BUY, OrderSide.SELL]
    assert signals[-1].signal_type is SignalType.EXIT
    assert "downward" in signals[-1].reason


def test_sma_same_inputs_produce_same_signal_sequence() -> None:
    first = run_prices(["3", "2", "1", "4", "5", "0.5"])
    second = run_prices(["3", "2", "1", "4", "5", "0.5"])

    def comparable(items: list[SignalDraft]):
        return [
            (item.side, item.signal_type, item.bar_timestamp, item.reference_price, item.reason)
            for item in items
        ]

    assert comparable(first) == comparable(second)


def test_sma_rejects_out_of_order_bars_and_never_creates_orders() -> None:
    strategy = sma_strategy()
    strategy_context = context()
    strategy.initialize(strategy_context)
    strategy.on_bar(strategy_context, bar("1", 1))
    with pytest.raises(StrategyError) as error:
        strategy.on_bar(strategy_context, bar("2", 0))
    assert error.value.code == "STRATEGY_INVALID_BAR"
    assert "Order" not in {type(item).__name__ for item in run_prices(["3", "2", "1", "4"])}


def test_strategy_modules_have_no_infrastructure_dependencies() -> None:
    domain_root = Path(__file__).parents[2] / "src" / "alphadesk_domain"
    source = "\n".join(
        (domain_root / name).read_text(encoding="utf-8")
        for name in ("strategy.py", "strategy_examples.py")
    ).lower()
    for forbidden in (
        "fastapi",
        "sqlalchemy",
        "redis",
        "broker",
        "miniqmt",
        "order_service",
        "unit_of_work",
    ):
        assert forbidden not in source
