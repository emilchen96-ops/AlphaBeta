from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from alphadesk_api.application.screenings import screening_spec_from_snapshot
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.screening import (
    ConditionGroupOperator,
    ConditionOutcome,
    RuleBasedScreeningEngine,
    ScreeningCondition,
    ScreeningConditionGroup,
    ScreeningError,
    ScreeningFeatureStore,
    ScreeningSpec,
    UniverseSpec,
    builtin_condition_catalog,
)
from alphadesk_domain.screening_specs import (
    NaturalLanguageScreeningParser,
    screening_spec_from_mapping,
)
from alphadesk_domain.strategy import StrategyBar

AS_OF = date(2026, 7, 29)


def _instrument() -> Instrument:
    return Instrument(
        symbol="600000",
        exchange="SSE",
        market="CN_A",
        name="测试股票",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
    )


def _bars(item: Instrument, *, amount: Decimal = Decimal("6000000000")):
    values = []
    for index in range(10):
        day = AS_OF - timedelta(days=9 - index)
        close = Decimal("11") if index == 7 else Decimal("10")
        values.append(
            StrategyBar(
                instrument_id=item.id,
                symbol=item.symbol,
                exchange=item.exchange,
                timeframe=MarketTimeframe.DAY_1,
                timestamp=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
                open=Decimal("10"),
                high=max(close, Decimal("10.2")),
                low=Decimal("9.8"),
                close=close,
                volume=Decimal("100"),
                amount=amount,
            )
        )
    return values


def _condition(key: str, parameters: dict[str, object] | None = None):
    return ScreeningCondition(condition_key=key, parameters=parameters or {})


def _v2(root: ScreeningConditionGroup) -> ScreeningSpec:
    return ScreeningSpec(
        schema_version=2,
        name="SC03-A测试",
        origin="UNIT_TEST",
        universe_spec=UniverseSpec(),
        as_of_date=AS_OF,
        timeframe=MarketTimeframe.DAY_1,
        root_group=root,
        price_adjustment_mode=PriceAdjustmentMode.RAW,
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    (
        ("成交额", "AMOUNT_THRESHOLD"),
        ("成交金额", "AMOUNT_THRESHOLD"),
        ("流动性", "AMOUNT_THRESHOLD"),
        ("近5日涨停", "RECENT_LIMIT_UP_EVENT"),
        ("近期涨停", "RECENT_LIMIT_UP_EVENT"),
        ("涨停次数", "RECENT_LIMIT_UP_EVENT"),
        ("均线", "SMA_RELATION"),
        ("EMA", "EMA_RELATION"),
        ("放量", "VOLUME_RATIO"),
        ("倍量", "VOLUME_RATIO"),
        ("突破", "N_DAY_HIGH_BREAKOUT"),
        ("新低", "N_DAY_LOW"),
        ("收益率", "N_DAY_RETURN"),
        ("阳线", "BULLISH_CANDLE"),
        ("停牌", "TRADING_STATUS"),
    ),
)
def test_catalog_search_aliases(query: str, expected: str) -> None:
    keys = {item.condition_key for item in builtin_condition_catalog().search(query=query)}
    assert expected in keys


@pytest.mark.parametrize(
    ("key", "parameter", "invalid"),
    (
        ("RECENT_LIMIT_UP_EVENT", "lookback_days", 0),
        ("RECENT_LIMIT_UP_EVENT", "lookback_days", 251),
        ("RECENT_LIMIT_UP_EVENT", "minimum_occurrences", 0),
        ("RECENT_LIMIT_UP_EVENT", "minimum_occurrences", 51),
        ("AMOUNT_THRESHOLD", "minimum_amount", -1),
        ("VOLUME_RATIO", "minimum_ratio", -1),
        ("N_DAY_HIGH_BREAKOUT", "window", 0),
        ("N_DAY_LOW", "window", 501),
        ("SMA_RELATION", "short_window", 0),
        ("RANGE_POSITION", "maximum_position", 2),
    ),
)
def test_parameter_boundaries_are_rejected(key: str, parameter: str, invalid: object) -> None:
    with pytest.raises(ScreeningError):
        builtin_condition_catalog().validate(key, {parameter: invalid})


def test_rich_parameter_metadata_is_exposed() -> None:
    catalog = builtin_condition_catalog()
    amount = catalog.get("AMOUNT_THRESHOLD").parameter_schema[0].response_dict()
    lookback = catalog.get("RECENT_LIMIT_UP_EVENT").parameter_schema[0].response_dict()
    assert amount["type"] == "amount"
    assert amount["display_unit"] == "亿元"
    assert amount["precision"] == 2
    assert lookback["type"] == "trading_day_window"
    assert lookback["placeholder"] == "例如 5"


def test_v1_flat_conditions_remain_implicit_and() -> None:
    spec = ScreeningSpec(
        schema_version=1,
        name="旧方案",
        origin="UNIT_TEST",
        universe_spec=UniverseSpec(),
        as_of_date=AS_OF,
        timeframe=MarketTimeframe.DAY_1,
        conditions=(_condition("BULLISH_CANDLE"), _condition("AMOUNT_THRESHOLD")),
    )
    validated = spec.validate(builtin_condition_catalog())
    assert validated.root_group.operator is ConditionGroupOperator.AND
    assert len(validated.conditions) == 2


def test_v2_snapshot_round_trip() -> None:
    catalog = builtin_condition_catalog()
    spec = _v2(
        ScreeningConditionGroup(
            operator=ConditionGroupOperator.OR,
            children=(
                _condition("BULLISH_CANDLE"),
                ScreeningConditionGroup(
                    operator=ConditionGroupOperator.AND,
                    children=(_condition("AMOUNT_THRESHOLD", {"minimum_amount": "5000000000"}),),
                ),
            ),
        )
    )
    snapshot = spec.snapshot(catalog)
    restored = screening_spec_from_mapping(snapshot, catalog)
    assert restored.schema_version == 2
    assert restored.root_group is not None
    assert restored.root_group.operator is ConditionGroupOperator.OR


def test_worker_restores_persisted_v2_snapshot_with_nested_groups() -> None:
    catalog = builtin_condition_catalog()
    spec = _v2(
        ScreeningConditionGroup(
            operator=ConditionGroupOperator.OR,
            children=(
                _condition("BULLISH_CANDLE"),
                ScreeningConditionGroup(
                    operator=ConditionGroupOperator.AND,
                    children=(
                        _condition(
                            "AMOUNT_THRESHOLD",
                            {"minimum_amount": "5000000000"},
                        ),
                        _condition("N_DAY_HIGH_BREAKOUT", {"window": 20}),
                    ),
                ),
            ),
        )
    )

    restored = screening_spec_from_snapshot(spec.snapshot(catalog))

    assert restored.schema_version == 2
    assert restored.conditions == ()
    assert restored.root_group is not None
    assert restored.root_group.operator is ConditionGroupOperator.OR
    assert len(restored.validate(catalog).conditions) == 3


def test_and_group_requires_every_condition() -> None:
    item = _instrument()
    root = ScreeningConditionGroup(
        operator=ConditionGroupOperator.AND,
        children=(
            _condition("BULLISH_CANDLE"),
            _condition("AMOUNT_THRESHOLD", {"minimum_amount": "5000000000"}),
        ),
    )
    outcome = RuleBasedScreeningEngine(builtin_condition_catalog()).evaluate_instrument(
        _v2(root), item, _bars(item)
    )
    assert outcome.outcome is ConditionOutcome.NOT_MATCHED


def test_or_group_matches_when_one_branch_matches() -> None:
    item = _instrument()
    root = ScreeningConditionGroup(
        operator=ConditionGroupOperator.OR,
        children=(
            _condition("BULLISH_CANDLE"),
            _condition("AMOUNT_THRESHOLD", {"minimum_amount": "5000000000"}),
        ),
    )
    outcome = RuleBasedScreeningEngine(builtin_condition_catalog()).evaluate_instrument(
        _v2(root), item, _bars(item)
    )
    assert outcome.outcome is ConditionOutcome.MATCHED
    assert outcome.candidate is not None
    details = outcome.candidate.metrics["condition_evaluations"]
    assert isinstance(details, list)
    assert len(details) == 2


def test_recent_limit_up_and_amount_matches() -> None:
    item = _instrument()
    sessions = [AS_OF - timedelta(days=9 - index) for index in range(10)]
    root = ScreeningConditionGroup(
        operator=ConditionGroupOperator.AND,
        children=(
            _condition(
                "RECENT_LIMIT_UP_EVENT",
                {
                    "lookback_days": 5,
                    "minimum_occurrences": 1,
                    "event_selection": "LATEST_VALID",
                    "require_reliable_limit_price": True,
                },
            ),
            _condition("AMOUNT_THRESHOLD", {"minimum_amount": "5000000000"}),
        ),
    )
    engine = RuleBasedScreeningEngine(
        builtin_condition_catalog(),
        ScreeningFeatureStore(market_sessions=sessions),
    )
    outcome = engine.evaluate_instrument(_v2(root), item, _bars(item))
    assert outcome.outcome is ConditionOutcome.MATCHED
    assert outcome.candidate is not None
    assert outcome.candidate.metrics["limit_up_occurrences"] == 1


def test_recent_limit_up_unknown_price_is_indeterminate() -> None:
    item = _instrument()
    item.name = "ST测试"
    root = ScreeningConditionGroup(
        operator=ConditionGroupOperator.AND,
        children=(_condition("RECENT_LIMIT_UP_EVENT"),),
    )
    outcome = RuleBasedScreeningEngine(builtin_condition_catalog()).evaluate_instrument(
        _v2(root), item, _bars(item)
    )
    assert outcome.outcome is ConditionOutcome.INDETERMINATE


def test_group_depth_over_three_is_rejected() -> None:
    leaf = ScreeningConditionGroup(
        operator=ConditionGroupOperator.AND,
        children=(_condition("BULLISH_CANDLE"),),
    )
    nested = leaf
    for _ in range(3):
        nested = ScreeningConditionGroup(
            operator=ConditionGroupOperator.AND,
            children=(nested,),
        )
    with pytest.raises(ScreeningError, match="3层"):
        _v2(nested)


def test_more_than_twenty_atoms_is_rejected() -> None:
    root = ScreeningConditionGroup(
        operator=ConditionGroupOperator.AND,
        children=tuple(_condition("BULLISH_CANDLE") for _ in range(21)),
    )
    with pytest.raises(ScreeningError, match="20"):
        _v2(root)


def test_empty_group_is_rejected() -> None:
    with pytest.raises(ScreeningError, match="至少需要一个"):
        ScreeningConditionGroup(operator=ConditionGroupOperator.AND, children=())


@pytest.mark.parametrize(
    ("text", "keys", "value"),
    (
        (
            "近5日出现过涨停的个股,并且最近一个交易日成交额大于50亿元",
            {"RECENT_LIMIT_UP_EVENT", "AMOUNT_THRESHOLD"},
            5,
        ),
        ("近10日涨停", {"RECENT_LIMIT_UP_EVENT"}, 10),
        ("过去20天内有涨停", {"RECENT_LIMIT_UP_EVENT"}, 20),
        ("成交额20亿元", {"AMOUNT_THRESHOLD"}, None),
    ),
)
def test_phrase_prefill_parser(text: str, keys: set[str], value: int | None) -> None:
    result = NaturalLanguageScreeningParser(builtin_condition_catalog()).parse(
        text,
        as_of_date=AS_OF,
    )
    assert result.spec is not None
    assert {item.condition_key for item in result.spec.conditions} == keys
    if value is not None:
        recent = next(
            item for item in result.spec.conditions if item.condition_key == "RECENT_LIMIT_UP_EVENT"
        )
        assert recent.parameters["lookback_days"] == value
    if "AMOUNT_THRESHOLD" in keys:
        amount = next(
            item for item in result.spec.conditions if item.condition_key == "AMOUNT_THRESHOLD"
        )
        expected = "5000000000" if "50亿" in text else "2000000000"
        assert amount.parameters["minimum_amount"] == expected


@pytest.mark.parametrize("operator", (ConditionGroupOperator.AND, ConditionGroupOperator.OR))
def test_nested_group_validation_flattens_data_requirements(
    operator: ConditionGroupOperator,
) -> None:
    root = ScreeningConditionGroup(
        operator=operator,
        children=(
            _condition("AMOUNT_THRESHOLD"),
            ScreeningConditionGroup(
                operator=ConditionGroupOperator.AND,
                children=(_condition("RECENT_LIMIT_UP_EVENT"),),
            ),
        ),
    )
    validated = _v2(root).validate(builtin_condition_catalog())
    assert {item.definition.condition_key for item in validated.conditions} == {
        "AMOUNT_THRESHOLD",
        "RECENT_LIMIT_UP_EVENT",
    }
    assert validated.required_history_bars == 7
