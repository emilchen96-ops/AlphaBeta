from decimal import Decimal

import pytest

from alphadesk_domain.strategy import (
    StrategyError,
    StrategyParameterDefinition,
    StrategyParameterType,
    StrategyRegistry,
)
from alphadesk_domain.strategy_examples import register_builtin_strategies
from alphadesk_domain.strategy_experiments import expand_parameter_grid

pytestmark = pytest.mark.unit


def definitions(strategy_key: str = "sma_crossover"):
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    return registry.get_parameter_definitions(strategy_key)


def test_single_parameter_grid_fills_strategy_defaults() -> None:
    result = expand_parameter_grid(definitions(), {"short_window": [5]})
    assert result == [{"long_window": 20, "quantity": "100", "short_window": 5}]


def test_cartesian_product_uses_definition_and_candidate_order() -> None:
    result = expand_parameter_grid(definitions(), {"short_window": [2, 3], "long_window": [5, 6]})
    assert [(item["short_window"], item["long_window"]) for item in result] == [
        (2, 5),
        (2, 6),
        (3, 5),
        (3, 6),
    ]


def test_duplicate_candidates_are_removed_without_reordering() -> None:
    result = expand_parameter_grid(definitions(), {"short_window": [3, 2, 3], "long_window": [5]})
    assert [item["short_window"] for item in result] == [3, 2]


def test_decimal_candidates_stay_decimal_until_stable_string_storage() -> None:
    result = expand_parameter_grid(
        definitions("volume_breakout"),
        {
            "breakout_window": [3],
            "volume_window": [2],
            "volume_multiplier": [Decimal("1.500")],
            "exit_window": [2],
        },
    )
    assert result[0]["volume_multiplier"] == "1.5"


@pytest.mark.parametrize(
    ("grid", "code"),
    [
        ({"missing": [1]}, "STRATEGY_EXPERIMENT_INVALID_GRID"),
        ({"short_window": []}, "STRATEGY_EXPERIMENT_EMPTY_GRID"),
        ({"short_window": [1.5]}, "STRATEGY_INVALID_PARAMETER"),
        ({"short_window": [0]}, "STRATEGY_INVALID_PARAMETER"),
    ],
)
def test_invalid_grids_are_controlled(grid, code: str) -> None:
    with pytest.raises(StrategyError) as captured:
        expand_parameter_grid(definitions(), grid)
    assert captured.value.code == code


def test_enum_boolean_and_string_candidates_are_supported() -> None:
    custom = (
        StrategyParameterDefinition(
            name="flag",
            parameter_type=StrategyParameterType.BOOLEAN,
            required=True,
            description="flag",
        ),
        StrategyParameterDefinition(
            name="label",
            parameter_type=StrategyParameterType.STRING,
            required=True,
            description="label",
        ),
        StrategyParameterDefinition(
            name="mode",
            parameter_type=StrategyParameterType.ENUM,
            required=True,
            description="mode",
            choices=("fast", "slow"),
        ),
    )
    result = expand_parameter_grid(
        custom, {"flag": [True, False], "label": ["x"], "mode": ["fast", "slow"]}
    )
    assert len(result) == 4
    assert result[0] == {"flag": True, "label": "x", "mode": "fast"}


def test_empty_supplied_grid_uses_all_defaults() -> None:
    assert len(expand_parameter_grid(definitions(), {})) == 1


def test_missing_required_parameter_fails() -> None:
    custom = (
        StrategyParameterDefinition(
            name="required_value",
            parameter_type=StrategyParameterType.INTEGER,
            required=True,
            description="required",
        ),
    )
    with pytest.raises(StrategyError, match="required"):
        expand_parameter_grid(custom, {})
