# ruff: noqa: RUF001
"""SC02-B safe natural-language contracts for catalog-backed screening.

The parser only produces allow-listed :class:`ScreeningSpec` values.  It does
not evaluate source code, issue SQL, access files or networks, or call any
trading capability.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.screening import (
    ConditionCatalog,
    RankingDirection,
    RankingRule,
    ScreeningCondition,
    ScreeningError,
    ScreeningSpec,
    UniverseSpec,
)


class ScreeningParseStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"


class ScreeningParserSource(StrEnum):
    LOCAL_RULES = "LOCAL_RULES"
    AI_ASSISTED = "AI_ASSISTED"


@dataclass(frozen=True, slots=True, kw_only=True)
class AppliedScreeningDefault:
    condition_key: str
    parameter_name: str
    display_name: str
    value: str | int | bool | None
    explanation: str

    def response_dict(self) -> dict[str, object]:
        return {
            "condition_key": self.condition_key,
            "parameter_name": self.parameter_name,
            "display_name": self.display_name,
            "value": self.value,
            "explanation": self.explanation,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RecognizedScreeningCondition:
    condition_key: str
    display_name: str
    matched_expression: str

    def response_dict(self) -> dict[str, str]:
        return {
            "condition_key": self.condition_key,
            "display_name": self.display_name,
            "matched_expression": self.matched_expression,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class LocalScreeningParseResult:
    status: ScreeningParseStatus
    parser_source: ScreeningParserSource
    spec: ScreeningSpec | None
    recognized_conditions: tuple[RecognizedScreeningCondition, ...] = ()
    ambiguities: tuple[str, ...] = ()
    unsupported_fragments: tuple[str, ...] = ()
    defaults_applied: tuple[AppliedScreeningDefault, ...] = ()
    normalized_text: str = ""
    potentially_catalog_matchable: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreeningAIRequest:
    text: str
    as_of_date: date
    catalog: tuple[Mapping[str, object], ...]
    local_status: ScreeningParseStatus
    local_ambiguities: tuple[str, ...] = ()
    local_unsupported_fragments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreeningAIResponse:
    payload: Mapping[str, object]


class ScreeningAIProvider(Protocol):
    provider_key: str
    configured: bool

    async def parse_screening(self, request: ScreeningAIRequest) -> ScreeningAIResponse: ...


_UNSAFE_PATTERNS = (
    r"python",
    r"\bimport\s+",
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bsubprocess\b",
    r"\bos\s*\.",
    r"\bpathlib\b",
    r"\bopen\s*\(",
    r"https?://",
    r"\brequests?\b",
    r"\bsocket\b",
    r"\bselect\s+.+\bfrom\b",
    r"\b(insert|update|delete|drop|alter)\s+",
    r"读取文件",
    r"写入文件",
    r"删除文件",
    r"访问文件",
    r"发送请求",
    r"调用接口",
    r"miniqmt.{0,12}(下单|委托|撤单|交易)",
    r"(下单|撤单|自动交易|实盘交易|创建订单)",
    r"(order|fill|broker)",
)

_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
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
}
_NUMBER_TOKEN = r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百]+)"


def _chinese_integer(token: str) -> int:
    if token in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[token]
    total = 0
    current = 0
    for char in token:
        if char in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[char]
        elif char == "十":
            total += (current or 1) * 10
            current = 0
        elif char == "百":
            total += (current or 1) * 100
            current = 0
        else:
            raise ValueError("unsupported Chinese number")
    return total + current


def _number(token: str) -> Decimal:
    try:
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            return Decimal(token)
        return Decimal(_chinese_integer(token))
    except (InvalidOperation, ValueError) as exc:
        raise ScreeningError("SCREENING_TEXT_NUMBER_INVALID", f"无法识别数字：{token}") from exc


def _integer(token: str, label: str) -> int:
    value = _number(token)
    if value != value.to_integral_value():
        raise ScreeningError("SCREENING_TEXT_NUMBER_INVALID", f"{label}必须是整数")
    return int(value)


def _stored(value: object) -> str | int | bool | None:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if value is None or isinstance(value, str | int | bool):
        return value
    return str(value)


def _normalized(text: str) -> str:
    return " ".join(
        text.strip()
        .replace("％", "%")
        .replace("，", "，")
        .replace("；", "；")
        .replace("\u3000", " ")
        .split()
    )


def _first_number(pattern: str, text: str) -> Decimal | None:
    match = re.search(pattern, text, re.IGNORECASE)
    return None if match is None else _number(match.group("number"))


class NaturalLanguageScreeningParser:
    """Deterministically map common Chinese descriptions to the SC02-A catalog."""

    MAX_TEXT_LENGTH = 1000

    def __init__(self, catalog: ConditionCatalog) -> None:
        self._catalog = catalog

    def parse(
        self,
        text: str,
        *,
        as_of_date: date,
        universe: UniverseSpec | None = None,
    ) -> LocalScreeningParseResult:
        normalized = _normalized(text)
        if not normalized:
            raise ScreeningError("SCREENING_TEXT_EMPTY", "请输入选股描述")
        if len(normalized) > self.MAX_TEXT_LENGTH:
            raise ScreeningError(
                "SCREENING_TEXT_TOO_LONG",
                f"选股描述最多{self.MAX_TEXT_LENGTH}个字符",
            )
        lowered = normalized.casefold()
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in _UNSAFE_PATTERNS):
            raise ScreeningError(
                "SCREENING_TEXT_UNSAFE",
                "选股描述包含脚本、网络、文件、SQL或交易指令；这里只允许描述研究条件",
            )

        resolved_universe = self._universe(normalized, universe)
        resolved_date = self._embedded_date(normalized) or as_of_date
        conditions: list[ScreeningCondition] = []
        recognized: list[RecognizedScreeningCondition] = []
        ambiguities: list[str] = []
        unsupported: list[str] = []
        defaults: list[AppliedScreeningDefault] = []
        rankings: list[RankingRule] = []

        has_limit = "涨停" in normalized and any(
            token in normalized for token in ("回踩", "起涨", "涨停前", "缩量")
        )
        has_bottom = any(token in normalized for token in ("底部", "低位")) and any(
            token in normalized for token in ("放量", "倍量", "均量", "成交量")
        )

        if has_limit:
            condition, condition_defaults, condition_ambiguities = self._limit_up(normalized)
            conditions.append(condition)
            defaults.extend(condition_defaults)
            ambiguities.extend(condition_ambiguities)
            definition = self._catalog.get(condition.condition_key)
            recognized.append(
                RecognizedScreeningCondition(
                    condition_key=definition.condition_key,
                    display_name=definition.display_name,
                    matched_expression="涨停回踩与缩量",
                )
            )

        if has_bottom:
            condition, condition_defaults, condition_ambiguities = self._bottom_volume(normalized)
            conditions.append(condition)
            defaults.extend(condition_defaults)
            ambiguities.extend(condition_ambiguities)
            definition = self._catalog.get(condition.condition_key)
            recognized.append(
                RecognizedScreeningCondition(
                    condition_key=definition.condition_key,
                    display_name=definition.display_name,
                    matched_expression="区间低位与成交量放大",
                )
            )
            if any(token in normalized for token in ("从高到低", "降序", "由高到低")):
                rankings.append(
                    RankingRule(field="volume_multiple", direction=RankingDirection.DESC)
                )
            elif any(token in normalized for token in ("从低到高", "升序", "由低到高")):
                rankings.append(
                    RankingRule(field="volume_multiple", direction=RankingDirection.ASC)
                )

        if not has_limit and not has_bottom:
            generic = self._generic_conditions(normalized)
            conditions.extend(generic)
            for condition in generic:
                definition = self._catalog.get(condition.condition_key)
                recognized.append(
                    RecognizedScreeningCondition(
                        condition_key=definition.condition_key,
                        display_name=definition.display_name,
                        matched_expression=definition.description,
                    )
                )

        if "或者" in normalized or re.search(r"(^|[\s，；、])或([\s，；、]|$)", normalized):
            ambiguities.append(
                "当前规则引擎只能安全组合“并且”条件，不能静默解释“或者”；请改为并且或拆分运行。"
            )
            unsupported.append("或者")

        fundamental_tokens = (
            "市盈率",
            "市净率",
            "净利润",
            "营收",
            "毛利率",
            "资产负债率",
            "ROE",
            "roe",
            "行业",
            "概念",
        )
        for token in fundamental_tokens:
            if token in normalized and token not in unsupported:
                unsupported.append(token)

        if not conditions:
            message = (
                "当前系统尚未准备该字段，不能执行这部分条件。"
                if unsupported
                else "系统未能把描述安全匹配到现有标准条件目录。"
            )
            return LocalScreeningParseResult(
                status=ScreeningParseStatus.UNSUPPORTED,
                parser_source=ScreeningParserSource.LOCAL_RULES,
                spec=None,
                recognized_conditions=(),
                ambiguities=(),
                unsupported_fragments=tuple(unsupported or (message,)),
                defaults_applied=(),
                normalized_text=normalized,
                potentially_catalog_matchable=any(
                    token in normalized
                    for token in ("突破", "均线", "成交量", "涨跌幅", "区间", "收阳", "涨停")
                ),
            )

        top_n_value = _first_number(
            rf"(?:前|取前|保留前)\s*(?P<number>{_NUMBER_TOKEN})\s*只",
            normalized,
        )
        top_n = None if top_n_value is None else int(top_n_value)
        if not rankings:
            rankings.append(RankingRule(field="score", direction=RankingDirection.DESC))
        if unsupported:
            ambiguities.append("描述中含有当前目录不能执行的条件，系统没有静默忽略。")

        status = (
            ScreeningParseStatus.AMBIGUOUS
            if ambiguities or unsupported
            else ScreeningParseStatus.COMPLETE
        )
        spec = ScreeningSpec(
            schema_version=1,
            name=self._name(recognized),
            origin="NATURAL_LANGUAGE",
            universe_spec=resolved_universe,
            as_of_date=resolved_date,
            timeframe=MarketTimeframe.DAY_1,
            conditions=tuple(conditions),
            exclusions={},
            ranking_rules=tuple(rankings),
            top_n=top_n,
            price_adjustment_mode=PriceAdjustmentMode.RAW,
        )
        spec.validate(self._catalog)
        return LocalScreeningParseResult(
            status=status,
            parser_source=ScreeningParserSource.LOCAL_RULES,
            spec=spec,
            recognized_conditions=tuple(recognized),
            ambiguities=tuple(dict.fromkeys(ambiguities)),
            unsupported_fragments=tuple(dict.fromkeys(unsupported)),
            defaults_applied=tuple(defaults),
            normalized_text=normalized,
            potentially_catalog_matchable=True,
        )

    def _universe(self, text: str, supplied: UniverseSpec | None) -> UniverseSpec:
        base = supplied or UniverseSpec()
        return UniverseSpec(
            universe_key="ALL_A_SHARES",
            excluded_instrument_ids=base.excluded_instrument_ids,
            exclude_st=base.exclude_st or bool(re.search(r"排除\s*(?:\*?ST|st)", text)),
            exclude_bse=base.exclude_bse
            or any(token in text for token in ("排除北交所", "不含北交所")),
            exclude_star_market=base.exclude_star_market
            or any(token in text for token in ("排除科创板", "不含科创板")),
            exclude_chinext=base.exclude_chinext
            or any(token in text for token in ("排除创业板", "不含创业板")),
        )

    @staticmethod
    def _embedded_date(text: str) -> date | None:
        match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
        if match is None:
            return None
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError as exc:
            raise ScreeningError("SCREENING_DATE_INVALID", "选股描述中的日期无效") from exc

    @staticmethod
    def _name(recognized: Sequence[RecognizedScreeningCondition]) -> str:
        labels = " + ".join(item.display_name for item in recognized)
        return f"自然语言选股：{labels}"[:128]

    def _default(
        self,
        condition_key: str,
        parameter_name: str,
        value: object,
        explanation: str,
    ) -> AppliedScreeningDefault:
        schema = next(
            item
            for item in self._catalog.get(condition_key).parameter_schema
            if item.name == parameter_name
        )
        return AppliedScreeningDefault(
            condition_key=condition_key,
            parameter_name=parameter_name,
            display_name=schema.display_name,
            value=_stored(value),
            explanation=explanation,
        )

    def _limit_up(
        self, text: str
    ) -> tuple[
        ScreeningCondition,
        list[AppliedScreeningDefault],
        list[str],
    ]:
        key = "LIMIT_UP_PULLBACK"
        definition = self._catalog.get(key)
        parameters = definition.validate_parameters({})
        defaults: list[AppliedScreeningDefault] = []
        ambiguities: list[str] = []

        lookback = _first_number(
            rf"(?:过去|近)\s*(?P<number>{_NUMBER_TOKEN})\s*(?:个)?(?:交易)?日",
            text,
        )
        if lookback is not None:
            parameters["lookback_days"] = int(lookback)
        elif "近一个月" in text or "近一月" in text:
            parameters["lookback_days"] = 20
            defaults.append(self._default(key, "lookback_days", 20, "“近一个月”按20个交易日理解。"))
        else:
            ambiguities.append("系统无法确定涨停事件的回看周期，请确认回看交易日数。")

        distance = _first_number(
            rf"(?:附近|距离|偏离|相差)[^，。；%]{{0,12}}?"
            rf"(?P<number>{_NUMBER_TOKEN})\s*%",
            text,
        )
        if distance is None:
            distance = _first_number(
                rf"(?P<number>{_NUMBER_TOKEN})\s*%\s*(?:以内|之内|附近)",
                text,
            )
        if distance is not None:
            parameters["maximum_distance_pct"] = distance / Decimal("100")
        else:
            ambiguities.append("系统无法确定回踩到起涨价格附近的最大距离，请确认回踩距离。")

        explicit_minimum = _first_number(
            rf"(?:不低于|至少为|最低为)[^，。；%]{{0,12}}?"
            rf"(?P<number>{_NUMBER_TOKEN})\s*%",
            text,
        )
        if explicit_minimum is not None:
            parameters["minimum_price_ratio_to_anchor"] = explicit_minimum / Decimal("100")
        else:
            defaults.append(
                self._default(
                    key,
                    "minimum_price_ratio_to_anchor",
                    parameters["minimum_price_ratio_to_anchor"],
                    "系统暂按不低于起涨价的98%理解。",
                )
            )

        explicit_volume = _first_number(
            rf"(?:低于|不超过|缩量到|缩小到)[^，。；%]{{0,16}}?"
            rf"(?P<number>{_NUMBER_TOKEN})\s*%",
            text,
        )
        if explicit_volume is not None:
            parameters["maximum_volume_ratio"] = explicit_volume / Decimal("100")
        elif "一半" in text:
            parameters["maximum_volume_ratio"] = Decimal("0.50")
        else:
            defaults.append(
                self._default(
                    key,
                    "maximum_volume_ratio",
                    parameters["maximum_volume_ratio"],
                    "系统暂按当前成交量不超过涨停日成交量的50%理解。",
                )
            )

        defaults.extend(
            (
                self._default(
                    key,
                    "event_selection",
                    parameters["event_selection"],
                    "多次涨停时选择距离筛选日期最近且数据完整的事件。",
                ),
                self._default(
                    key,
                    "anchor_price",
                    parameters["anchor_price"],
                    "起涨价格按涨停前一交易日收盘价计算。",
                ),
                self._default(
                    key,
                    "volume_reference",
                    parameters["volume_reference"],
                    "缩量比例以涨停日成交量为参照。",
                ),
            )
        )
        return (
            ScreeningCondition(condition_key=key, parameters=parameters),
            defaults,
            ambiguities,
        )

    def _bottom_volume(
        self, text: str
    ) -> tuple[
        ScreeningCondition,
        list[AppliedScreeningDefault],
        list[str],
    ]:
        key = "BOTTOM_VOLUME_EXPANSION"
        definition = self._catalog.get(key)
        parameters = definition.validate_parameters({})
        defaults: list[AppliedScreeningDefault] = []
        ambiguities: list[str] = []

        range_window = _first_number(
            rf"(?:过去|此前|近|位于|处于)?\s*(?P<number>{_NUMBER_TOKEN})\s*日"
            rf"(?:价格)?区间",
            text,
        )
        bottom_ratio = _first_number(
            rf"(?:底部|低位)[^，。；%]{{0,8}}?(?P<number>{_NUMBER_TOKEN})\s*%",
            text,
        )
        if bottom_ratio is None:
            bottom_ratio = _first_number(
                rf"区间(?:的)?(?:底部|低位)\s*(?P<number>{_NUMBER_TOKEN})\s*%",
                text,
            )
        volume_window = _first_number(
            rf"(?:此前|过去|近)?\s*(?P<number>{_NUMBER_TOKEN})\s*日"
            rf"(?:平均成交量|均量)",
            text,
        )
        multiple = _first_number(
            rf"(?:成交量[^，。；]{{0,24}}|放)\s*(?P<number>{_NUMBER_TOKEN})\s*倍",
            text,
        )

        if range_window is not None:
            parameters["range_window"] = int(range_window)
        else:
            ambiguities.append("系统无法确定“低位”的观察周期，请确认价格区间周期。")
        if bottom_ratio is not None:
            parameters["bottom_ratio"] = bottom_ratio / Decimal("100")
        elif any(token in text for token in ("区间低位", "价格低位", "底部", "低位")):
            defaults.append(
                self._default(
                    key,
                    "bottom_ratio",
                    parameters["bottom_ratio"],
                    "系统暂按价格位于区间底部20%理解。",
                )
            )
            if range_window is None:
                ambiguities.append("系统无法确定“低位”的范围，请确认底部范围。")
        if volume_window is not None:
            parameters["volume_window"] = int(volume_window)
        else:
            ambiguities.append("系统无法确定“放量”的均量周期，请确认平均成交量周期。")
        if multiple is not None:
            parameters["minimum_volume_multiple"] = multiple
        else:
            ambiguities.append("系统无法确定“放量”的倍数，请确认最低成交量倍数。")

        if "不要求收阳" in text or "无需收阳" in text:
            parameters["require_bullish_candle"] = False
        elif "收阳" not in text and "阳线" not in text:
            defaults.append(
                self._default(
                    key,
                    "require_bullish_candle",
                    True,
                    "标准底部放倍量形态默认要求筛选日收阳。",
                )
            )
        defaults.extend(
            (
                self._default(
                    key,
                    "exclude_current_from_range",
                    True,
                    "价格区间排除筛选日，避免把当前K线加入自身基准。",
                ),
                self._default(
                    key,
                    "exclude_current_from_average_volume",
                    True,
                    "平均成交量排除筛选日，避免未来函数和自我引用。",
                ),
            )
        )
        return (
            ScreeningCondition(condition_key=key, parameters=parameters),
            defaults,
            ambiguities,
        )

    def _generic_conditions(self, text: str) -> list[ScreeningCondition]:
        values: list[ScreeningCondition] = []
        high = re.search(
            rf"(?P<number>{_NUMBER_TOKEN})\s*日(?:价格|收盘价)?(?:新高|突破)",
            text,
        )
        low = re.search(rf"(?P<number>{_NUMBER_TOKEN})\s*日(?:价格|收盘价)?新低", text)
        volume = re.search(
            rf"成交量[^，。；]{{0,20}}?(?:此前|过去)?\s*"
            rf"(?P<window>{_NUMBER_TOKEN})\s*日(?:平均成交量|均量)"
            rf"[^，。；]{{0,12}}?(?P<multiple>{_NUMBER_TOKEN})\s*倍",
            text,
        )
        amount = re.search(
            rf"成交额[^，。；]{{0,12}}(?P<number>{_NUMBER_TOKEN})\s*(?P<unit>亿元|万元|元)",
            text,
        )
        if high is not None:
            values.append(
                ScreeningCondition(
                    condition_key="N_DAY_HIGH_BREAKOUT",
                    parameters={"window": _integer(high.group("number"), "突破周期")},
                )
            )
        if low is not None:
            values.append(
                ScreeningCondition(
                    condition_key="N_DAY_LOW",
                    parameters={"window": _integer(low.group("number"), "新低周期")},
                )
            )
        if volume is not None:
            values.append(
                ScreeningCondition(
                    condition_key="VOLUME_RATIO",
                    parameters={
                        "window": _integer(volume.group("window"), "均量周期"),
                        "minimum_ratio": _stored(_number(volume.group("multiple"))),
                    },
                )
            )
        if "收阳" in text or "阳线" in text:
            values.append(ScreeningCondition(condition_key="BULLISH_CANDLE"))
        if amount is not None:
            multiplier = {
                "亿元": Decimal("100000000"),
                "万元": Decimal("10000"),
                "元": Decimal("1"),
            }[amount.group("unit")]
            values.append(
                ScreeningCondition(
                    condition_key="AMOUNT_THRESHOLD",
                    parameters={
                        "minimum_amount": _stored(_number(amount.group("number")) * multiplier)
                    },
                )
            )
        for condition in values:
            self._catalog.validate(condition.condition_key, condition.parameters)
        return values


_SPEC_KEYS = {
    "schema_version",
    "name",
    "origin",
    "universe_spec",
    "as_of_date",
    "timeframe",
    "conditions",
    "exclusions",
    "ranking_rules",
    "top_n",
    "price_adjustment_mode",
}
_UNIVERSE_KEYS = {
    "universe_key",
    "excluded_instrument_ids",
    "exclude_st",
    "exclude_bse",
    "exclude_star_market",
    "exclude_chinext",
}
_CONDITION_KEYS = {"condition_key", "parameters", "condition_version"}
_RANK_KEYS = {"field", "direction"}


def _strict_mapping_keys(data: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ScreeningError("SCREENING_SPEC_UNKNOWN_FIELD", f"{label}包含未知字段：{unknown[0]}")


def screening_spec_from_mapping(
    payload: Mapping[str, object],
    catalog: ConditionCatalog,
    *,
    forced_origin: str | None = None,
) -> ScreeningSpec:
    """Build a strictly validated spec from client or AI structured output."""

    _strict_mapping_keys(payload, _SPEC_KEYS, "ScreeningSpec")
    try:
        universe_raw = payload.get("universe_spec", {})
        conditions_raw = payload["conditions"]
        rankings_raw = payload.get("ranking_rules", [])
        exclusions_raw = payload.get("exclusions", {})
        if not isinstance(universe_raw, Mapping):
            raise TypeError("universe_spec")
        if not isinstance(conditions_raw, list):
            raise TypeError("conditions")
        if not isinstance(rankings_raw, list):
            raise TypeError("ranking_rules")
        if not isinstance(exclusions_raw, Mapping):
            raise TypeError("exclusions")
        _strict_mapping_keys(universe_raw, _UNIVERSE_KEYS, "股票范围")
        excluded = universe_raw.get("excluded_instrument_ids", [])
        if not isinstance(excluded, list):
            raise TypeError("excluded_instrument_ids")
        universe = UniverseSpec(
            universe_key=str(universe_raw.get("universe_key", "ALL_A_SHARES")),
            excluded_instrument_ids=tuple(UUID(str(item)) for item in excluded),
            exclude_st=bool(universe_raw.get("exclude_st", False)),
            exclude_bse=bool(universe_raw.get("exclude_bse", False)),
            exclude_star_market=bool(universe_raw.get("exclude_star_market", False)),
            exclude_chinext=bool(universe_raw.get("exclude_chinext", False)),
        )
        conditions: list[ScreeningCondition] = []
        for raw in conditions_raw:
            if not isinstance(raw, Mapping):
                raise TypeError("condition")
            _strict_mapping_keys(raw, _CONDITION_KEYS, "筛选条件")
            definition = catalog.get(str(raw["condition_key"]))
            supplied_version = raw.get("condition_version")
            if supplied_version is not None and str(supplied_version) != definition.version:
                raise ScreeningError(
                    "SCREENING_CONDITION_VERSION_MISMATCH",
                    f"{definition.display_name}的条件版本已更新，请重新解析或确认条件",
                )
            parameters = raw.get("parameters", {})
            if not isinstance(parameters, Mapping):
                raise TypeError("parameters")
            conditions.append(
                ScreeningCondition(
                    condition_key=str(raw["condition_key"]),
                    parameters=dict(parameters),
                )
            )
        rankings: list[RankingRule] = []
        for raw in rankings_raw:
            if not isinstance(raw, Mapping):
                raise TypeError("ranking")
            _strict_mapping_keys(raw, _RANK_KEYS, "排序规则")
            rankings.append(
                RankingRule(
                    field=str(raw["field"]),
                    direction=RankingDirection(str(raw.get("direction", "DESC"))),
                )
            )
        spec = ScreeningSpec(
            schema_version=int(str(payload.get("schema_version", 1))),
            name=str(payload.get("name", "自然语言选股")),
            origin=forced_origin or str(payload.get("origin", "USER_STRUCTURED")),
            universe_spec=universe,
            as_of_date=date.fromisoformat(str(payload["as_of_date"])),
            timeframe=MarketTimeframe(str(payload.get("timeframe", "DAY_1"))),
            conditions=tuple(conditions),
            exclusions=dict(exclusions_raw),
            ranking_rules=tuple(rankings),
            top_n=(None if payload.get("top_n") is None else int(str(payload["top_n"]))),
            price_adjustment_mode=PriceAdjustmentMode(
                str(payload.get("price_adjustment_mode", "RAW"))
            ),
        )
        spec.validate(catalog)
        return spec
    except ScreeningError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ScreeningError("SCREENING_SPEC_INVALID", "ScreeningSpec结构或取值无效") from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class ScreeningPreview:
    summary: str
    universe: str
    conditions: tuple[str, ...]
    screening_time: str
    ranking: tuple[str, ...]
    defaults: tuple[str, ...]
    data_requirements: tuple[str, ...]
    parser_source: str
    no_future_data_rule: str
    data_ready: bool
    data_readiness_message: str
    can_execute: bool
    notices: tuple[str, ...] = field(default_factory=tuple)

    def response_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "universe": self.universe,
            "conditions": list(self.conditions),
            "screening_time": self.screening_time,
            "ranking": list(self.ranking),
            "defaults": list(self.defaults),
            "data_requirements": list(self.data_requirements),
            "parser_source": self.parser_source,
            "no_future_data_rule": self.no_future_data_rule,
            "data_ready": self.data_ready,
            "data_readiness_message": self.data_readiness_message,
            "can_execute": self.can_execute,
            "notices": list(self.notices),
        }


class ScreeningPreviewRenderer:
    def __init__(self, catalog: ConditionCatalog) -> None:
        self._catalog = catalog

    def render(
        self,
        spec: ScreeningSpec,
        *,
        parser_source: ScreeningParserSource | str,
        defaults: Sequence[AppliedScreeningDefault] = (),
        data_ready: bool,
        data_readiness_message: str,
        can_execute: bool,
        notices: Sequence[str] = (),
    ) -> ScreeningPreview:
        validated = spec.validate(self._catalog)
        condition_lines: list[str] = []
        requirements: list[str] = []
        for item in validated.conditions:
            condition_lines.extend(
                self._condition_preview(
                    item.definition.condition_key,
                    item.parameters,
                )
            )
            fields = "、".join(
                self._field_label(value) for value in item.definition.required_fields
            )
            requirements.append(
                f"{item.definition.display_name}：至少"
                f"{item.definition.history_bars(item.parameters)}根日K线；需要{fields}。"
            )
        ranking_lines = [self._ranking_preview(item) for item in spec.ranking_rules]
        if spec.top_n is not None:
            ranking_lines.append(f"仅保留排序后的前{spec.top_n}只股票。")
        source_value = (
            parser_source.value
            if isinstance(parser_source, ScreeningParserSource)
            else str(parser_source)
        )
        source_text = {
            "LOCAL_RULES": "本地确定性规则",
            "AI_ASSISTED": "AI辅助解析（已重新校验）",
            "USER_CORRECTED": "用户在可视化编辑器中确认",
        }.get(source_value, source_value)
        return ScreeningPreview(
            summary=f"{spec.name}，共{len(validated.conditions)}项标准条件。",
            universe=self._universe_preview(spec.universe_spec),
            conditions=tuple(condition_lines),
            screening_time=f"{spec.as_of_date.isoformat()}收盘后（已完成交易日）。",
            ranking=tuple(ranking_lines or ("按标准条件得分从高到低排序。",)),
            defaults=tuple(item.explanation for item in defaults),
            data_requirements=tuple(requirements),
            parser_source=source_text,
            no_future_data_rule=(
                "只读取筛选日期及以前的本地历史日线，所有滚动基准均排除当前K线，不会读取未来数据。"
            ),
            data_ready=data_ready,
            data_readiness_message=data_readiness_message,
            can_execute=can_execute,
            notices=tuple(notices),
        )

    @staticmethod
    def _percent(value: object) -> str:
        percentage = (Decimal(str(value)) * Decimal("100")).normalize()
        return f"{format(percentage, 'f')}%"

    @staticmethod
    def _number_text(value: object) -> str:
        number = Decimal(str(value))
        return format(number.normalize(), "f")

    def _condition_preview(self, condition_key: str, parameters: Mapping[str, object]) -> list[str]:
        if condition_key == "LIMIT_UP_PULLBACK":
            return [
                f"过去{parameters['lookback_days']}个交易日内出现过涨停。",
                "多次涨停时，选择距离筛选日期最近且数据完整的涨停事件。",
                "起涨价格按涨停前一交易日收盘价计算。",
                f"当前收盘价距离起涨价格不超过"
                f"{self._percent(parameters['maximum_distance_pct'])}。",
                f"当前收盘价不低于起涨价格的"
                f"{self._percent(parameters['minimum_price_ratio_to_anchor'])}。",
                f"当前成交量不超过涨停日成交量的"
                f"{self._percent(parameters['maximum_volume_ratio'])}。",
            ]
        if condition_key == "BOTTOM_VOLUME_EXPANSION":
            lines = [
                f"当前价格位于此前{parameters['range_window']}日价格区间底部"
                f"{self._percent(parameters['bottom_ratio'])}。",
                f"当前成交量至少为此前{parameters['volume_window']}日平均成交量的"
                f"{self._number_text(parameters['minimum_volume_multiple'])}倍。",
            ]
            if bool(parameters["require_bullish_candle"]):
                lines.append("筛选日收盘价高于开盘价（当日收阳）。")
            return lines
        definition = self._catalog.get(condition_key)
        labels = {key: _stored(value) for key, value in parameters.items()}
        try:
            return [definition.explanation_template.format(**labels) + "。"]
        except KeyError:
            return [definition.description + "。"]

    @staticmethod
    def _ranking_preview(rule: RankingRule) -> str:
        labels = {
            "score": "标准条件得分",
            "volume_multiple": "成交量倍数",
            "range_position": "区间位置",
            "distance_to_anchor": "距起涨价格的距离",
            "current_close": "当前收盘价",
        }
        direction = "从高到低" if rule.direction is RankingDirection.DESC else "从低到高"
        return f"按{labels.get(rule.field, rule.field)}{direction}排序。"

    @staticmethod
    def _universe_preview(universe: UniverseSpec) -> str:
        exclusions: list[str] = []
        if universe.exclude_st:
            exclusions.append("ST及*ST")
        if universe.exclude_bse:
            exclusions.append("北交所")
        if universe.exclude_star_market:
            exclusions.append("科创板")
        if universe.exclude_chinext:
            exclusions.append("创业板")
        base = "筛选日期当时存在的全部A股（沪、深、北）"
        return base + (f"，排除{'、'.join(exclusions)}。" if exclusions else "。")

    @staticmethod
    def _field_label(value: str) -> str:
        return {
            "open": "开盘价",
            "high": "最高价",
            "low": "最低价",
            "close": "收盘价",
            "volume": "成交量",
            "amount": "成交额",
            "price_limit": "涨跌停价格",
            "trading_status": "交易状态",
        }.get(value, value)
