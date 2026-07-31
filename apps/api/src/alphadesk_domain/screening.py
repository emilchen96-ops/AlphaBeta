# ruff: noqa: RUF001
"""SC02-A versioned condition catalog and deterministic rule screening engine.

The module is deliberately framework independent.  It accepts only structured,
catalog-backed specifications and immutable market-bar facts; it never executes
code supplied by a caller and has no trading-side dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.indicators import (
    ExponentialMovingAverage,
    RollingAverageVolume,
    RollingHighest,
    RollingLowest,
    SimpleMovingAverage,
)
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.strategy import StrategyBar
from alphadesk_domain.values import non_empty


class ScreeningError(ValueError):
    """A bounded, user-safe screening validation or evaluation error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConditionCategory(StrEnum):
    PRICE = "PRICE"
    TREND = "TREND"
    VOLUME = "VOLUME"
    CANDLE = "CANDLE"
    LIQUIDITY = "LIQUIDITY"
    TRADING = "TRADING"
    PATTERN = "PATTERN"
    RETURN = "RETURN"
    AMOUNT = "AMOUNT"
    MOVING_AVERAGE = "MOVING_AVERAGE"
    BREAKOUT = "BREAKOUT"
    LIMIT_UP_EVENT = "LIMIT_UP_EVENT"
    RANGE_POSITION = "RANGE_POSITION"
    COMPOSITE_PATTERN = "COMPOSITE_PATTERN"


class ConditionParameterType(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    ENUM = "enum"
    PERCENTAGE = "percentage"
    AMOUNT = "amount"
    TRADING_DAY_WINDOW = "trading_day_window"


class ConditionGroupOperator(StrEnum):
    AND = "AND"
    OR = "OR"


class ConditionOutcome(StrEnum):
    MATCHED = "MATCHED"
    NOT_MATCHED = "NOT_MATCHED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INDETERMINATE = "INDETERMINATE"
    FAILED = "FAILED"


class RankingDirection(StrEnum):
    ASC = "ASC"
    DESC = "DESC"


ConditionValue = str | int | bool | Decimal | None
StoredConditionValue = str | int | bool | None
MetricValue = object


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ScreeningError("SCREENING_INVALID_PARAMETER", f"{name}必须是数值")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ScreeningError("SCREENING_INVALID_PARAMETER", f"{name}必须是数值") from exc
    if not result.is_finite():
        raise ScreeningError("SCREENING_INVALID_PARAMETER", f"{name}必须是有限数值")
    return result


def _stored(value: ConditionValue) -> StoredConditionValue:
    return format(value.normalize(), "f") if isinstance(value, Decimal) else value


def _metric(value: Decimal | int | bool | str | None) -> MetricValue:
    return format(value.normalize(), "f") if isinstance(value, Decimal) else value


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionParameterSchema:
    name: str
    display_name: str
    parameter_type: ConditionParameterType
    description: str
    default: ConditionValue = None
    required: bool = False
    nullable: bool = False
    min_value: Decimal | int | None = None
    max_value: Decimal | int | None = None
    enum_values: tuple[str, ...] = ()
    unit: str | None = None
    display_unit: str | None = None
    precision: int | None = None
    placeholder: str | None = None
    help_text: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", non_empty(self.name, "name"))
        object.__setattr__(self, "display_name", non_empty(self.display_name, "display_name"))
        object.__setattr__(self, "description", non_empty(self.description, "description"))
        if self.parameter_type is ConditionParameterType.ENUM and not self.enum_values:
            raise ValueError("enum parameter requires enum_values")

    def validate(self, value: object) -> ConditionValue:
        if value is None:
            if self.nullable:
                return None
            raise ScreeningError(
                "SCREENING_REQUIRED_PARAMETER_MISSING",
                f"缺少参数：{self.display_name}（{self.name}）",
            )
        if self.parameter_type is ConditionParameterType.BOOLEAN:
            if not isinstance(value, bool):
                raise ScreeningError(
                    "SCREENING_INVALID_PARAMETER", f"{self.display_name}必须为是或否"
                )
            return value
        if self.parameter_type in {
            ConditionParameterType.INTEGER,
            ConditionParameterType.TRADING_DAY_WINDOW,
        }:
            if isinstance(value, bool):
                raise ScreeningError(
                    "SCREENING_INVALID_PARAMETER", f"{self.display_name}必须为整数"
                )
            try:
                parsed = int(str(value))
            except (TypeError, ValueError) as exc:
                raise ScreeningError(
                    "SCREENING_INVALID_PARAMETER", f"{self.display_name}必须为整数"
                ) from exc
            if str(parsed) != str(value).strip() and not isinstance(value, int):
                raise ScreeningError(
                    "SCREENING_INVALID_PARAMETER", f"{self.display_name}必须为整数"
                )
            self._check_range(Decimal(parsed))
            return parsed
        if self.parameter_type in {
            ConditionParameterType.DECIMAL,
            ConditionParameterType.PERCENTAGE,
            ConditionParameterType.AMOUNT,
        }:
            parsed_decimal = _decimal(value, self.display_name)
            self._check_range(parsed_decimal)
            return parsed_decimal
        if not isinstance(value, str) or value not in self.enum_values:
            raise ScreeningError(
                "SCREENING_INVALID_PARAMETER",
                f"{self.display_name}必须是：{'、'.join(self.enum_values)}",
            )
        return value

    def _check_range(self, value: Decimal) -> None:
        if self.min_value is not None and value < Decimal(str(self.min_value)):
            raise ScreeningError("SCREENING_INVALID_PARAMETER", f"{self.display_name}低于允许范围")
        if self.max_value is not None and value > Decimal(str(self.max_value)):
            raise ScreeningError("SCREENING_INVALID_PARAMETER", f"{self.display_name}高于允许范围")

    def response_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "type": self.parameter_type.value,
            "description": self.description,
            "default": _stored(self.default),
            "required": self.required,
            "nullable": self.nullable,
            "min_value": None if self.min_value is None else str(self.min_value),
            "max_value": None if self.max_value is None else str(self.max_value),
            "enum_values": list(self.enum_values),
            "unit": self.unit,
            "display_unit": self.display_unit,
            "precision": self.precision,
            "placeholder": self.placeholder,
            "help_text": self.help_text or self.description,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionDefinition:
    condition_key: str
    display_name: str
    description: str
    category: ConditionCategory
    parameter_schema: tuple[ConditionParameterSchema, ...]
    required_fields: tuple[str, ...]
    required_history_bars: int
    supported_timeframes: tuple[MarketTimeframe, ...]
    price_adjustment_mode: PriceAdjustmentMode
    evaluator_key: str
    explanation_template: str
    version: str
    enabled: bool = True
    aliases: tuple[str, ...] = ()
    deprecated: bool = False
    replacement_condition_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "condition_key", non_empty(self.condition_key, "condition_key").upper()
        )
        object.__setattr__(self, "display_name", non_empty(self.display_name, "display_name"))
        object.__setattr__(self, "description", non_empty(self.description, "description"))
        object.__setattr__(self, "evaluator_key", non_empty(self.evaluator_key, "evaluator_key"))
        object.__setattr__(
            self,
            "explanation_template",
            non_empty(self.explanation_template, "explanation_template"),
        )
        object.__setattr__(self, "version", non_empty(self.version, "version"))
        if self.required_history_bars < 1:
            raise ValueError("required_history_bars must be positive")
        if not self.supported_timeframes:
            raise ValueError("supported_timeframes must not be empty")
        names = [item.name for item in self.parameter_schema]
        if len(names) != len(set(names)):
            raise ValueError("condition parameter names must be unique")

    def validate_parameters(self, supplied: Mapping[str, object]) -> dict[str, ConditionValue]:
        definitions = {item.name: item for item in self.parameter_schema}
        unknown = sorted(set(supplied) - set(definitions))
        if unknown:
            raise ScreeningError(
                "SCREENING_UNKNOWN_PARAMETER",
                f"{self.display_name}包含未知参数：{', '.join(unknown)}",
            )
        result: dict[str, ConditionValue] = {}
        for name, schema in definitions.items():
            if name in supplied:
                result[name] = schema.validate(supplied[name])
            elif schema.default is not None or schema.nullable:
                result[name] = schema.validate(schema.default)
            elif schema.required:
                raise ScreeningError(
                    "SCREENING_REQUIRED_PARAMETER_MISSING",
                    f"缺少参数：{schema.display_name}（{name}）",
                )
        return result

    def history_bars(self, parameters: Mapping[str, ConditionValue]) -> int:
        dynamic = {
            "N_DAY_HIGH_BREAKOUT": int(parameters.get("window") or 20) + 1,
            "N_DAY_LOW": int(parameters.get("window") or 20) + 1,
            "SMA_RELATION": max(
                int(parameters.get("short_window") or 5),
                int(parameters.get("long_window") or 20),
            ),
            "EMA_RELATION": max(
                int(parameters.get("short_window") or 5),
                int(parameters.get("long_window") or 20),
            ),
            "AVERAGE_VOLUME": int(parameters.get("window") or 20),
            "VOLUME_RATIO": int(parameters.get("window") or 20) + 1,
            "N_DAY_RETURN": int(parameters.get("window") or 20) + 1,
            "RANGE_POSITION": int(parameters.get("window") or 60) + 1,
            "AMOUNT_THRESHOLD": int(parameters.get("window") or 1),
            "LIMIT_UP_PULLBACK": int(parameters.get("lookback_days") or 20) + 2,
            "RECENT_LIMIT_UP_EVENT": int(parameters.get("lookback_days") or 5) + 2,
            "BOTTOM_VOLUME_EXPANSION": max(
                int(parameters.get("range_window") or 60),
                int(parameters.get("volume_window") or 20),
            )
            + 1,
        }
        return max(self.required_history_bars, dynamic.get(self.condition_key, 1))

    def response_dict(self) -> dict[str, object]:
        return {
            "condition_key": self.condition_key,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category.value,
            "parameter_schema": [item.response_dict() for item in self.parameter_schema],
            "required_fields": list(self.required_fields),
            "required_history_bars": self.required_history_bars,
            "supported_timeframes": [item.value for item in self.supported_timeframes],
            "price_adjustment_mode": self.price_adjustment_mode.value,
            "evaluator_key": self.evaluator_key,
            "explanation_template": self.explanation_template,
            "version": self.version,
            "enabled": self.enabled,
            "aliases": list(self.aliases),
            "deprecated": self.deprecated,
            "replacement_condition_key": self.replacement_condition_key,
        }


class ConditionCatalog:
    """Explicit allow-list of versioned screening conditions."""

    def __init__(self) -> None:
        self._items: dict[str, ConditionDefinition] = {}

    def register(self, definition: ConditionDefinition) -> None:
        key = definition.condition_key
        if key in self._items:
            raise ScreeningError("SCREENING_CONDITION_DUPLICATE", f"条件已注册：{key}")
        self._items[key] = definition

    def get(self, condition_key: str) -> ConditionDefinition:
        key = condition_key.strip().upper()
        item = self._items.get(key)
        if item is None or not item.enabled:
            raise ScreeningError("SCREENING_CONDITION_NOT_FOUND", f"未知条件：{condition_key}")
        return item

    def list(self) -> tuple[ConditionDefinition, ...]:
        return tuple(self._items[key] for key in sorted(self._items) if self._items[key].enabled)

    def search(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        enabled: bool = True,
    ) -> tuple[ConditionDefinition, ...]:
        normalized = (query or "").strip().casefold()
        normalized_category = (category or "").strip().upper()
        items = []
        for item in self._items.values():
            if enabled and not item.enabled:
                continue
            if normalized_category and item.category.value != normalized_category:
                continue
            haystack = " ".join(
                (
                    item.condition_key,
                    item.display_name,
                    item.description,
                    *item.aliases,
                )
            ).casefold()
            if normalized and normalized not in haystack:
                continue
            items.append(item)
        return tuple(sorted(items, key=lambda item: (item.category.value, item.condition_key)))

    def validate(
        self, condition_key: str, parameters: Mapping[str, object]
    ) -> tuple[ConditionDefinition, dict[str, ConditionValue]]:
        definition = self.get(condition_key)
        return definition, definition.validate_parameters(parameters)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreeningCondition:
    condition_key: str
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "condition_key", non_empty(self.condition_key, "condition_key").upper()
        )
        object.__setattr__(self, "parameters", dict(self.parameters))


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreeningConditionGroup:
    operator: ConditionGroupOperator
    children: tuple[ScreeningCondition | ScreeningConditionGroup, ...]

    def __post_init__(self) -> None:
        if not self.children:
            raise ScreeningError("SCREENING_GROUP_EMPTY", "条件组至少需要一个条件")


@dataclass(frozen=True, slots=True, kw_only=True)
class UniverseSpec:
    universe_key: str = "ALL_A_SHARES"
    excluded_instrument_ids: tuple[UUID, ...] = ()
    exclude_st: bool = False
    exclude_bse: bool = False
    exclude_star_market: bool = False
    exclude_chinext: bool = False

    def __post_init__(self) -> None:
        if self.universe_key != "ALL_A_SHARES":
            raise ScreeningError("SCREENING_UNIVERSE_NOT_SUPPORTED", "SC02-A仅支持全部A股")
        object.__setattr__(
            self,
            "excluded_instrument_ids",
            tuple(sorted(set(self.excluded_instrument_ids), key=str)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RankingRule:
    field: str
    direction: RankingDirection = RankingDirection.DESC

    def __post_init__(self) -> None:
        object.__setattr__(self, "field", non_empty(self.field, "field"))


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreeningSpec:
    schema_version: int
    name: str
    origin: str
    universe_spec: UniverseSpec
    as_of_date: date
    timeframe: MarketTimeframe
    conditions: tuple[ScreeningCondition, ...] = ()
    root_group: ScreeningConditionGroup | None = None
    exclusions: Mapping[str, object] = field(default_factory=dict)
    ranking_rules: tuple[RankingRule, ...] = ()
    top_n: int | None = None
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW

    def __post_init__(self) -> None:
        if self.schema_version not in {1, 2}:
            raise ScreeningError(
                "SCREENING_SCHEMA_VERSION_NOT_SUPPORTED",
                "仅支持ScreeningSpec v1/v2",
            )
        object.__setattr__(self, "name", non_empty(self.name, "name")[:128])
        object.__setattr__(self, "origin", non_empty(self.origin, "origin")[:64])
        if self.timeframe is not MarketTimeframe.DAY_1:
            raise ScreeningError("SCREENING_TIMEFRAME_NOT_SUPPORTED", "SC02-A仅支持日线")
        if self.price_adjustment_mode is not PriceAdjustmentMode.RAW:
            raise ScreeningError(
                "SCREENING_ADJUSTMENT_NOT_SUPPORTED", "SC02-A标准形态仅支持不复权价格"
            )
        if self.schema_version == 1 and not self.conditions:
            raise ScreeningError("SCREENING_CONDITIONS_EMPTY", "至少需要一个筛选条件")
        if self.schema_version == 2 and self.root_group is None:
            raise ScreeningError("SCREENING_CONDITIONS_EMPTY", "组合选股至少需要一个条件组")
        if self.schema_version == 2 and self.conditions:
            raise ScreeningError("SCREENING_SCHEMA_CONFLICT", "v2规格只能使用root_group")
        if len(self.conditions) > 32:
            raise ScreeningError("SCREENING_TOO_MANY_CONDITIONS", "筛选条件不得超过32个")
        if self.root_group is not None:
            _validate_group_shape(self.root_group)
        if self.top_n is not None and not 1 <= self.top_n <= 10_000:
            raise ScreeningError("SCREENING_INVALID_TOP_N", "top_n必须在1到10000之间")
        _assert_safe_structure(self.exclusions, "exclusions")

    def validate(self, catalog: ConditionCatalog) -> ValidatedScreeningSpec:
        def validate_condition(condition: ScreeningCondition) -> ValidatedCondition:
            definition, parameters = catalog.validate(condition.condition_key, condition.parameters)
            if self.timeframe not in definition.supported_timeframes:
                raise ScreeningError(
                    "SCREENING_TIMEFRAME_NOT_SUPPORTED",
                    f"{definition.display_name}不支持{self.timeframe.value}",
                )
            if self.price_adjustment_mode is not definition.price_adjustment_mode:
                raise ScreeningError(
                    "SCREENING_ADJUSTMENT_NOT_SUPPORTED",
                    f"{definition.display_name}要求{definition.price_adjustment_mode.value}",
                )
            return ValidatedCondition(definition=definition, parameters=parameters)

        def validate_group(group: ScreeningConditionGroup) -> ValidatedConditionGroup:
            return ValidatedConditionGroup(
                operator=group.operator,
                children=tuple(
                    validate_group(item)
                    if isinstance(item, ScreeningConditionGroup)
                    else validate_condition(item)
                    for item in group.children
                ),
            )

        root = (
            validate_group(self.root_group)
            if self.root_group is not None
            else ValidatedConditionGroup(
                operator=ConditionGroupOperator.AND,
                children=tuple(validate_condition(item) for item in self.conditions),
            )
        )
        validated = tuple(_flatten_validated_conditions(root))
        allowed_rank_fields = {
            "score",
            "volume_multiple",
            "range_position",
            "distance_to_anchor",
            "current_close",
        }
        for rule in self.ranking_rules:
            if rule.field not in allowed_rank_fields:
                raise ScreeningError(
                    "SCREENING_INVALID_RANKING_FIELD", f"不支持排序字段：{rule.field}"
                )
        return ValidatedScreeningSpec(spec=self, root_group=root, conditions=validated)

    def snapshot(self, catalog: ConditionCatalog) -> dict[str, object]:
        validated = self.validate(catalog)
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "name": self.name,
            "origin": self.origin,
            "universe_spec": {
                "universe_key": self.universe_spec.universe_key,
                "excluded_instrument_ids": [
                    str(item) for item in self.universe_spec.excluded_instrument_ids
                ],
                "exclude_st": self.universe_spec.exclude_st,
                "exclude_bse": self.universe_spec.exclude_bse,
                "exclude_star_market": self.universe_spec.exclude_star_market,
                "exclude_chinext": self.universe_spec.exclude_chinext,
            },
            "as_of_date": self.as_of_date.isoformat(),
            "timeframe": self.timeframe.value,
            "exclusions": dict(self.exclusions),
            "ranking_rules": [
                {"field": item.field, "direction": item.direction.value}
                for item in self.ranking_rules
            ],
            "top_n": self.top_n,
            "price_adjustment_mode": self.price_adjustment_mode.value,
        }
        if self.schema_version == 1:
            payload["conditions"] = [
                _validated_condition_snapshot(item) for item in validated.conditions
            ]
        else:
            payload["conditions"] = []
            payload["root_group"] = _validated_group_snapshot(validated.root_group)
        return payload


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedCondition:
    definition: ConditionDefinition
    parameters: Mapping[str, ConditionValue]


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedConditionGroup:
    operator: ConditionGroupOperator
    children: tuple[ValidatedCondition | ValidatedConditionGroup, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedScreeningSpec:
    spec: ScreeningSpec
    root_group: ValidatedConditionGroup
    conditions: tuple[ValidatedCondition, ...]

    @property
    def required_history_bars(self) -> int:
        return max(item.definition.history_bars(item.parameters) for item in self.conditions)


def _validate_group_shape(group: ScreeningConditionGroup, *, depth: int = 1) -> int:
    if depth > 3:
        raise ScreeningError("SCREENING_GROUP_TOO_DEEP", "条件组最多嵌套3层")
    atoms = 0
    for child in group.children:
        atoms += (
            _validate_group_shape(child, depth=depth + 1)
            if isinstance(child, ScreeningConditionGroup)
            else 1
        )
    if atoms > 20:
        raise ScreeningError("SCREENING_TOO_MANY_CONDITIONS", "组合选股最多20个原子条件")
    return atoms


def _flatten_validated_conditions(
    group: ValidatedConditionGroup,
) -> tuple[ValidatedCondition, ...]:
    return tuple(
        condition
        for child in group.children
        for condition in (
            _flatten_validated_conditions(child)
            if isinstance(child, ValidatedConditionGroup)
            else (child,)
        )
    )


def _validated_condition_snapshot(item: ValidatedCondition) -> dict[str, object]:
    return {
        "node_type": "CONDITION",
        "condition_key": item.definition.condition_key,
        "condition_version": item.definition.version,
        "parameters": {key: _stored(value) for key, value in item.parameters.items()},
    }


def _validated_group_snapshot(item: ValidatedConditionGroup) -> dict[str, object]:
    return {
        "node_type": "GROUP",
        "operator": item.operator.value,
        "children": [
            _validated_group_snapshot(child)
            if isinstance(child, ValidatedConditionGroup)
            else _validated_condition_snapshot(child)
            for child in item.children
        ],
    }


_FORBIDDEN_KEYS = {
    "python",
    "python_code",
    "sql",
    "function",
    "function_name",
    "file",
    "file_path",
    "http",
    "url",
    "miniqmt_command",
    "trade_command",
    "order",
    "order_id",
    "fill",
    "fill_id",
}


def _assert_safe_structure(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_KEYS:
                raise ScreeningError(
                    "SCREENING_UNSAFE_SPEC_FIELD", f"ScreeningSpec禁止字段：{path}.{key}"
                )
            _assert_safe_structure(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for index, child in enumerate(value):
            _assert_safe_structure(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.strip().lower()
        unsafe_fragments = (
            "http://",
            "https://",
            "import ",
            "select ",
            "insert ",
            "update ",
            "delete ",
            "drop ",
            "__",
            ".py",
            "\\",
        )
        if any(fragment in lowered for fragment in unsafe_fragments):
            raise ScreeningError(
                "SCREENING_UNSAFE_SPEC_VALUE", f"ScreeningSpec包含禁止内容：{path}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ConditionEvaluation:
    outcome: ConditionOutcome
    score: Decimal = Decimal("0")
    reason_code: str
    reason: str
    metrics: Mapping[str, Decimal | int | bool | str | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreeningCandidate:
    instrument_id: UUID
    symbol: str
    exchange: str
    instrument_name: str
    score: Decimal
    reference_price: Decimal
    reason_code: str
    reason: str
    metrics: Mapping[str, MetricValue]


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentScreeningOutcome:
    instrument_id: UUID
    outcome: ConditionOutcome
    candidate: ScreeningCandidate | None = None
    reason_code: str | None = None
    reason: str | None = None
    failed_condition_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FeatureSnapshot:
    instrument_id: UUID
    as_of_date: date
    feature_version: str
    bars: tuple[StrategyBar, ...]
    market_sessions: tuple[date, ...]
    rolling_high_60: Decimal | None
    rolling_low_60: Decimal | None
    average_volume_20: Decimal | None
    volume_ratio_20: Decimal | None
    range_position_60: Decimal | None
    bullish_candle: bool | None


class ScreeningFeatureStore:
    """Per-run, rebuildable cache derived solely from authoritative MarketBars."""

    feature_version = "sc02a-v1"

    def __init__(
        self,
        required_condition_keys: Sequence[str] | None = None,
        market_sessions: Sequence[date] | None = None,
    ) -> None:
        self._cache: dict[tuple[object, ...], FeatureSnapshot] = {}
        self._required_condition_keys = (
            None if required_condition_keys is None else frozenset(required_condition_keys)
        )
        self._market_sessions = tuple(sorted(set(market_sessions or ())))

    def get(
        self,
        instrument: Instrument,
        bars: Sequence[StrategyBar],
        as_of_date: date,
    ) -> FeatureSnapshot:
        eligible_input = tuple(
            sorted(
                (
                    bar
                    for bar in bars
                    if bar.instrument_id == instrument.id and bar.timestamp.date() <= as_of_date
                ),
                key=lambda item: item.timestamp,
            )
        )
        source_signature: tuple[object, ...] = (
            len(eligible_input),
            None if not eligible_input else eligible_input[0].timestamp,
            None if not eligible_input else eligible_input[-1].timestamp,
            None if not eligible_input else eligible_input[-1].close,
            None if not eligible_input else eligible_input[-1].volume,
        )
        key = (
            instrument.id,
            as_of_date,
            self.feature_version,
            self._required_condition_keys,
            self._market_sessions,
            *source_signature,
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        eligible = eligible_input
        high = low = average_volume = None
        current = eligible[-1] if eligible else None
        needs_bottom_features = (
            self._required_condition_keys is None
            or "BOTTOM_VOLUME_EXPANSION" in self._required_condition_keys
        )
        if needs_bottom_features:
            prior_60 = eligible[-61:-1] if len(eligible) >= 2 else ()
            prior_20 = eligible[-21:-1] if len(eligible) >= 2 else ()
            highest = RollingHighest(60)
            lowest = RollingLowest(60)
            average_volume_indicator = RollingAverageVolume(20)
            for item in prior_60:
                high = highest.update(item.high)
                low = lowest.update(item.low)
            for item in prior_20:
                average_volume = average_volume_indicator.update(item.volume)
        volume_ratio = (
            current.volume / average_volume
            if current is not None and average_volume is not None and average_volume > 0
            else None
        )
        range_position = (
            (current.close - low) / (high - low)
            if current is not None and high is not None and low is not None and high > low
            else None
        )
        snapshot = FeatureSnapshot(
            instrument_id=instrument.id,
            as_of_date=as_of_date,
            feature_version=self.feature_version,
            bars=eligible,
            market_sessions=self._market_sessions,
            rolling_high_60=high,
            rolling_low_60=low,
            average_volume_20=average_volume,
            volume_ratio_20=volume_ratio,
            range_position_60=range_position,
            bullish_candle=(
                None
                if current is None or not needs_bottom_features
                else current.close > current.open
            ),
        )
        self._cache[key] = snapshot
        return snapshot

    def clear(self) -> None:
        self._cache.clear()


class RuleBasedScreeningEngine:
    """Evaluate a validated ScreeningSpec without I/O or trading side effects."""

    def __init__(
        self,
        catalog: ConditionCatalog,
        feature_store: ScreeningFeatureStore | None = None,
    ) -> None:
        self._catalog = catalog
        self._features = feature_store or ScreeningFeatureStore()

    @property
    def catalog(self) -> ConditionCatalog:
        return self._catalog

    def evaluate_instrument(
        self,
        spec: ScreeningSpec,
        instrument: Instrument,
        bars: Sequence[StrategyBar],
        *,
        trading_status: str | None = None,
    ) -> InstrumentScreeningOutcome:
        validated = spec.validate(self._catalog)
        snapshot = self._features.get(instrument, bars, spec.as_of_date)
        evaluations: list[tuple[ValidatedCondition, ConditionEvaluation]] = []

        def evaluate_node(
            node: ValidatedCondition | ValidatedConditionGroup,
        ) -> ConditionOutcome:
            if isinstance(node, ValidatedCondition):
                required_history = node.definition.history_bars(node.parameters)
                if len(snapshot.bars) < required_history:
                    evaluation = ConditionEvaluation(
                        outcome=ConditionOutcome.INSUFFICIENT_DATA,
                        reason_code="INSUFFICIENT_HISTORY",
                        reason=(
                            f"历史日线不足：条件“{node.definition.display_name}”"
                            f"需要{required_history}根，实际{len(snapshot.bars)}根"
                        ),
                    )
                else:
                    try:
                        evaluation = self._evaluate(
                            node,
                            instrument,
                            snapshot,
                            trading_status=trading_status,
                        )
                    except (ArithmeticError, InvalidOperation, ValueError) as exc:
                        evaluation = ConditionEvaluation(
                            outcome=ConditionOutcome.FAILED,
                            reason_code="CONDITION_EVALUATION_FAILED",
                            reason=str(exc)[:400],
                        )
                evaluations.append((node, evaluation))
                return evaluation.outcome
            outcomes = [evaluate_node(child) for child in node.children]
            if node.operator is ConditionGroupOperator.AND:
                if any(item is ConditionOutcome.NOT_MATCHED for item in outcomes):
                    return ConditionOutcome.NOT_MATCHED
                if any(item is ConditionOutcome.FAILED for item in outcomes):
                    return ConditionOutcome.FAILED
                if any(item is ConditionOutcome.INDETERMINATE for item in outcomes):
                    return ConditionOutcome.INDETERMINATE
                if any(item is ConditionOutcome.INSUFFICIENT_DATA for item in outcomes):
                    return ConditionOutcome.INSUFFICIENT_DATA
                return ConditionOutcome.MATCHED
            if any(item is ConditionOutcome.MATCHED for item in outcomes):
                return ConditionOutcome.MATCHED
            if any(item is ConditionOutcome.FAILED for item in outcomes):
                return ConditionOutcome.FAILED
            if any(item is ConditionOutcome.INDETERMINATE for item in outcomes):
                return ConditionOutcome.INDETERMINATE
            if any(item is ConditionOutcome.INSUFFICIENT_DATA for item in outcomes):
                return ConditionOutcome.INSUFFICIENT_DATA
            return ConditionOutcome.NOT_MATCHED

        group_outcome = evaluate_node(validated.root_group)
        if group_outcome is not ConditionOutcome.MATCHED:
            failed = next(
                (
                    (condition, evaluation)
                    for condition, evaluation in evaluations
                    if evaluation.outcome is group_outcome
                    or (
                        group_outcome is ConditionOutcome.INDETERMINATE
                        and evaluation.outcome
                        in {ConditionOutcome.INSUFFICIENT_DATA, ConditionOutcome.INDETERMINATE}
                    )
                ),
                evaluations[-1],
            )
            return InstrumentScreeningOutcome(
                instrument_id=instrument.id,
                outcome=group_outcome,
                reason_code=failed[1].reason_code,
                reason=failed[1].reason,
                failed_condition_key=failed[0].definition.condition_key,
            )
        current = snapshot.bars[-1]
        matched_evaluations = [
            item for _, item in evaluations if item.outcome is ConditionOutcome.MATCHED
        ]
        score = sum((item.score for item in matched_evaluations), Decimal("0"))
        metrics: dict[str, MetricValue] = {
            "feature_version": snapshot.feature_version,
            "as_of_date": snapshot.as_of_date.isoformat(),
            "market_data_time": current.timestamp.isoformat(),
            "current_close": _metric(current.close),
            "daily_return": (
                None
                if len(snapshot.bars) < 2
                else _metric(current.close / snapshot.bars[-2].close - Decimal("1"))
            ),
            "data_source": "MINIQMT",
        }
        for _, evaluation in evaluations:
            for key, value in evaluation.metrics.items():
                metrics[key] = _metric(value)
        metrics["condition_evaluations"] = [
            {
                "condition_key": condition.definition.condition_key,
                "display_name": condition.definition.display_name,
                "outcome": evaluation.outcome.value,
                "reason_code": evaluation.reason_code,
                "reason": evaluation.reason,
                "metrics": {key: _metric(value) for key, value in evaluation.metrics.items()},
            }
            for condition, evaluation in evaluations
        ]
        reason = "；".join(item.reason for item in matched_evaluations)
        return InstrumentScreeningOutcome(
            instrument_id=instrument.id,
            outcome=ConditionOutcome.MATCHED,
            candidate=ScreeningCandidate(
                instrument_id=instrument.id,
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                instrument_name=instrument.name,
                score=score,
                reference_price=current.close,
                reason_code="+".join(item.reason_code for item in matched_evaluations),
                reason=reason,
                metrics=metrics,
            ),
        )

    def rank(
        self, spec: ScreeningSpec, candidates: Sequence[ScreeningCandidate]
    ) -> tuple[ScreeningCandidate, ...]:
        ordered = list(candidates)
        rules = spec.ranking_rules or (RankingRule(field="score"),)
        # Stable sorting from the least significant rule to the most significant.
        ordered.sort(key=lambda item: (item.exchange, item.symbol, str(item.instrument_id)))
        for rule in reversed(rules):
            reverse = rule.direction is RankingDirection.DESC
            ordered.sort(
                key=lambda item: self._rank_value(item, rule.field),
                reverse=reverse,
            )
        if spec.top_n is not None:
            ordered = ordered[: spec.top_n]
        return tuple(ordered)

    @staticmethod
    def _rank_value(candidate: ScreeningCandidate, field: str) -> Decimal:
        if field == "score":
            return candidate.score
        value = candidate.metrics.get(field)
        try:
            return Decimal(str(value)) if value is not None else Decimal("-Infinity")
        except InvalidOperation:
            return Decimal("-Infinity")

    def _evaluate(
        self,
        condition: ValidatedCondition,
        instrument: Instrument,
        snapshot: FeatureSnapshot,
        *,
        trading_status: str | None,
    ) -> ConditionEvaluation:
        key = condition.definition.evaluator_key
        if key == "limit_up_pullback_v1":
            return _evaluate_limit_up_pullback(instrument, snapshot, condition.parameters)
        if key == "recent_limit_up_event_v1":
            return _evaluate_recent_limit_up_event(instrument, snapshot, condition.parameters)
        if key == "bottom_volume_expansion_v1":
            return _evaluate_bottom_volume_expansion(snapshot, condition.parameters)
        return _evaluate_ordinary(key, snapshot, condition.parameters, trading_status)


def _not_matched(code: str, reason: str) -> ConditionEvaluation:
    return ConditionEvaluation(
        outcome=ConditionOutcome.NOT_MATCHED,
        reason_code=code,
        reason=reason,
    )


def _evaluate_bottom_volume_expansion(
    snapshot: FeatureSnapshot, parameters: Mapping[str, ConditionValue]
) -> ConditionEvaluation:
    range_window = int(parameters["range_window"] or 60)
    volume_window = int(parameters["volume_window"] or 20)
    bottom_ratio = _decimal(parameters["bottom_ratio"], "bottom_ratio")
    minimum_multiple = _decimal(parameters["minimum_volume_multiple"], "minimum_volume_multiple")
    bars = snapshot.bars
    current = bars[-1]
    prior_range = bars[-range_window - 1 : -1]
    prior_volume = bars[-volume_window - 1 : -1]
    if len(prior_range) < range_window or len(prior_volume) < volume_window:
        return ConditionEvaluation(
            outcome=ConditionOutcome.INSUFFICIENT_DATA,
            reason_code="BOTTOM_VOLUME_INSUFFICIENT_HISTORY",
            reason="计算底部放倍量所需历史日线不足",
        )
    highest = RollingHighest(range_window)
    lowest = RollingLowest(range_window)
    rolling_high = rolling_low = None
    for item in prior_range:
        rolling_high = highest.update(item.high)
        rolling_low = lowest.update(item.low)
    if rolling_high is None or rolling_low is None:
        return ConditionEvaluation(
            outcome=ConditionOutcome.INSUFFICIENT_DATA,
            reason_code="BOTTOM_VOLUME_INSUFFICIENT_HISTORY",
            reason="计算底部区间所需历史日线不足",
        )
    denominator = rolling_high - rolling_low
    if denominator <= 0:
        return ConditionEvaluation(
            outcome=ConditionOutcome.INDETERMINATE,
            reason_code="RANGE_POSITION_ZERO_DENOMINATOR",
            reason="历史价格区间最高价等于最低价，无法计算区间位置",
        )
    range_position = (current.close - rolling_low) / denominator
    average_volume_indicator = RollingAverageVolume(volume_window)
    average_volume = None
    for item in prior_volume:
        average_volume = average_volume_indicator.update(item.volume)
    if average_volume is None:
        return ConditionEvaluation(
            outcome=ConditionOutcome.INSUFFICIENT_DATA,
            reason_code="BOTTOM_VOLUME_INSUFFICIENT_HISTORY",
            reason="计算平均成交量所需历史日线不足",
        )
    if average_volume <= 0:
        return ConditionEvaluation(
            outcome=ConditionOutcome.INDETERMINATE,
            reason_code="AVERAGE_VOLUME_ZERO",
            reason="此前平均成交量为0，无法计算成交量倍数",
        )
    volume_multiple = current.volume / average_volume
    bullish = current.close > current.open
    if range_position > bottom_ratio:
        return _not_matched("RANGE_POSITION_TOO_HIGH", "当前价格不在设定的底部区间")
    if volume_multiple <= minimum_multiple:
        return _not_matched("VOLUME_MULTIPLE_TOO_LOW", "当前成交量未超过设定倍数")
    if bool(parameters["require_bullish_candle"]) and not bullish:
        return _not_matched("BULLISH_CANDLE_REQUIRED", "当日收盘价未高于开盘价")
    return ConditionEvaluation(
        outcome=ConditionOutcome.MATCHED,
        score=volume_multiple,
        reason_code="BOTTOM_VOLUME_EXPANSION_MATCHED",
        reason=(
            f"当前位于此前{range_window}日价格区间底部"
            f"{(range_position * Decimal('100')).quantize(Decimal('0.01'))}%；"
            f"当前成交量为此前{volume_window}日平均成交量的"
            f"{volume_multiple.quantize(Decimal('0.01'))}倍；当日收阳"
        ),
        metrics={
            "rolling_high_60": rolling_high,
            "rolling_low_60": rolling_low,
            "current_close": current.close,
            "range_position": range_position,
            "average_volume_20": average_volume,
            "current_volume": current.volume,
            "volume_multiple": volume_multiple,
            "bullish_candle": bullish,
            "range_window": range_window,
            "volume_window": volume_window,
            "exclude_current_from_range": True,
            "exclude_current_from_average_volume": True,
        },
    )


def _explicit_upper_limit(instrument: Instrument, event_date: date) -> Decimal | None:
    values = instrument.metadata.get("upper_limit_prices")
    if isinstance(values, Mapping):
        value = values.get(event_date.isoformat())
        if value is not None:
            parsed = _decimal(value, "upper_limit_price")
            return parsed if parsed > 0 else None
    value = instrument.metadata.get("upper_limit_price")
    if value is not None:
        parsed = _decimal(value, "upper_limit_price")
        return parsed if parsed > 0 else None
    return None


def _formal_price_limit_ratio(
    instrument: Instrument, event_date: date, event_index: int, bars: Sequence[StrategyBar]
) -> Decimal | None:
    explicit = instrument.metadata.get("price_limit_ratio")
    if explicit is not None:
        ratio = _decimal(explicit, "price_limit_ratio")
        return ratio if Decimal("0") < ratio <= Decimal("1") else None
    if bool(instrument.metadata.get("is_st")) or instrument.name.strip().upper().startswith(
        ("ST", "*ST", "S*ST")
    ):
        # Historical ST rules have board/date exceptions.  Without a persisted
        # formal ratio or actual limit price, guessing 5% would fabricate facts.
        return None
    if instrument.listed_at is not None:
        listed_bars = [
            item
            for item in bars[: event_index + 1]
            if item.timestamp.date() >= instrument.listed_at
        ]
        if len(listed_bars) <= 5:
            return None
    symbol = instrument.symbol
    if instrument.exchange == "BSE":
        return Decimal("0.30") if event_date >= date(2021, 11, 15) else None
    if instrument.exchange == "SSE" and symbol.startswith(("688", "689")):
        return Decimal("0.20")
    if instrument.exchange == "SZSE" and symbol.startswith(("300", "301")):
        return Decimal("0.20") if event_date >= date(2020, 8, 24) else Decimal("0.10")
    if instrument.exchange in {"SSE", "SZSE"}:
        return Decimal("0.10")
    return None


def _upper_limit_price(
    instrument: Instrument,
    event_date: date,
    previous_close: Decimal,
    event_index: int,
    bars: Sequence[StrategyBar],
) -> Decimal | None:
    actual = _explicit_upper_limit(instrument, event_date)
    if actual is not None:
        return actual
    ratio = _formal_price_limit_ratio(instrument, event_date, event_index, bars)
    if ratio is None:
        return None
    return (previous_close * (Decimal("1") + ratio)).quantize(
        instrument.price_tick, rounding=ROUND_HALF_UP
    )


def _evaluate_limit_up_pullback(
    instrument: Instrument,
    snapshot: FeatureSnapshot,
    parameters: Mapping[str, ConditionValue],
) -> ConditionEvaluation:
    bars = snapshot.bars
    lookback = int(parameters["lookback_days"] or 20)
    maximum_distance = _decimal(parameters["maximum_distance_pct"], "maximum_distance_pct")
    minimum_ratio = _decimal(
        parameters["minimum_price_ratio_to_anchor"], "minimum_price_ratio_to_anchor"
    )
    maximum_volume_ratio = _decimal(parameters["maximum_volume_ratio"], "maximum_volume_ratio")
    current = bars[-1]
    event_dates = {item for item in snapshot.market_sessions if item < snapshot.as_of_date}
    if event_dates:
        event_dates = set(sorted(event_dates)[-lookback:])
    start = max(1, len(bars) - 1 - lookback) if not event_dates else 1
    unknown_limit_days = 0
    event_index: int | None = None
    upper_limit: Decimal | None = None
    for index in range(len(bars) - 2, start - 1, -1):
        previous = bars[index - 1]
        candidate = bars[index]
        if event_dates and candidate.timestamp.date() not in event_dates:
            continue
        resolved = _upper_limit_price(
            instrument,
            candidate.timestamp.date(),
            previous.close,
            index,
            bars,
        )
        if resolved is None:
            unknown_limit_days += 1
            continue
        if candidate.close >= resolved:
            event_index = index
            upper_limit = resolved
            break
    if event_index is None:
        if unknown_limit_days:
            return ConditionEvaluation(
                outcome=ConditionOutcome.INDETERMINATE,
                reason_code="LIMIT_PRICE_NOT_AVAILABLE",
                reason="历史区间存在无法取得可靠涨停价的交易日，不能伪造涨停事件",
            )
        return _not_matched("LIMIT_UP_EVENT_NOT_FOUND", f"此前{lookback}日未发现涨停事件")
    event = bars[event_index]
    previous_close = bars[event_index - 1].close
    if event.volume <= 0:
        return ConditionEvaluation(
            outcome=ConditionOutcome.INDETERMINATE,
            reason_code="LIMIT_UP_VOLUME_NOT_AVAILABLE",
            reason="涨停日成交量无效，无法计算缩量比例",
        )
    price_ratio = current.close / previous_close
    distance = price_ratio - Decimal("1")
    protection_price = previous_close * minimum_ratio
    volume_ratio = current.volume / event.volume
    if price_ratio < minimum_ratio:
        return _not_matched("PROTECTION_PRICE_BROKEN", "当前价格跌破保护价")
    if abs(distance) > maximum_distance:
        return _not_matched("ANCHOR_DISTANCE_EXCEEDED", "当前价格距离起涨锚点超过上限")
    if volume_ratio > maximum_volume_ratio:
        return _not_matched("PULLBACK_VOLUME_TOO_HIGH", "当前成交量未缩至设定上限")
    trading_days_ago = (
        len(
            [
                item
                for item in snapshot.market_sessions
                if event.timestamp.date() < item <= snapshot.as_of_date
            ]
        )
        if snapshot.market_sessions
        else len(bars) - 1 - event_index
    )
    return ConditionEvaluation(
        outcome=ConditionOutcome.MATCHED,
        score=Decimal("1") - volume_ratio + Decimal("1") / Decimal(trading_days_ago + 1),
        reason_code="LIMIT_UP_PULLBACK_MATCHED",
        reason=(
            f"{trading_days_ago}个交易日前出现涨停；涨停前收盘价为"
            f"{previous_close.quantize(Decimal('0.01'))}元；当前收盘价为"
            f"{current.close.quantize(Decimal('0.01'))}元；当前距离起涨价"
            f"{(distance * Decimal('100')).quantize(Decimal('0.01'))}%；当前成交量为"
            f"涨停日的{(volume_ratio * Decimal('100')).quantize(Decimal('0.01'))}%；"
            "当前价格未跌破保护价"
        ),
        metrics={
            "limit_up_date": event.timestamp.date().isoformat(),
            "upper_limit_price": upper_limit,
            "previous_close_before_limit_up": previous_close,
            "current_close": current.close,
            "distance_to_anchor": distance,
            "protection_price": protection_price,
            "limit_up_day_volume": event.volume,
            "current_volume": current.volume,
            "volume_ratio": volume_ratio,
            "trading_days_since_limit_up": trading_days_ago,
            "event_selection": "LATEST_VALID",
            "anchor_price": "PRE_LIMIT_PREVIOUS_CLOSE",
        },
    )


def _evaluate_recent_limit_up_event(
    instrument: Instrument,
    snapshot: FeatureSnapshot,
    parameters: Mapping[str, ConditionValue],
) -> ConditionEvaluation:
    lookback = int(parameters["lookback_days"] or 5)
    minimum_occurrences = int(parameters["minimum_occurrences"] or 1)
    event_selection = str(parameters["event_selection"] or "LATEST_VALID")
    require_reliable = bool(parameters["require_reliable_limit_price"])
    sessions = tuple(item for item in snapshot.market_sessions if item <= snapshot.as_of_date)
    target_dates = set(sessions[-lookback:]) if sessions else set()
    bars = snapshot.bars
    events: list[tuple[date, Decimal]] = []
    unknown_dates: list[str] = []
    for index in range(1, len(bars)):
        current = bars[index]
        event_date = current.timestamp.date()
        if target_dates and event_date not in target_dates:
            continue
        if not target_dates and index < len(bars) - lookback:
            continue
        resolved = _upper_limit_price(
            instrument,
            event_date,
            bars[index - 1].close,
            index,
            bars,
        )
        if resolved is None:
            unknown_dates.append(event_date.isoformat())
            continue
        if current.close >= resolved:
            events.append((event_date, resolved))
    if require_reliable and unknown_dates:
        return ConditionEvaluation(
            outcome=ConditionOutcome.INDETERMINATE,
            reason_code="LIMIT_PRICE_NOT_AVAILABLE",
            reason="回看窗口存在无法取得可靠涨停价的交易日，不能可靠判断涨停事件",
            metrics={"unknown_limit_price_dates": ",".join(unknown_dates)},
        )
    if len(events) < minimum_occurrences:
        return _not_matched(
            "RECENT_LIMIT_UP_EVENT_NOT_FOUND",
            f"近{lookback}个交易日涨停{len(events)}次，少于要求的{minimum_occurrences}次",
        )
    selected = events[-1] if event_selection == "LATEST_VALID" else events[0]
    return ConditionEvaluation(
        outcome=ConditionOutcome.MATCHED,
        score=Decimal(len(events)),
        reason_code="RECENT_LIMIT_UP_EVENT_MATCHED",
        reason=(
            f"近{lookback}个交易日出现{len(events)}次可靠涨停，最近一次为{selected[0].isoformat()}"
        ),
        metrics={
            "lookback_days": lookback,
            "limit_up_occurrences": len(events),
            "latest_limit_up_date": selected[0].isoformat(),
            "latest_upper_limit_price": selected[1],
            "event_selection": event_selection,
            "require_reliable_limit_price": require_reliable,
        },
    )


def _sma_value(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ScreeningError("SCREENING_INSUFFICIENT_DATA", "没有可计算的数值")
    indicator = SimpleMovingAverage(len(values))
    result = None
    for value in values:
        result = indicator.update(value)
    if result is None:
        raise ScreeningError("SCREENING_INSUFFICIENT_DATA", "SMA历史数据不足")
    return result


def _ema_value(values: Sequence[Decimal], window: int) -> Decimal:
    indicator = ExponentialMovingAverage(window)
    result = None
    for value in values:
        result = indicator.update(value)
    if result is None:
        raise ScreeningError("SCREENING_INSUFFICIENT_DATA", "EMA历史数据不足")
    return result


def _relation_matches(left: Decimal, right: Decimal, relation: str) -> bool:
    return {
        "ABOVE": left > right,
        "BELOW": left < right,
        "GREATER_OR_EQUAL": left >= right,
        "LESS_OR_EQUAL": left <= right,
    }[relation]


def _evaluate_ordinary(
    evaluator_key: str,
    snapshot: FeatureSnapshot,
    parameters: Mapping[str, ConditionValue],
    trading_status: str | None,
) -> ConditionEvaluation:
    bars = snapshot.bars
    current = bars[-1]
    metrics: dict[str, Decimal | int | bool | str | None]
    if evaluator_key == "n_day_high_breakout_v1":
        window = int(parameters["window"] or 20)
        high = max(item.high for item in bars[-window - 1 : -1])
        matched = current.close > high
        metrics = {"prior_high": high, "current_close": current.close}
    elif evaluator_key == "n_day_low_v1":
        window = int(parameters["window"] or 20)
        low = min(item.low for item in bars[-window - 1 : -1])
        matched = current.close <= low
        metrics = {"prior_low": low, "current_close": current.close}
    elif evaluator_key in {"sma_relation_v1", "ema_relation_v1"}:
        short = int(parameters["short_window"] or 5)
        long = int(parameters["long_window"] or 20)
        closes = [item.close for item in bars]
        if evaluator_key == "sma_relation_v1":
            left = _sma_value(closes[-short:])
            right = _sma_value(closes[-long:])
        else:
            left, right = _ema_value(closes, short), _ema_value(closes, long)
        relation = str(parameters["relation"])
        matched = _relation_matches(left, right, relation)
        metrics = {"short_value": left, "long_value": right, "relation": relation}
    elif evaluator_key == "average_volume_v1":
        window = int(parameters["window"] or 20)
        average = _sma_value([item.volume for item in bars[-window:]])
        threshold = _decimal(parameters["minimum"], "minimum")
        matched = average >= threshold
        metrics = {"average_volume": average}
    elif evaluator_key == "volume_ratio_v1":
        window = int(parameters["window"] or 20)
        average = _sma_value([item.volume for item in bars[-window - 1 : -1]])
        if average <= 0:
            return ConditionEvaluation(
                outcome=ConditionOutcome.INDETERMINATE,
                reason_code="AVERAGE_VOLUME_ZERO",
                reason="平均成交量为0，无法计算成交量比例",
            )
        ratio = current.volume / average
        threshold = _decimal(parameters["minimum_ratio"], "minimum_ratio")
        matched = ratio >= threshold
        metrics = {"average_volume": average, "volume_ratio": ratio}
    elif evaluator_key == "n_day_return_v1":
        window = int(parameters["window"] or 20)
        base = bars[-window - 1].close
        if base <= 0:
            raise ScreeningError("SCREENING_INVALID_BAR", "收益率基准价格无效")
        value = current.close / base - Decimal("1")
        minimum = _decimal(parameters["minimum_return"], "minimum_return")
        maximum = parameters.get("maximum_return")
        matched = value >= minimum and (
            maximum is None or value <= _decimal(maximum, "maximum_return")
        )
        metrics = {"n_day_return": value}
    elif evaluator_key == "range_position_v1":
        window = int(parameters["window"] or 60)
        prior = bars[-window - 1 : -1]
        high, low = max(item.high for item in prior), min(item.low for item in prior)
        if high <= low:
            return ConditionEvaluation(
                outcome=ConditionOutcome.INDETERMINATE,
                reason_code="RANGE_POSITION_ZERO_DENOMINATOR",
                reason="价格区间分母为0",
            )
        value = (current.close - low) / (high - low)
        maximum = _decimal(parameters["maximum_position"], "maximum_position")
        matched = value <= maximum
        metrics = {"range_position": value, "rolling_high": high, "rolling_low": low}
    elif evaluator_key == "bullish_candle_v1":
        matched = current.close > current.open
        metrics = {"bullish_candle": matched}
    elif evaluator_key == "amount_threshold_v1":
        threshold = _decimal(parameters["minimum_amount"], "minimum_amount")
        if current.amount is None:
            return ConditionEvaluation(
                outcome=ConditionOutcome.INDETERMINATE,
                reason_code="AMOUNT_NOT_AVAILABLE",
                reason="成交额数据不可用",
            )
        matched = current.amount >= threshold
        metrics = {"current_amount": current.amount}
    elif evaluator_key == "trading_status_v1":
        required = str(parameters["status"])
        if trading_status is None:
            return ConditionEvaluation(
                outcome=ConditionOutcome.INDETERMINATE,
                reason_code="TRADING_STATUS_NOT_AVAILABLE",
                reason="筛选日交易状态不可用",
            )
        matched = trading_status == required
        metrics = {"trading_status": trading_status}
    else:
        raise ScreeningError("SCREENING_EVALUATOR_NOT_FOUND", f"未知计算器：{evaluator_key}")
    if not matched:
        return _not_matched("CONDITION_NOT_MATCHED", "未满足条件")
    return ConditionEvaluation(
        outcome=ConditionOutcome.MATCHED,
        score=Decimal("1"),
        reason_code="CONDITION_MATCHED",
        reason="满足标准条件",
        metrics=metrics,
    )


def _param(
    name: str,
    display_name: str,
    kind: ConditionParameterType,
    description: str,
    default: ConditionValue,
    *,
    minimum: Decimal | int | None = None,
    maximum: Decimal | int | None = None,
    enum_values: tuple[str, ...] = (),
    unit: str | None = None,
    display_unit: str | None = None,
    precision: int | None = None,
    placeholder: str | None = None,
    help_text: str | None = None,
) -> ConditionParameterSchema:
    return ConditionParameterSchema(
        name=name,
        display_name=display_name,
        parameter_type=kind,
        description=description,
        default=default,
        required=True,
        min_value=minimum,
        max_value=maximum,
        enum_values=enum_values,
        unit=unit,
        display_unit=display_unit,
        precision=precision,
        placeholder=placeholder,
        help_text=help_text,
    )


def _definition(
    key: str,
    display_name: str,
    description: str,
    category: ConditionCategory,
    parameters: tuple[ConditionParameterSchema, ...],
    required_fields: tuple[str, ...],
    required_history_bars: int,
    explanation: str,
    aliases: tuple[str, ...] = (),
) -> ConditionDefinition:
    return ConditionDefinition(
        condition_key=key,
        display_name=display_name,
        description=description,
        category=category,
        parameter_schema=parameters,
        required_fields=required_fields,
        required_history_bars=required_history_bars,
        supported_timeframes=(MarketTimeframe.DAY_1,),
        price_adjustment_mode=PriceAdjustmentMode.RAW,
        evaluator_key=f"{key.lower()}_v1",
        explanation_template=explanation,
        version="1.0.0",
        aliases=aliases,
    )


def register_builtin_conditions(catalog: ConditionCatalog) -> None:
    """Register the stable SC02-A catalog without exposing evaluator names to callers."""

    def integer_window(default: int = 20) -> tuple[ConditionParameterSchema, ...]:
        return (
            _param(
                "window",
                "统计窗口",
                ConditionParameterType.INTEGER,
                "向前统计的交易日数量",
                default,
                minimum=1,
                maximum=500,
                unit="交易日",
            ),
        )

    relation_params = (
        _param(
            "short_window",
            "短周期",
            ConditionParameterType.INTEGER,
            "短周期交易日数量",
            5,
            minimum=1,
            maximum=250,
        ),
        _param(
            "long_window",
            "长周期",
            ConditionParameterType.INTEGER,
            "长周期交易日数量",
            20,
            minimum=2,
            maximum=500,
        ),
        _param(
            "relation",
            "比较关系",
            ConditionParameterType.ENUM,
            "短周期指标相对长周期指标的关系",
            "ABOVE",
            enum_values=("ABOVE", "BELOW", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"),
        ),
    )
    definitions = (
        _definition(
            "N_DAY_HIGH_BREAKOUT",
            "N日新高突破",
            "当前收盘价突破此前N日最高价",
            ConditionCategory.BREAKOUT,
            integer_window(),
            ("high", "close"),
            21,
            "当前收盘价突破此前{window}日最高价",
            ("突破", "新高", "价格突破", "N日突破"),
        ),
        _definition(
            "N_DAY_LOW",
            "N日新低",
            "当前收盘价不高于此前N日最低价",
            ConditionCategory.RANGE_POSITION,
            integer_window(),
            ("low", "close"),
            21,
            "当前收盘价触及此前{window}日低位",
            ("新低", "低点", "N日最低"),
        ),
        _definition(
            "SMA_RELATION",
            "简单均线关系",
            "比较短周期与长周期简单移动平均线",
            ConditionCategory.MOVING_AVERAGE,
            relation_params,
            ("close",),
            20,
            "短周期均线与长周期均线满足{relation}",
            ("均线", "简单移动平均线", "SMA"),
        ),
        _definition(
            "EMA_RELATION",
            "指数均线关系",
            "比较短周期与长周期指数移动平均线",
            ConditionCategory.MOVING_AVERAGE,
            relation_params,
            ("close",),
            20,
            "短周期指数均线与长周期指数均线满足{relation}",
            ("指数均线", "EMA", "趋势均线"),
        ),
        _definition(
            "AVERAGE_VOLUME",
            "平均成交量",
            "此前窗口平均成交量达到下限",
            ConditionCategory.VOLUME,
            (
                *integer_window(),
                _param(
                    "minimum",
                    "平均成交量下限",
                    ConditionParameterType.DECIMAL,
                    "窗口平均成交量的最低要求",
                    "0",
                    minimum=Decimal("0"),
                ),
            ),
            ("volume",),
            20,
            "此前{window}日平均成交量达到下限",
            ("均量", "平均成交量"),
        ),
        _definition(
            "VOLUME_RATIO",
            "成交量比例",
            "当前成交量相对此前均量的比例",
            ConditionCategory.VOLUME,
            (
                *integer_window(),
                _param(
                    "minimum_ratio",
                    "最低成交量倍数",
                    ConditionParameterType.DECIMAL,
                    "当前成交量相对此前均量的最低倍数",
                    "2",
                    minimum=Decimal("0"),
                    maximum=Decimal("100"),
                ),
            ),
            ("volume",),
            21,
            "当前成交量为此前均量的{volume_ratio}倍",
            ("放量", "成交量倍数", "量比", "倍量"),
        ),
        _definition(
            "N_DAY_RETURN",
            "N日涨跌幅",
            "当前收盘价相对N日前收盘价的收益率",
            ConditionCategory.RETURN,
            (
                *integer_window(),
                _param(
                    "minimum_return",
                    "最低涨跌幅",
                    ConditionParameterType.PERCENTAGE,
                    "N日涨跌幅下限",
                    "0",
                    minimum=Decimal("-1"),
                    maximum=Decimal("10"),
                ),
                ConditionParameterSchema(
                    name="maximum_return",
                    display_name="最高涨跌幅",
                    parameter_type=ConditionParameterType.PERCENTAGE,
                    description="可选的N日涨跌幅上限",
                    default=None,
                    nullable=True,
                    min_value=Decimal("-1"),
                    max_value=Decimal("10"),
                ),
            ),
            ("close",),
            21,
            "此前{window}日涨跌幅为{n_day_return}",
            ("涨幅", "跌幅", "收益率", "N日涨跌"),
        ),
        _definition(
            "RANGE_POSITION",
            "区间位置",
            "当前收盘价在此前价格区间中的相对位置",
            ConditionCategory.RANGE_POSITION,
            (
                _param(
                    "window",
                    "价格区间窗口",
                    ConditionParameterType.INTEGER,
                    "此前价格区间的交易日数量",
                    60,
                    minimum=2,
                    maximum=500,
                ),
                _param(
                    "maximum_position",
                    "最高区间位置",
                    ConditionParameterType.DECIMAL,
                    "允许的最高区间位置",
                    "0.20",
                    minimum=Decimal("0"),
                    maximum=Decimal("1"),
                ),
            ),
            ("high", "low", "close"),
            61,
            "当前位于此前{window}日价格区间的{range_position}",
            ("区间位置", "低位", "高位"),
        ),
        _definition(
            "BULLISH_CANDLE",
            "收阳",
            "当日收盘价高于开盘价",
            ConditionCategory.CANDLE,
            (),
            ("open", "close"),
            1,
            "当日收盘价高于开盘价",
            ("阳线", "收阳", "上涨K线"),
        ),
        _definition(
            "AMOUNT_THRESHOLD",
            "成交额下限",
            "当日成交额达到设定下限",
            ConditionCategory.AMOUNT,
            (
                _param(
                    "minimum_amount",
                    "最低成交额",
                    ConditionParameterType.AMOUNT,
                    "当日最低成交额",
                    "0",
                    minimum=Decimal("0"),
                    unit="元",
                    display_unit="亿元",
                    precision=2,
                    placeholder="例如 50（亿元）",
                    help_text="输入以亿元展示，保存和计算时统一换算为元",
                ),
            ),
            ("amount",),
            1,
            "当日成交额达到{minimum_amount}元",
            ("成交额", "成交金额", "流动性", "亿元"),
        ),
        _definition(
            "TRADING_STATUS",
            "交易状态",
            "筛选日交易状态满足设定值",
            ConditionCategory.TRADING,
            (
                _param(
                    "status",
                    "交易状态",
                    ConditionParameterType.ENUM,
                    "筛选日要求的交易状态",
                    "TRADING",
                    enum_values=("TRADING", "SUSPENDED"),
                ),
            ),
            ("trading_status",),
            1,
            "筛选日交易状态为{status}",
            ("交易状态", "停牌", "正常交易"),
        ),
        ConditionDefinition(
            condition_key="RECENT_LIMIT_UP_EVENT",
            display_name="近期涨停事件",
            description="在最近N个共同市场交易日内至少出现指定次数的可靠涨停",
            category=ConditionCategory.LIMIT_UP_EVENT,
            parameter_schema=(
                _param(
                    "lookback_days",
                    "回看交易日数",
                    ConditionParameterType.TRADING_DAY_WINDOW,
                    "以市场共同交易日为准向前回看的窗口",
                    5,
                    minimum=1,
                    maximum=250,
                    unit="交易日",
                    display_unit="个交易日",
                    precision=0,
                    placeholder="例如 5",
                ),
                _param(
                    "minimum_occurrences",
                    "最少涨停次数",
                    ConditionParameterType.INTEGER,
                    "回看窗口内至少出现的涨停次数",
                    1,
                    minimum=1,
                    maximum=50,
                    unit="次",
                    precision=0,
                    placeholder="例如 1",
                ),
                _param(
                    "event_selection",
                    "事件选择方式",
                    ConditionParameterType.ENUM,
                    "存在多次涨停时用于展示和解释的事件",
                    "LATEST_VALID",
                    enum_values=("LATEST_VALID", "EARLIEST_VALID"),
                ),
                _param(
                    "require_reliable_limit_price",
                    "要求可靠涨停价",
                    ConditionParameterType.BOOLEAN,
                    "无法取得可靠涨停价时返回无法判断，不使用固定比例猜测",
                    True,
                ),
            ),
            required_fields=("close", "price_limit", "trading_calendar"),
            required_history_bars=7,
            supported_timeframes=(MarketTimeframe.DAY_1,),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
            evaluator_key="recent_limit_up_event_v1",
            explanation_template="近{lookback_days}个交易日出现{limit_up_occurrences}次涨停",
            version="1.0.0",
            aliases=("近5日涨停", "近期涨停", "涨停次数", "涨停事件", "最近涨停"),
        ),
        ConditionDefinition(
            condition_key="LIMIT_UP_PULLBACK",
            display_name="涨停回踩",
            description="最近涨停后回踩起涨锚点且成交量显著收缩",
            category=ConditionCategory.COMPOSITE_PATTERN,
            parameter_schema=(
                _param(
                    "lookback_days",
                    "回看交易日数",
                    ConditionParameterType.INTEGER,
                    "向前寻找涨停事件的交易日数量",
                    20,
                    minimum=2,
                    maximum=250,
                ),
                _param(
                    "event_selection",
                    "事件选择",
                    ConditionParameterType.ENUM,
                    "多次涨停时选择最近且数据完整的事件",
                    "LATEST_VALID",
                    enum_values=("LATEST_VALID",),
                ),
                _param(
                    "anchor_price",
                    "锚点价格",
                    ConditionParameterType.ENUM,
                    "涨停前一交易日收盘价",
                    "PRE_LIMIT_PREVIOUS_CLOSE",
                    enum_values=("PRE_LIMIT_PREVIOUS_CLOSE",),
                ),
                _param(
                    "maximum_distance_pct",
                    "最大锚点距离",
                    ConditionParameterType.PERCENTAGE,
                    "当前收盘价距离锚点的最大绝对比例",
                    "0.03",
                    minimum=Decimal("0"),
                    maximum=Decimal("1"),
                ),
                _param(
                    "minimum_price_ratio_to_anchor",
                    "最低保护比例",
                    ConditionParameterType.PERCENTAGE,
                    "当前价格不得低于锚点的该比例",
                    "0.98",
                    minimum=Decimal("0"),
                    maximum=Decimal("2"),
                ),
                _param(
                    "volume_reference",
                    "成交量参照",
                    ConditionParameterType.ENUM,
                    "使用涨停日成交量作为参照",
                    "LIMIT_UP_DAY_VOLUME",
                    enum_values=("LIMIT_UP_DAY_VOLUME",),
                ),
                _param(
                    "maximum_volume_ratio",
                    "最大成交量比例",
                    ConditionParameterType.PERCENTAGE,
                    "当前成交量不得超过涨停日成交量的该比例",
                    "0.50",
                    minimum=Decimal("0"),
                    maximum=Decimal("10"),
                ),
            ),
            required_fields=("open", "high", "low", "close", "volume", "price_limit"),
            required_history_bars=22,
            supported_timeframes=(MarketTimeframe.DAY_1,),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
            evaluator_key="limit_up_pullback_v1",
            explanation_template=(
                "{trading_days_since_limit_up}个交易日前涨停，当前距锚点"
                "{distance_to_anchor}，成交量为涨停日的{volume_ratio}"
            ),
            version="1.0.0",
        ),
        ConditionDefinition(
            condition_key="BOTTOM_VOLUME_EXPANSION",
            display_name="底部放倍量",
            description="价格位于历史区间底部、成交量超过此前均量且当日收阳",
            category=ConditionCategory.COMPOSITE_PATTERN,
            parameter_schema=(
                _param(
                    "range_window",
                    "价格区间窗口",
                    ConditionParameterType.INTEGER,
                    "此前价格高低区间交易日数量",
                    60,
                    minimum=2,
                    maximum=500,
                ),
                _param(
                    "bottom_ratio",
                    "底部区间比例",
                    ConditionParameterType.PERCENTAGE,
                    "当前价格允许处于区间的最高位置",
                    "0.20",
                    minimum=Decimal("0"),
                    maximum=Decimal("1"),
                ),
                _param(
                    "volume_window",
                    "平均成交量窗口",
                    ConditionParameterType.INTEGER,
                    "此前平均成交量交易日数量",
                    20,
                    minimum=1,
                    maximum=250,
                ),
                _param(
                    "minimum_volume_multiple",
                    "最低成交量倍数",
                    ConditionParameterType.DECIMAL,
                    "当前成交量必须超过的此前均量倍数",
                    "2",
                    minimum=Decimal("0"),
                    maximum=Decimal("100"),
                ),
                _param(
                    "require_bullish_candle",
                    "要求收阳",
                    ConditionParameterType.BOOLEAN,
                    "要求当日收盘价高于开盘价",
                    True,
                ),
                _param(
                    "exclude_current_from_range",
                    "区间排除当日",
                    ConditionParameterType.BOOLEAN,
                    "计算价格区间时强制排除当前交易日",
                    True,
                ),
                _param(
                    "exclude_current_from_average_volume",
                    "均量排除当日",
                    ConditionParameterType.BOOLEAN,
                    "计算平均成交量时强制排除当前交易日",
                    True,
                ),
            ),
            required_fields=("open", "high", "low", "close", "volume"),
            required_history_bars=61,
            supported_timeframes=(MarketTimeframe.DAY_1,),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
            evaluator_key="bottom_volume_expansion_v1",
            explanation_template=(
                "当前位于此前60日区间底部{range_position}，"
                "成交量为此前20日均量的{volume_multiple}倍且当日收阳"
            ),
            version="1.0.0",
        ),
    )
    for definition in definitions:
        catalog.register(definition)


def builtin_condition_catalog() -> ConditionCatalog:
    catalog = ConditionCatalog()
    register_builtin_conditions(catalog)
    return catalog


def screening_templates() -> tuple[ScreeningSpec, ...]:
    today = date.today()
    return (
        ScreeningSpec(
            schema_version=1,
            name="涨停回踩",
            origin="BUILTIN_TEMPLATE",
            universe_spec=UniverseSpec(),
            as_of_date=today,
            timeframe=MarketTimeframe.DAY_1,
            conditions=(ScreeningCondition(condition_key="LIMIT_UP_PULLBACK"),),
            ranking_rules=(RankingRule(field="score", direction=RankingDirection.DESC),),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
        ),
        ScreeningSpec(
            schema_version=1,
            name="底部放倍量",
            origin="BUILTIN_TEMPLATE",
            universe_spec=UniverseSpec(),
            as_of_date=today,
            timeframe=MarketTimeframe.DAY_1,
            conditions=(ScreeningCondition(condition_key="BOTTOM_VOLUME_EXPANSION"),),
            ranking_rules=(RankingRule(field="volume_multiple", direction=RankingDirection.DESC),),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
        ),
        ScreeningSpec(
            schema_version=1,
            name="成交量异常",
            origin="BUILTIN_TEMPLATE",
            universe_spec=UniverseSpec(),
            as_of_date=today,
            timeframe=MarketTimeframe.DAY_1,
            conditions=(
                ScreeningCondition(
                    condition_key="VOLUME_RATIO",
                    parameters={"window": 20, "minimum_ratio": "2"},
                ),
            ),
            ranking_rules=(RankingRule(field="volume_multiple", direction=RankingDirection.DESC),),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
        ),
        ScreeningSpec(
            schema_version=1,
            name="涨停后回落",
            origin="BUILTIN_TEMPLATE",
            universe_spec=UniverseSpec(),
            as_of_date=today,
            timeframe=MarketTimeframe.DAY_1,
            conditions=(
                ScreeningCondition(
                    condition_key="LIMIT_UP_PULLBACK",
                    parameters={
                        "lookback_days": 20,
                        "event_selection": "LATEST_VALID",
                        "anchor_price": "PRE_LIMIT_PREVIOUS_CLOSE",
                        "maximum_distance_pct": "0.08",
                        "minimum_price_ratio_to_anchor": "0.95",
                        "volume_reference": "LIMIT_UP_DAY_VOLUME",
                        "maximum_volume_ratio": "0.80",
                    },
                ),
            ),
            ranking_rules=(RankingRule(field="distance_to_anchor"),),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
        ),
        ScreeningSpec(
            schema_version=1,
            name="放量突破",
            origin="BUILTIN_TEMPLATE",
            universe_spec=UniverseSpec(),
            as_of_date=today,
            timeframe=MarketTimeframe.DAY_1,
            conditions=(
                ScreeningCondition(condition_key="N_DAY_HIGH_BREAKOUT", parameters={"window": 20}),
                ScreeningCondition(
                    condition_key="VOLUME_RATIO",
                    parameters={"window": 20, "minimum_ratio": "1.5"},
                ),
            ),
            ranking_rules=(RankingRule(field="volume_multiple", direction=RankingDirection.DESC),),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
        ),
        ScreeningSpec(
            schema_version=1,
            name="均线趋势",
            origin="BUILTIN_TEMPLATE",
            universe_spec=UniverseSpec(),
            as_of_date=today,
            timeframe=MarketTimeframe.DAY_1,
            conditions=(
                ScreeningCondition(
                    condition_key="SMA_RELATION",
                    parameters={"short_window": 5, "long_window": 20, "relation": "ABOVE"},
                ),
            ),
            ranking_rules=(RankingRule(field="score", direction=RankingDirection.DESC),),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
        ),
    )


@dataclass(frozen=True, slots=True)
class ScreeningTemplateDefinition:
    template_key: str
    display_name: str
    description: str
    spec: ScreeningSpec
    timeframe: str = "日线"
    required_data: str = "MiniQMT历史日线"
    enabled: bool = True


def screening_template_catalog() -> tuple[ScreeningTemplateDefinition, ...]:
    specs = screening_templates()
    metadata = (
        ("limit_up_pullback", "最近涨停后回踩起涨锚点，同时成交量明显收缩"),
        ("bottom_volume_expansion", "位于历史区间底部、成交量放大且当日收阳"),
        ("volume_anomaly", "当前成交量显著高于此前平均成交量"),
        ("limit_up_retrace", "最近涨停后回落至起涨区域，用于宽松观察"),
        ("volume_breakout", "价格突破前期高点，同时成交量明显放大"),
        ("moving_average_trend", "短期均线位于长期均线上方"),
    )
    return tuple(
        ScreeningTemplateDefinition(
            template_key=key,
            display_name=spec.name,
            description=description,
            spec=spec,
        )
        for spec, (key, description) in zip(specs, metadata, strict=True)
    )
