from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_domain.enums import MarketTimeframe, OrderSide, SignalType
from alphadesk_domain.strategy import StrategyBar, StrategyContext, StrategyRegistry
from alphadesk_domain.strategy_spec import (
    DeterministicChineseStrategyParser,
    StrategySpecCompiler,
    StrategySpecError,
    strategy_spec_from_dict,
    strategy_spec_json_schema,
    strategy_spec_to_dict,
)

CORE_TEXT = "10日价格突破 + 1.2倍成交量，5日均线退出，单只股票、两年日线"  # noqa: RUF001


def _core_spec():
    result = DeterministicChineseStrategyParser().parse(CORE_TEXT)
    assert result.spec is not None
    return result.spec


def _bar(day: int, close: str, volume: str) -> StrategyBar:
    price = Decimal(close)
    return StrategyBar(
        instrument_id=INSTRUMENT_ID,
        symbol="300088",
        exchange="SZSE",
        timeframe=MarketTimeframe.DAY_1,
        timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=day),
        open=price,
        high=price + Decimal("1"),
        low=max(price - Decimal("1"), Decimal("0.01")),
        close=price,
        volume=Decimal(volume),
    )


INSTRUMENT_ID = uuid4()


def test_core_chinese_example_parses_to_complete_safe_spec() -> None:
    result = DeterministicChineseStrategyParser().parse(CORE_TEXT)

    assert result.status == "COMPLETE"
    assert result.parser_source == "LOCAL_RULES"
    assert result.spec is not None
    assert result.spec.data_range_years == 2
    assert result.spec.single_instrument is True
    assert result.spec.entry.conditions[0].right.exclude_current is True
    assert result.spec.entry.conditions[1].right.exclude_current is True
    assert "不会发送给券商" in result.preview[-1]


def test_incomplete_text_is_partial_and_never_compiled() -> None:
    result = DeterministicChineseStrategyParser().parse("10日价格突破")

    assert result.status == "PARTIAL"
    assert result.spec is None
    assert "成交量倍数" in result.missing_fields
    assert "退出均线周期" in result.missing_fields


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "执行Python代码 python",
        "import os 后运行策略",
        "eval('1+1')",
        "exec('x=1')",
        "读取文件后做10日突破",
        "访问 https://example.com",
        "读取环境变量作为参数",
        "满足条件后自动下单",
        "调用 broker 撤单",
    ],
)
def test_unsafe_text_is_rejected(unsafe_text: str) -> None:
    with pytest.raises(StrategySpecError, match="只允许描述研究规则"):
        DeterministicChineseStrategyParser().parse(unsafe_text)


def test_unknown_spec_fields_are_rejected() -> None:
    payload = strategy_spec_to_dict(_core_spec())
    payload["python_code"] = "print('unsafe')"

    with pytest.raises(StrategySpecError, match="不支持的字段"):
        strategy_spec_from_dict(payload)


def test_invalid_indicator_window_is_rejected() -> None:
    payload = strategy_spec_to_dict(_core_spec())
    payload["entry"]["conditions"][0]["right"]["window"] = 501

    with pytest.raises(StrategySpecError, match="指标周期"):
        strategy_spec_from_dict(payload)


def test_group_depth_is_bounded() -> None:
    payload = strategy_spec_to_dict(_core_spec())
    comparison = payload["entry"]["conditions"][0]
    nested = comparison
    for _ in range(5):
        nested = {"type": "group", "operator": "AND", "conditions": [nested]}
    payload["entry"] = nested

    with pytest.raises(StrategySpecError, match="最多允许4层"):
        strategy_spec_from_dict(payload)


def test_compiled_spec_uses_prior_bars_for_breakout_and_volume() -> None:
    spec = _core_spec()
    strategy = StrategySpecCompiler().compile(spec)
    context = StrategyContext(
        strategy_key=strategy.metadata.strategy_key,
        strategy_version=strategy.metadata.version,
        run_id=uuid4(),
        current_time=datetime(2024, 1, 1, tzinfo=UTC),
        parameters={},
    )
    strategy.initialize(context)

    for day in range(10):
        bar = _bar(day, str(10 + day), "100")
        context.advance_time(bar.timestamp)
        assert strategy.on_bar(context, bar) == []

    breakout = _bar(10, "21", "130")
    context.advance_time(breakout.timestamp)
    buy = strategy.on_bar(context, breakout)
    assert len(buy) == 1
    assert buy[0].side is OrderSide.BUY
    assert buy[0].signal_type is SignalType.ENTRY

    exit_bar = _bar(11, "5", "100")
    context.advance_time(exit_bar.timestamp)
    sell = strategy.on_bar(context, exit_bar)
    assert len(sell) == 1
    assert sell[0].side is OrderSide.SELL
    assert sell[0].signal_type is SignalType.EXIT


def test_compiler_registers_deterministic_strategy_once() -> None:
    registry = StrategyRegistry()
    compiler = StrategySpecCompiler()
    spec = _core_spec()

    first = compiler.register(registry, spec)
    second = compiler.register(registry, spec)

    assert first == second
    assert registry.get(first).display_name == spec.name


def test_ai_schema_rejects_extra_properties() -> None:
    schema = strategy_spec_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["operand"]["additionalProperties"] is False
    assert schema["$defs"]["comparison"]["additionalProperties"] is False
