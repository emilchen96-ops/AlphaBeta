"""Safe, versioned strategy rules for the UX02 research workbench.

The module intentionally models rules as a small allow-listed AST.  It never
stores or evaluates Python source, imports modules, reads files, performs HTTP
requests, or talks to a broker.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from alphadesk_domain.enums import MarketTimeframe, OrderSide, SignalType
from alphadesk_domain.strategy import (
    SignalDraft,
    Strategy,
    StrategyBar,
    StrategyContext,
    StrategyError,
    StrategyMetadata,
    StrategyRegistry,
)


class StrategySpecError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LogicalOperator(StrEnum):
    AND = "AND"
    OR = "OR"


class ComparisonOperator(StrEnum):
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"


class MarketField(StrEnum):
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"


class IndicatorKind(StrEnum):
    SMA = "SMA"
    ROLLING_HIGHEST = "ROLLING_HIGHEST"
    ROLLING_LOWEST = "ROLLING_LOWEST"
    AVERAGE_VOLUME = "AVERAGE_VOLUME"


class OperandKind(StrEnum):
    FIELD = "FIELD"
    INDICATOR = "INDICATOR"
    CONSTANT = "CONSTANT"


@dataclass(frozen=True, slots=True)
class Operand:
    kind: OperandKind
    field: MarketField | None = None
    indicator: IndicatorKind | None = None
    window: int | None = None
    exclude_current: bool = False
    multiplier: Decimal = Decimal("1")
    value: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Comparison:
    left: Operand
    operator: ComparisonOperator
    right: Operand


@dataclass(frozen=True, slots=True)
class ConditionGroup:
    operator: LogicalOperator
    conditions: tuple[Comparison | ConditionGroup, ...]


@dataclass(frozen=True, slots=True)
class StrategySpec:
    name: str
    description: str
    entry: ConditionGroup
    exit: ConditionGroup
    timeframe: MarketTimeframe = MarketTimeframe.DAY_1
    quantity: Decimal = Decimal("100")
    single_instrument: bool = True
    data_range_years: int = 2
    schema_version: int = 1
    origin: str = "USER"


@dataclass(frozen=True, slots=True)
class StrategyParseResult:
    status: str
    parser_source: str
    spec: StrategySpec | None
    preview: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class UserStrategyDefinition:
    name: str
    description: str
    id: UUID
    current_version: int = 1
    archived: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class UserStrategyVersion:
    strategy_id: UUID
    version_number: int
    spec: StrategySpec
    id: UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ResearchBacktestSpecSnapshot:
    backtest_run_id: UUID
    spec: StrategySpec
    id: UUID
    user_strategy_id: UUID | None = None
    user_strategy_version_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AdvancedStrategyPlugin(Protocol):
    """Opt-in extension port for rules that the safe AST cannot express."""

    plugin_key: str

    def build(self, configuration: Mapping[str, Any]) -> Strategy: ...


class AdvancedStrategyPluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, AdvancedStrategyPlugin] = {}

    def register(self, plugin: AdvancedStrategyPlugin) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", plugin.plugin_key):
            raise StrategySpecError("STRATEGY_PLUGIN_INVALID", "高级插件标识不合法")
        if plugin.plugin_key in self._plugins:
            raise StrategySpecError("STRATEGY_PLUGIN_DUPLICATE", "高级插件已注册")
        self._plugins[plugin.plugin_key] = plugin

    def get(self, key: str) -> AdvancedStrategyPlugin:
        try:
            return self._plugins[key]
        except KeyError as exc:
            raise StrategySpecError("STRATEGY_PLUGIN_NOT_FOUND", "高级插件不存在") from exc


_DANGEROUS_PATTERNS = (
    r"\bpython\b",
    r"\bimport\s+",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bsubprocess\b",
    r"\bos\.",
    r"https?://",
    r"环境变量",
    r"读取文件",
    r"写入文件",
    r"删除文件",
    r"发送请求",
    r"发起下单",
    r"自动下单",
    r"撤单",
    r"\bbroker\b",
)


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise StrategySpecError("STRATEGY_SPEC_INVALID", f"{field_name}必须是有效数字") from exc
    if not result.is_finite():
        raise StrategySpecError("STRATEGY_SPEC_INVALID", f"{field_name}必须是有限数字")
    return result


def _strict_keys(data: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise StrategySpecError(
            "STRATEGY_SPEC_UNKNOWN_FIELD", f"{label}包含不支持的字段: {sorted(unknown)[0]}"
        )


def _operand_from_dict(data: Mapping[str, Any]) -> Operand:
    _strict_keys(
        data,
        {"kind", "field", "indicator", "window", "exclude_current", "multiplier", "value"},
        "规则操作数",
    )
    try:
        kind = OperandKind(str(data["kind"]))
    except (KeyError, ValueError) as exc:
        raise StrategySpecError("STRATEGY_SPEC_INVALID", "规则操作数类型不受支持") from exc
    field_value = data.get("field")
    indicator_value = data.get("indicator")
    try:
        market_field = None if field_value is None else MarketField(str(field_value))
        indicator = None if indicator_value is None else IndicatorKind(str(indicator_value))
    except ValueError as exc:
        raise StrategySpecError("STRATEGY_SPEC_INVALID", "字段或指标不在白名单中") from exc
    window_raw = data.get("window")
    window = None if window_raw is None else int(window_raw)
    value_raw = data.get("value")
    return Operand(
        kind=kind,
        field=market_field,
        indicator=indicator,
        window=window,
        exclude_current=bool(data.get("exclude_current", False)),
        multiplier=_decimal(data.get("multiplier", "1"), "指标倍数"),
        value=None if value_raw is None else _decimal(value_raw, "常数"),
    )


def _condition_from_dict(data: Mapping[str, Any], depth: int = 1) -> Comparison | ConditionGroup:
    if depth > 4:
        raise StrategySpecError("STRATEGY_SPEC_TOO_DEEP", "条件嵌套最多允许4层")
    node_type = data.get("type")
    if node_type == "comparison":
        _strict_keys(data, {"type", "left", "operator", "right"}, "比较条件")
        try:
            left = _operand_from_dict(data["left"])
            right = _operand_from_dict(data["right"])
            comparison_operator = ComparisonOperator(str(data["operator"]))
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, StrategySpecError):
                raise
            raise StrategySpecError("STRATEGY_SPEC_INVALID", "比较条件格式不正确") from exc
        return Comparison(left=left, operator=comparison_operator, right=right)
    if node_type == "group":
        _strict_keys(data, {"type", "operator", "conditions"}, "条件组")
        raw_conditions = data.get("conditions")
        if not isinstance(raw_conditions, list):
            raise StrategySpecError("STRATEGY_SPEC_INVALID", "条件组必须包含条件列表")
        try:
            group_operator = LogicalOperator(str(data["operator"]))
        except (KeyError, ValueError) as exc:
            raise StrategySpecError("STRATEGY_SPEC_INVALID", "条件组运算符不受支持") from exc
        return ConditionGroup(
            operator=group_operator,
            conditions=tuple(
                _condition_from_dict(item, depth + 1)
                for item in raw_conditions
                if isinstance(item, Mapping)
            ),
        )
    raise StrategySpecError("STRATEGY_SPEC_INVALID", "规则节点类型不受支持")


def strategy_spec_from_dict(data: Mapping[str, Any]) -> StrategySpec:
    _strict_keys(
        data,
        {
            "schema_version",
            "name",
            "description",
            "entry",
            "exit",
            "timeframe",
            "quantity",
            "single_instrument",
            "data_range_years",
            "origin",
        },
        "策略规格",
    )
    try:
        entry = _condition_from_dict(data["entry"])
        exit_group = _condition_from_dict(data["exit"])
        timeframe = MarketTimeframe(str(data.get("timeframe", "DAY_1")))
    except (KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, StrategySpecError):
            raise
        raise StrategySpecError("STRATEGY_SPEC_INVALID", "策略规格格式不正确") from exc
    if not isinstance(entry, ConditionGroup) or not isinstance(exit_group, ConditionGroup):
        raise StrategySpecError("STRATEGY_SPEC_INVALID", "买入和卖出规则必须是条件组")
    spec = StrategySpec(
        schema_version=int(data.get("schema_version", 1)),
        name=str(data.get("name", "")).strip(),
        description=str(data.get("description", "")).strip(),
        entry=entry,
        exit=exit_group,
        timeframe=timeframe,
        quantity=_decimal(data.get("quantity", "100"), "每次交易数量"),
        single_instrument=bool(data.get("single_instrument", True)),
        data_range_years=int(data.get("data_range_years", 2)),
        origin=str(data.get("origin", "USER")).strip().upper(),
    )
    StrategySpecValidator().validate(spec)
    return spec


def _operand_to_dict(operand: Operand) -> dict[str, Any]:
    return {
        "kind": operand.kind.value,
        "field": None if operand.field is None else operand.field.value,
        "indicator": None if operand.indicator is None else operand.indicator.value,
        "window": operand.window,
        "exclude_current": operand.exclude_current,
        "multiplier": str(operand.multiplier),
        "value": None if operand.value is None else str(operand.value),
    }


def _condition_to_dict(condition: Comparison | ConditionGroup) -> dict[str, Any]:
    if isinstance(condition, Comparison):
        return {
            "type": "comparison",
            "left": _operand_to_dict(condition.left),
            "operator": condition.operator.value,
            "right": _operand_to_dict(condition.right),
        }
    return {
        "type": "group",
        "operator": condition.operator.value,
        "conditions": [_condition_to_dict(item) for item in condition.conditions],
    }


def strategy_spec_to_dict(spec: StrategySpec) -> dict[str, Any]:
    return {
        "schema_version": spec.schema_version,
        "name": spec.name,
        "description": spec.description,
        "entry": _condition_to_dict(spec.entry),
        "exit": _condition_to_dict(spec.exit),
        "timeframe": spec.timeframe.value,
        "quantity": str(spec.quantity),
        "single_instrument": spec.single_instrument,
        "data_range_years": spec.data_range_years,
        "origin": spec.origin,
    }


class StrategySpecValidator:
    MAX_CONDITIONS = 16
    MAX_WINDOW = 500

    def validate(self, spec: StrategySpec) -> StrategySpec:
        if spec.schema_version != 1:
            raise StrategySpecError("STRATEGY_SPEC_VERSION_UNSUPPORTED", "仅支持规则版本1")
        if not spec.name or len(spec.name) > 128:
            raise StrategySpecError("STRATEGY_SPEC_INVALID", "策略名称长度必须为1到128个字符")
        if spec.timeframe is not MarketTimeframe.DAY_1:
            raise StrategySpecError("STRATEGY_SPEC_UNSUPPORTED", "当前快速回测仅支持日线")
        if spec.quantity <= 0:
            raise StrategySpecError("STRATEGY_SPEC_INVALID", "每次交易数量必须大于0")
        if not 1 <= spec.data_range_years <= 20:
            raise StrategySpecError("STRATEGY_SPEC_INVALID", "数据年限必须在1到20年之间")
        for label, group in (("买入", spec.entry), ("卖出", spec.exit)):
            count = self._validate_group(group, depth=1)
            if count == 0:
                raise StrategySpecError("STRATEGY_SPEC_INVALID", f"{label}条件不能为空")
            if count > self.MAX_CONDITIONS:
                raise StrategySpecError(
                    "STRATEGY_SPEC_TOO_COMPLEX", f"{label}条件最多允许{self.MAX_CONDITIONS}项"
                )
        return spec

    def _validate_group(self, group: ConditionGroup, *, depth: int) -> int:
        if depth > 4:
            raise StrategySpecError("STRATEGY_SPEC_TOO_DEEP", "条件嵌套最多允许4层")
        if not group.conditions:
            raise StrategySpecError("STRATEGY_SPEC_INVALID", "条件组不能为空")
        count = 0
        for item in group.conditions:
            if isinstance(item, ConditionGroup):
                count += self._validate_group(item, depth=depth + 1)
            else:
                self._validate_operand(item.left)
                self._validate_operand(item.right)
                count += 1
        return count

    def _validate_operand(self, operand: Operand) -> None:
        if operand.kind is OperandKind.FIELD:
            if operand.field is None or any(
                value is not None for value in (operand.indicator, operand.window, operand.value)
            ):
                raise StrategySpecError("STRATEGY_SPEC_INVALID", "行情字段操作数格式不正确")
            return
        if operand.kind is OperandKind.CONSTANT:
            if operand.value is None:
                raise StrategySpecError("STRATEGY_SPEC_INVALID", "常数操作数缺少数值")
            return
        if operand.kind is OperandKind.INDICATOR:
            if operand.indicator is None or operand.field is None or operand.window is None:
                raise StrategySpecError("STRATEGY_SPEC_INVALID", "指标操作数缺少必要参数")
            if not 1 <= operand.window <= self.MAX_WINDOW:
                raise StrategySpecError(
                    "STRATEGY_SPEC_INVALID", f"指标周期必须在1到{self.MAX_WINDOW}之间"
                )
            if not Decimal("0") < operand.multiplier <= Decimal("100"):
                raise StrategySpecError("STRATEGY_SPEC_INVALID", "指标倍数必须大于0且不超过100")
            if (
                operand.indicator is IndicatorKind.AVERAGE_VOLUME
                and operand.field is not MarketField.VOLUME
            ):
                raise StrategySpecError("STRATEGY_SPEC_INVALID", "平均成交量只能使用成交量字段")
            return
        raise StrategySpecError("STRATEGY_SPEC_INVALID", "操作数类型不受支持")


def _field(field_name: MarketField) -> Operand:
    return Operand(kind=OperandKind.FIELD, field=field_name)


def _indicator(
    kind: IndicatorKind,
    field_name: MarketField,
    window: int,
    *,
    exclude_current: bool,
    multiplier: Decimal = Decimal("1"),
) -> Operand:
    return Operand(
        kind=OperandKind.INDICATOR,
        field=field_name,
        indicator=kind,
        window=window,
        exclude_current=exclude_current,
        multiplier=multiplier,
    )


class DeterministicChineseStrategyParser:
    """Parse common Chinese price/volume rules without any AI dependency."""

    def parse(self, text: str) -> StrategyParseResult:
        normalized = " ".join(text.strip().split())
        if not normalized:
            raise StrategySpecError("STRATEGY_TEXT_EMPTY", "请输入策略描述")
        if len(normalized) > 1000:
            raise StrategySpecError("STRATEGY_TEXT_TOO_LONG", "策略描述最多1000个字符")
        lowered = normalized.casefold()
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in _DANGEROUS_PATTERNS):
            raise StrategySpecError(
                "STRATEGY_TEXT_UNSAFE",
                "策略描述包含脚本、网络、文件或交易指令; 自然语言只允许描述研究规则",
            )

        breakout = re.search(r"(\d{1,3})\s*日(?:价格|收盘价)?突破", normalized)
        volume = re.search(r"(\d+(?:\.\d+)?)\s*倍成交量", normalized)
        exit_sma = re.search(r"(\d{1,3})\s*日均线退出", normalized)
        year_match = re.search(r"(\d{1,2}|一|二|两|三|四|五|六|七|八|九|十)\s*年", normalized)
        missing: list[str] = []
        if breakout is None:
            missing.append("价格突破周期")
        if volume is None:
            missing.append("成交量倍数")
        if exit_sma is None:
            missing.append("退出均线周期")
        if missing:
            return StrategyParseResult(
                status="PARTIAL",
                parser_source="LOCAL_RULES",
                spec=None,
                preview=(),
                warnings=("当前描述尚不能安全编译, 请补齐缺少的规则。",),
                missing_fields=tuple(missing),
            )

        assert breakout is not None and volume is not None and exit_sma is not None
        years = 2
        if year_match is not None:
            token = year_match.group(1)
            chinese_numbers = {
                "一": 1,
                "二": 2,
                "两": 2,
                "三": 3,
                "四": 4,
                "五": 5,
                "六": 6,
                "七": 7,
                "八": 8,
                "九": 9,
                "十": 10,
            }
            years = chinese_numbers.get(token, int(token) if token.isdigit() else 2)
        breakout_window = int(breakout.group(1))
        volume_multiplier = _decimal(volume.group(1), "成交量倍数")
        exit_window = int(exit_sma.group(1))
        spec = StrategySpec(
            name=f"{breakout_window}日价格突破与放量策略",
            description=normalized,
            entry=ConditionGroup(
                operator=LogicalOperator.AND,
                conditions=(
                    Comparison(
                        left=_field(MarketField.CLOSE),
                        operator=ComparisonOperator.GT,
                        right=_indicator(
                            IndicatorKind.ROLLING_HIGHEST,
                            MarketField.HIGH,
                            breakout_window,
                            exclude_current=True,
                        ),
                    ),
                    Comparison(
                        left=_field(MarketField.VOLUME),
                        operator=ComparisonOperator.GT,
                        right=_indicator(
                            IndicatorKind.AVERAGE_VOLUME,
                            MarketField.VOLUME,
                            breakout_window,
                            exclude_current=True,
                            multiplier=volume_multiplier,
                        ),
                    ),
                ),
            ),
            exit=ConditionGroup(
                operator=LogicalOperator.AND,
                conditions=(
                    Comparison(
                        left=_field(MarketField.CLOSE),
                        operator=ComparisonOperator.LT,
                        right=_indicator(
                            IndicatorKind.SMA,
                            MarketField.CLOSE,
                            exit_window,
                            exclude_current=False,
                        ),
                    ),
                ),
            ),
            single_instrument="单只股票" in normalized,
            data_range_years=years,
            origin="NATURAL_LANGUAGE",
        )
        StrategySpecValidator().validate(spec)
        return StrategyParseResult(
            status="COMPLETE",
            parser_source="LOCAL_RULES",
            spec=spec,
            preview=tuple(strategy_spec_preview(spec)),
        )


_FIELD_LABELS = {
    MarketField.OPEN: "开盘价",
    MarketField.HIGH: "最高价",
    MarketField.LOW: "最低价",
    MarketField.CLOSE: "收盘价",
    MarketField.VOLUME: "成交量",
}
_OPERATOR_LABELS = {
    ComparisonOperator.GT: "大于",
    ComparisonOperator.GTE: "大于等于",
    ComparisonOperator.LT: "小于",
    ComparisonOperator.LTE: "小于等于",
}


def _operand_preview(operand: Operand) -> str:
    if operand.kind is OperandKind.FIELD and operand.field is not None:
        return _FIELD_LABELS[operand.field]
    if operand.kind is OperandKind.CONSTANT and operand.value is not None:
        return str(operand.value)
    if operand.kind is OperandKind.INDICATOR:
        assert operand.indicator is not None and operand.field is not None
        prefix = "前" if operand.exclude_current else "含当日"
        if operand.indicator is IndicatorKind.ROLLING_HIGHEST:
            text = f"{prefix}{operand.window}日最高价"
        elif operand.indicator is IndicatorKind.ROLLING_LOWEST:
            text = f"{prefix}{operand.window}日最低价"
        elif operand.indicator is IndicatorKind.AVERAGE_VOLUME:
            text = f"{prefix}{operand.window}日平均成交量"
        else:
            text = f"{prefix}{operand.window}日简单移动平均线(SMA)"
        return text if operand.multiplier == 1 else f"{operand.multiplier}倍{text}"
    raise StrategySpecError("STRATEGY_SPEC_INVALID", "无法生成规则预览")


def _condition_preview(condition: Comparison | ConditionGroup) -> str:
    if isinstance(condition, Comparison):
        return (
            f"{_operand_preview(condition.left)}"
            f"{_OPERATOR_LABELS[condition.operator]}"
            f"{_operand_preview(condition.right)}"
        )
    joiner = " 且 " if condition.operator is LogicalOperator.AND else " 或 "
    return joiner.join(_condition_preview(item) for item in condition.conditions)


def strategy_spec_preview(spec: StrategySpec) -> list[str]:
    return [
        f"买入: {_condition_preview(spec.entry)}。",
        f"卖出: {_condition_preview(spec.exit)}。",
        f"范围: {'单只股票' if spec.single_instrument else '多只股票'}, "
        f"{spec.data_range_years}年日线。",
        "滚动最高价和平均成交量默认排除当前K线, 不使用未来数据。",
        "回测仅为历史模拟, 不会发送给券商。",
    ]


def strategy_spec_key(spec: StrategySpec) -> str:
    payload = json.dumps(strategy_spec_to_dict(spec), sort_keys=True, separators=(",", ":"))
    return f"user_spec_{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def _operand_value(operand: Operand, bars: Sequence[StrategyBar]) -> Decimal | None:
    if not bars:
        return None
    if operand.kind is OperandKind.FIELD:
        assert operand.field is not None
        return Decimal(getattr(bars[-1], operand.field.value))
    if operand.kind is OperandKind.CONSTANT:
        return operand.value
    assert (
        operand.indicator is not None and operand.field is not None and operand.window is not None
    )
    source = bars[:-1] if operand.exclude_current else bars
    if len(source) < operand.window:
        return None
    values = [Decimal(getattr(bar, operand.field.value)) for bar in source[-operand.window :]]
    if operand.indicator is IndicatorKind.ROLLING_HIGHEST:
        base = max(values)
    elif operand.indicator is IndicatorKind.ROLLING_LOWEST:
        base = min(values)
    else:
        base = sum(values, Decimal("0")) / Decimal(len(values))
    return base * operand.multiplier


def _evaluate(condition: Comparison | ConditionGroup, bars: Sequence[StrategyBar]) -> bool:
    if isinstance(condition, ConditionGroup):
        results = [_evaluate(item, bars) for item in condition.conditions]
        return all(results) if condition.operator is LogicalOperator.AND else any(results)
    left = _operand_value(condition.left, bars)
    right = _operand_value(condition.right, bars)
    if left is None or right is None:
        return False
    if condition.operator is ComparisonOperator.GT:
        return left > right
    if condition.operator is ComparisonOperator.GTE:
        return left >= right
    if condition.operator is ComparisonOperator.LT:
        return left < right
    return left <= right


@dataclass(slots=True)
class _CompiledInstrumentState:
    bars: list[StrategyBar] = field(default_factory=list)
    is_long: bool = False


class CompiledStrategy:
    def __init__(self, spec: StrategySpec) -> None:
        self.spec = StrategySpecValidator().validate(spec)
        self.metadata = StrategyMetadata(
            strategy_key=strategy_spec_key(spec),
            display_name=spec.name,
            description=spec.description or "用户构建的安全规则策略",
            version="1.0.0",
            supported_timeframes=(spec.timeframe,),
        )

    def initialize(self, context: StrategyContext) -> None:
        context.set_state(self.metadata.strategy_key, {})

    def on_bar(self, context: StrategyContext, bar: StrategyBar) -> list[SignalDraft]:
        if bar.timeframe is not self.spec.timeframe:
            raise StrategyError("STRATEGY_INVALID_BAR", "K线周期与策略规格不一致")
        raw_states = context.get_state(self.metadata.strategy_key)
        if not isinstance(raw_states, dict):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "策略尚未初始化")
        state = raw_states.setdefault(str(bar.instrument_id), _CompiledInstrumentState())
        if not isinstance(state, _CompiledInstrumentState):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "策略状态无效")
        if state.bars and bar.timestamp <= state.bars[-1].timestamp:
            raise StrategyError("STRATEGY_INVALID_BAR", "K线必须按时间严格递增")
        state.bars.append(bar)
        if len(state.bars) > 501:
            del state.bars[0]
        side: OrderSide | None = None
        signal_type: SignalType | None = None
        reason = ""
        if not state.is_long and _evaluate(self.spec.entry, state.bars):
            side = OrderSide.BUY
            signal_type = SignalType.ENTRY
            state.is_long = True
            reason = _condition_preview(self.spec.entry)
        elif state.is_long and _evaluate(self.spec.exit, state.bars):
            side = OrderSide.SELL
            signal_type = SignalType.EXIT
            state.is_long = False
            reason = _condition_preview(self.spec.exit)
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
                quantity=self.spec.quantity,
                reference_price=bar.close,
                reason=reason,
                metadata={
                    "strategy_spec_schema_version": self.spec.schema_version,
                    "safe_compiled": True,
                },
            )
        ]

    def finalize(self, context: StrategyContext) -> None:
        del context


class StrategySpecCompiler:
    def compile(self, spec: StrategySpec) -> CompiledStrategy:
        return CompiledStrategy(StrategySpecValidator().validate(spec))

    def register(self, registry: StrategyRegistry, spec: StrategySpec) -> str:
        compiled = self.compile(spec)
        key = compiled.metadata.strategy_key
        try:
            registry.get(key)
        except StrategyError as exc:
            if exc.code != "STRATEGY_NOT_FOUND":
                raise
            registry.register(
                compiled.metadata,
                (),
                lambda parameters: CompiledStrategy(spec),
            )
        return key


def strategy_spec_json_schema() -> dict[str, Any]:
    """JSON schema used by optional AI providers; additional fields are rejected."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AlphaDesk StrategySpec v1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "name", "entry", "exit"],
        "properties": {
            "schema_version": {"const": 1},
            "name": {"type": "string", "minLength": 1, "maxLength": 128},
            "description": {"type": "string", "maxLength": 1000},
            "timeframe": {"const": "DAY_1"},
            "quantity": {"type": "string"},
            "single_instrument": {"type": "boolean"},
            "data_range_years": {"type": "integer", "minimum": 1, "maximum": 20},
            "origin": {"type": "string"},
            "entry": {"$ref": "#/$defs/group"},
            "exit": {"$ref": "#/$defs/group"},
        },
        "$defs": {
            "operand": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {"enum": [item.value for item in OperandKind]},
                    "field": {"enum": [item.value for item in MarketField] + [None]},
                    "indicator": {"enum": [item.value for item in IndicatorKind] + [None]},
                    "window": {"type": ["integer", "null"], "minimum": 1, "maximum": 500},
                    "exclude_current": {"type": "boolean"},
                    "multiplier": {"type": "string"},
                    "value": {"type": ["string", "null"]},
                },
                "required": ["kind"],
            },
            "comparison": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"const": "comparison"},
                    "left": {"$ref": "#/$defs/operand"},
                    "operator": {"enum": [item.value for item in ComparisonOperator]},
                    "right": {"$ref": "#/$defs/operand"},
                },
                "required": ["type", "left", "operator", "right"],
            },
            "group": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"const": "group"},
                    "operator": {"enum": [item.value for item in LogicalOperator]},
                    "conditions": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 16,
                        "items": {
                            "oneOf": [
                                {"$ref": "#/$defs/comparison"},
                                {"$ref": "#/$defs/group"},
                            ]
                        },
                    },
                },
                "required": ["type", "operator", "conditions"],
            },
        },
    }
