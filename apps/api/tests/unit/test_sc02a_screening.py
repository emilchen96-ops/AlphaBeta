from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.screening import (
    ConditionOutcome,
    RankingDirection,
    RankingRule,
    RuleBasedScreeningEngine,
    ScreeningCondition,
    ScreeningError,
    ScreeningFeatureStore,
    ScreeningSpec,
    UniverseSpec,
    builtin_condition_catalog,
    screening_templates,
)
from alphadesk_domain.strategy import StrategyBar

AS_OF = date(2026, 7, 22)


def instrument(
    symbol: str = "600000",
    exchange: str = "SSE",
    *,
    metadata: dict[str, object] | None = None,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        exchange=exchange,
        market="CN_A",
        name="测试股票",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
        metadata=metadata or {},
    )


def bar(
    item: Instrument,
    day: date,
    *,
    open_price: str = "10",
    high: str = "10.2",
    low: str = "9.8",
    close: str = "10",
    volume: str = "100",
) -> StrategyBar:
    return StrategyBar(
        instrument_id=item.id,
        symbol=item.symbol,
        exchange=item.exchange,
        timeframe=MarketTimeframe.DAY_1,
        timestamp=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        amount=Decimal(close) * Decimal(volume),
    )


def spec(key: str, parameters: dict[str, object] | None = None) -> ScreeningSpec:
    return ScreeningSpec(
        schema_version=1,
        name="测试筛选",
        origin="UNIT_TEST",
        universe_spec=UniverseSpec(),
        as_of_date=AS_OF,
        timeframe=MarketTimeframe.DAY_1,
        conditions=(ScreeningCondition(condition_key=key, parameters=parameters or {}),),
        ranking_rules=(RankingRule(field="score", direction=RankingDirection.DESC),),
        price_adjustment_mode=PriceAdjustmentMode.RAW,
    )


def limit_bars(item: Instrument, ratio: Decimal) -> list[StrategyBar]:
    days = [AS_OF - timedelta(days=29 - index) for index in range(30)]
    values = [bar(item, day) for day in days]
    event_index = 23
    upper = (Decimal("10") * (Decimal("1") + ratio)).quantize(Decimal("0.01"))
    values[event_index] = bar(
        item,
        days[event_index],
        open_price="10",
        high=str(upper),
        low="10",
        close=str(upper),
        volume="1000",
    )
    values[-1] = bar(
        item,
        days[-1],
        open_price="10.00",
        high="10.20",
        low="9.90",
        close="10.10",
        volume="400",
    )
    return values


def bottom_bars(item: Instrument) -> list[StrategyBar]:
    values: list[StrategyBar] = []
    for index in range(61):
        day = AS_OF - timedelta(days=61 - index)
        values.append(
            bar(
                item,
                day,
                open_price="14",
                high=("20" if index == 10 else "15"),
                low=("10" if index == 20 else "12"),
                close="14",
                volume="100",
            )
        )
    values.append(
        bar(
            item,
            AS_OF,
            open_price="11.5",
            high="12",
            low="11",
            close="11.9",
            volume="235",
        )
    )
    return values


def first_board_failed_next_day_bars(
    item: Instrument, *, consolidation_days: int = 3
) -> tuple[list[date], list[StrategyBar]]:
    history_length = consolidation_days + 7
    days = [AS_OF - timedelta(days=history_length - 1 - index) for index in range(history_length)]
    values = [bar(item, day) for day in days]
    first_board_offset = -(consolidation_days + 2)
    failed_board_offset = -(consolidation_days + 1)
    values[first_board_offset] = bar(
        item,
        days[first_board_offset],
        open_price="10.2",
        high="11",
        low="10.2",
        close="11",
        volume="1000",
    )
    values[failed_board_offset] = bar(
        item,
        days[failed_board_offset],
        open_price="11",
        high="11.5",
        low="10.5",
        close="10.8",
        volume="800",
    )
    for index, offset in enumerate(range(-consolidation_days, 0)):
        volume = str(600 - (index * 100))
        values[offset] = bar(
            item,
            days[offset],
            open_price="10.8",
            high="11.2",
            low="10.3",
            close="10.7",
            volume=volume,
        )
    return days, values


def first_board_engine(days: list[date]) -> RuleBasedScreeningEngine:
    return RuleBasedScreeningEngine(
        builtin_condition_catalog(),
        ScreeningFeatureStore(market_sessions=days),
    )


def test_catalog_has_required_standard_conditions_and_chinese_templates() -> None:
    catalog = builtin_condition_catalog()
    keys = {item.condition_key for item in catalog.list()}
    assert {
        "N_DAY_HIGH_BREAKOUT",
        "N_DAY_LOW",
        "SMA_RELATION",
        "EMA_RELATION",
        "AVERAGE_VOLUME",
        "VOLUME_RATIO",
        "N_DAY_RETURN",
        "RANGE_POSITION",
        "BULLISH_CANDLE",
        "AMOUNT_THRESHOLD",
        "TRADING_STATUS",
        "LIMIT_UP_PULLBACK",
        "FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK",
        "BOTTOM_VOLUME_EXPANSION",
        "LIMIT_UP_ANCHOR_DISTANCE",
        "LIMIT_UP_ANCHOR_FLOOR",
        "LIMIT_UP_VOLUME_RATIO",
    } <= keys
    definition = catalog.get("BOTTOM_VOLUME_EXPANSION")
    assert definition.history_bars(definition.validate_parameters({})) == 61
    assert "当前位于" in definition.explanation_template
    recent_limit = catalog.get("RECENT_LIMIT_UP_EVENT")
    assert recent_limit.validate_parameters({})["minimum_occurrences"] == 1


def test_catalog_rejects_unknown_condition_and_invalid_parameters() -> None:
    catalog = builtin_condition_catalog()
    with pytest.raises(ScreeningError, match="未知条件"):
        catalog.get("EXECUTE_PYTHON")
    with pytest.raises(ScreeningError, match="低于允许范围"):
        catalog.validate("LIMIT_UP_PULLBACK", {"lookback_days": 0})
    with pytest.raises(ScreeningError, match="未知参数"):
        catalog.validate("LIMIT_UP_PULLBACK", {"sql": "select * from orders"})


def test_screening_spec_rejects_unsafe_content_and_non_raw_prices() -> None:
    with pytest.raises(ScreeningError, match="禁止字段"):
        ScreeningSpec(
            schema_version=1,
            name="unsafe",
            origin="UNIT_TEST",
            universe_spec=UniverseSpec(),
            as_of_date=AS_OF,
            timeframe=MarketTimeframe.DAY_1,
            conditions=(ScreeningCondition(condition_key="BULLISH_CANDLE"),),
            exclusions={"python": "import os"},
        )
    with pytest.raises(ScreeningError, match="仅支持不复权"):
        ScreeningSpec(
            schema_version=1,
            name="qfq",
            origin="UNIT_TEST",
            universe_spec=UniverseSpec(),
            as_of_date=AS_OF,
            timeframe=MarketTimeframe.DAY_1,
            conditions=(ScreeningCondition(condition_key="BULLISH_CANDLE"),),
            price_adjustment_mode=PriceAdjustmentMode.QFQ,
        )


@pytest.mark.parametrize(
    ("symbol", "exchange", "ratio"),
    (
        ("600000", "SSE", Decimal("0.10")),
        ("300001", "SZSE", Decimal("0.20")),
        ("688001", "SSE", Decimal("0.20")),
        ("920001", "BSE", Decimal("0.30")),
    ),
)
def test_limit_up_pullback_supports_main_chinext_star_and_bse(
    symbol: str, exchange: str, ratio: Decimal
) -> None:
    item = instrument(symbol, exchange)
    outcome = RuleBasedScreeningEngine(builtin_condition_catalog()).evaluate_instrument(
        spec("LIMIT_UP_PULLBACK"), item, limit_bars(item, ratio)
    )
    assert outcome.outcome is ConditionOutcome.MATCHED
    assert outcome.candidate is not None
    assert outcome.candidate.metrics["previous_close_before_limit_up"] == "10"
    assert outcome.candidate.metrics["volume_ratio"] == "0.4"
    assert "当前价格未跌破保护价" in outcome.candidate.reason


def test_limit_up_pullback_uses_latest_valid_event_and_exact_anchor() -> None:
    item = instrument()
    bars = limit_bars(item, Decimal("0.10"))
    earlier = len(bars) - 12
    bars[earlier] = bar(
        item,
        bars[earlier].timestamp.date(),
        high="11",
        low="10",
        close="11",
        volume="2000",
    )
    outcome = RuleBasedScreeningEngine(builtin_condition_catalog()).evaluate_instrument(
        spec("LIMIT_UP_PULLBACK"), item, bars
    )
    assert outcome.candidate is not None
    assert outcome.candidate.metrics["limit_up_date"] == bars[-7].timestamp.date().isoformat()
    assert outcome.candidate.metrics["protection_price"] == "9.8"


def test_limit_up_pullback_marks_st_without_reliable_limit_as_indeterminate() -> None:
    item = instrument(metadata={"is_st": True})
    outcome = RuleBasedScreeningEngine(builtin_condition_catalog()).evaluate_instrument(
        spec("LIMIT_UP_PULLBACK"), item, limit_bars(item, Decimal("0.05"))
    )
    assert outcome.outcome is ConditionOutcome.INDETERMINATE
    assert outcome.reason_code == "LIMIT_PRICE_NOT_AVAILABLE"


def test_limit_up_pullback_enforces_distance_protection_and_volume() -> None:
    item = instrument()
    engine = RuleBasedScreeningEngine(builtin_condition_catalog())
    too_far = limit_bars(item, Decimal("0.10"))
    too_far[-1] = bar(
        item,
        AS_OF,
        open_price="10.3",
        high="10.5",
        low="10.2",
        close="10.4",
        volume="400",
    )
    assert engine.evaluate_instrument(spec("LIMIT_UP_PULLBACK"), item, too_far).reason_code == (
        "ANCHOR_DISTANCE_EXCEEDED"
    )
    too_low = limit_bars(item, Decimal("0.10"))
    too_low[-1] = bar(
        item,
        AS_OF,
        open_price="9.8",
        high="9.85",
        low="9.7",
        close="9.79",
        volume="400",
    )
    assert engine.evaluate_instrument(spec("LIMIT_UP_PULLBACK"), item, too_low).reason_code == (
        "PROTECTION_PRICE_BROKEN"
    )
    too_much_volume = limit_bars(item, Decimal("0.10"))
    too_much_volume[-1] = bar(
        item,
        AS_OF,
        open_price="10",
        high="10.2",
        low="9.9",
        close="10.1",
        volume="501",
    )
    assert (
        engine.evaluate_instrument(spec("LIMIT_UP_PULLBACK"), item, too_much_volume).reason_code
        == "PULLBACK_VOLUME_TOO_HIGH"
    )


def test_first_board_failed_next_day_pullback_matches_exact_common_session_pattern() -> None:
    item = instrument()
    days, bars = first_board_failed_next_day_bars(item)
    outcome = first_board_engine(days).evaluate_instrument(
        spec("FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK"), item, bars
    )
    assert outcome.outcome is ConditionOutcome.MATCHED
    assert outcome.candidate is not None
    assert outcome.candidate.metrics["first_board_date"] == days[-5].isoformat()
    assert outcome.candidate.metrics["failed_board_date"] == days[-4].isoformat()
    assert outcome.candidate.metrics["reference_high"] == "11.5"
    assert outcome.candidate.metrics["volume_ratio"] == "0.4"
    assert "随后3个共同交易日" in outcome.candidate.reason


def test_first_board_failed_next_day_pullback_supports_four_session_window() -> None:
    item = instrument()
    days, bars = first_board_failed_next_day_bars(item, consolidation_days=4)
    screening_spec = spec(
        "FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK",
        parameters={"consolidation_days": 4},
    )
    outcome = first_board_engine(days).evaluate_instrument(screening_spec, item, bars)
    assert outcome.outcome is ConditionOutcome.MATCHED
    assert outcome.candidate is not None
    assert outcome.candidate.metrics["first_board_date"] == days[-6].isoformat()
    assert outcome.candidate.metrics["failed_board_date"] == days[-5].isoformat()
    assert outcome.candidate.metrics["pullback_start_date"] == days[-4].isoformat()
    assert outcome.candidate.metrics["pullback_end_date"] == days[-1].isoformat()
    assert outcome.candidate.metrics["consolidation_days"] == 4
    assert "随后4个共同交易日" in outcome.candidate.reason


def test_first_board_failed_next_day_pullback_history_window_follows_parameter() -> None:
    definition = builtin_condition_catalog().get("FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK")
    parameters = definition.validate_parameters({"consolidation_days": 4})
    assert definition.history_bars(parameters) == 7


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    (
        ("prior_limit", "NOT_FIRST_LIMIT_UP_BOARD"),
        ("next_day_limit", "NEXT_DAY_NOT_FAILED_BOARD"),
        ("break_first_low", "FIRST_BOARD_LOW_BROKEN"),
        ("exceed_reference_high", "REFERENCE_HIGH_EXCEEDED"),
        ("volume_too_high", "PULLBACK_VOLUME_TOO_HIGH"),
    ),
)
def test_first_board_failed_next_day_pullback_rejects_each_broken_leg(
    mutation: str, reason_code: str
) -> None:
    item = instrument()
    days, bars = first_board_failed_next_day_bars(item)
    if mutation == "prior_limit":
        bars[-7] = bar(item, days[-7], open_price="9.09", high="9.2", low="9", close="9.09")
        bars[-6] = bar(item, days[-6], high="10", low="9.09", close="10", volume="900")
    elif mutation == "next_day_limit":
        bars[-4] = bar(
            item,
            days[-4],
            open_price="11",
            high="12.1",
            low="11",
            close="12.1",
            volume="800",
        )
    elif mutation == "break_first_low":
        bars[-2] = bar(
            item,
            days[-2],
            open_price="10.7",
            high="11",
            low="10.19",
            close="10.7",
            volume="400",
        )
    elif mutation == "exceed_reference_high":
        bars[-2] = bar(
            item,
            days[-2],
            open_price="10.7",
            high="11.51",
            low="10.3",
            close="10.7",
            volume="400",
        )
    else:
        bars[-1] = bar(
            item,
            days[-1],
            open_price="10.7",
            high="11",
            low="10.3",
            close="10.7",
            volume="501",
        )
    outcome = first_board_engine(days).evaluate_instrument(
        spec("FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK"), item, bars
    )
    assert outcome.outcome is ConditionOutcome.NOT_MATCHED
    assert outcome.reason_code == reason_code


def test_first_board_failed_next_day_pullback_does_not_shift_missing_common_session() -> None:
    item = instrument()
    days, bars = first_board_failed_next_day_bars(item)
    bars = [entry for entry in bars if entry.timestamp.date() != days[-2]]
    outcome = first_board_engine(days).evaluate_instrument(
        spec("FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK"), item, bars
    )
    assert outcome.outcome is ConditionOutcome.INDETERMINATE
    assert outcome.reason_code == "FIRST_BOARD_PATTERN_BAR_MISSING"


def test_first_board_failed_next_day_pullback_requires_reliable_limit_price() -> None:
    item = instrument(metadata={"is_st": True})
    days, bars = first_board_failed_next_day_bars(item)
    outcome = first_board_engine(days).evaluate_instrument(
        spec("FIRST_BOARD_FAILED_NEXT_DAY_PULLBACK"), item, bars
    )
    assert outcome.outcome is ConditionOutcome.INDETERMINATE
    assert outcome.reason_code == "LIMIT_PRICE_NOT_AVAILABLE"


def test_bottom_volume_expansion_excludes_current_bar_and_explains_result() -> None:
    item = instrument()
    outcome = RuleBasedScreeningEngine(builtin_condition_catalog()).evaluate_instrument(
        spec("BOTTOM_VOLUME_EXPANSION"), item, bottom_bars(item)
    )
    assert outcome.outcome is ConditionOutcome.MATCHED
    assert outcome.candidate is not None
    assert outcome.candidate.metrics["rolling_high_60"] == "20"
    assert outcome.candidate.metrics["rolling_low_60"] == "10"
    assert outcome.candidate.metrics["average_volume_20"] == "100"
    assert outcome.candidate.metrics["volume_multiple"] == "2.35"
    assert outcome.candidate.metrics["bullish_candle"] is True
    assert "2.35倍" in outcome.candidate.reason


def test_bottom_volume_expansion_handles_zero_range_and_insufficient_data() -> None:
    item = instrument()
    flat = [
        bar(item, AS_OF - timedelta(days=60 - index), high="10", low="10") for index in range(61)
    ]
    engine = RuleBasedScreeningEngine(builtin_condition_catalog())
    zero = engine.evaluate_instrument(spec("BOTTOM_VOLUME_EXPANSION"), item, flat)
    assert zero.outcome is ConditionOutcome.INDETERMINATE
    assert zero.reason_code == "RANGE_POSITION_ZERO_DENOMINATOR"
    insufficient = engine.evaluate_instrument(spec("BOTTOM_VOLUME_EXPANSION"), item, flat[:20])
    assert insufficient.outcome is ConditionOutcome.INSUFFICIENT_DATA


def test_screening_never_uses_bars_after_as_of_date() -> None:
    item = instrument()
    bars = bottom_bars(item)
    bars.append(
        bar(
            item,
            AS_OF + timedelta(days=1),
            open_price="100",
            high="200",
            low="1",
            close="150",
            volume="999999",
        )
    )
    outcome = RuleBasedScreeningEngine(builtin_condition_catalog()).evaluate_instrument(
        spec("BOTTOM_VOLUME_EXPANSION"), item, bars
    )
    assert outcome.candidate is not None
    assert outcome.candidate.reference_price == Decimal("11.9")
    assert outcome.candidate.metrics["market_data_time"].startswith(AS_OF.isoformat())


def test_volume_multiple_ranking_is_descending_and_stable() -> None:
    catalog = builtin_condition_catalog()
    engine = RuleBasedScreeningEngine(catalog)
    run_spec = ScreeningSpec(
        schema_version=1,
        name="底部放倍量",
        origin="UNIT_TEST",
        universe_spec=UniverseSpec(),
        as_of_date=AS_OF,
        timeframe=MarketTimeframe.DAY_1,
        conditions=(ScreeningCondition(condition_key="BOTTOM_VOLUME_EXPANSION"),),
        ranking_rules=(RankingRule(field="volume_multiple"),),
        top_n=2,
    )
    candidates = []
    for symbol, volume in (("600003", "300"), ("600001", "250"), ("600002", "250")):
        item = instrument(symbol)
        bars = bottom_bars(item)
        bars[-1] = bar(
            item,
            AS_OF,
            open_price="11.5",
            high="12",
            low="11",
            close="11.9",
            volume=volume,
        )
        result = engine.evaluate_instrument(run_spec, item, bars)
        assert result.candidate is not None
        candidates.append(result.candidate)
    ranked = engine.rank(run_spec, candidates)
    assert [item.symbol for item in ranked] == ["600003", "600001"]


def test_templates_include_the_original_patterns_and_sc02c_standard_library() -> None:
    templates = screening_templates()
    assert [item.schema_version for item in templates[:2]] == [2, 2]
    assert templates[0].root_group is not None
    assert templates[1].root_group is not None
    assert [item.condition_key for item in templates[0].root_group.children] == [
        "RECENT_LIMIT_UP_EVENT",
        "LIMIT_UP_ANCHOR_DISTANCE",
        "LIMIT_UP_ANCHOR_FLOOR",
        "LIMIT_UP_VOLUME_RATIO",
    ]
    assert [item.condition_key for item in templates[1].root_group.children] == [
        "RANGE_POSITION",
        "VOLUME_RATIO",
        "BULLISH_CANDLE",
    ]
    assert len(templates) == 6
    assert all(item.universe_spec.universe_key == "ALL_A_SHARES" for item in templates)


def test_atomic_bottom_volume_template_matches_legacy_composite_semantics() -> None:
    item = instrument()
    bars = bottom_bars(item)
    engine = RuleBasedScreeningEngine(builtin_condition_catalog())
    legacy = engine.evaluate_instrument(spec("BOTTOM_VOLUME_EXPANSION"), item, bars)
    blocks = engine.evaluate_instrument(screening_templates()[1], item, bars)
    assert legacy.outcome is blocks.outcome is ConditionOutcome.MATCHED
    assert legacy.candidate is not None and blocks.candidate is not None
    assert blocks.candidate.metrics["range_position"] == legacy.candidate.metrics["range_position"]
    assert blocks.candidate.metrics["volume_ratio"] == legacy.candidate.metrics["volume_multiple"]
    assert blocks.candidate.metrics["bullish_candle"] is True


def test_atomic_limit_up_template_matches_legacy_composite_semantics() -> None:
    item = instrument()
    bars = limit_bars(item, Decimal("0.10"))
    engine = RuleBasedScreeningEngine(builtin_condition_catalog())
    legacy = engine.evaluate_instrument(spec("LIMIT_UP_PULLBACK"), item, bars)
    blocks = engine.evaluate_instrument(screening_templates()[0], item, bars)
    assert legacy.outcome is blocks.outcome is ConditionOutcome.MATCHED
    assert legacy.candidate is not None and blocks.candidate is not None
    assert blocks.candidate.metrics["limit_up_date"] == legacy.candidate.metrics["limit_up_date"]
    assert (
        blocks.candidate.metrics["distance_to_anchor"]
        == legacy.candidate.metrics["distance_to_anchor"]
    )
    assert blocks.candidate.metrics["volume_ratio"] == legacy.candidate.metrics["volume_ratio"]
    assert blocks.candidate.reason_code == "SCREENING_SPEC_MATCHED"
    assert len(blocks.candidate.reason_code) <= 64
