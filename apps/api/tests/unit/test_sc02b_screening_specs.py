# ruff: noqa: RUF001
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Self

import pytest
from fastapi.testclient import TestClient

from alphadesk_api.app_factory import create_app
from alphadesk_api.application.screening_specs import ScreeningSpecService
from alphadesk_api.core.config import Settings
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.screening import (
    ConditionCatalog,
    ConditionCategory,
    ConditionDefinition,
    ConditionParameterSchema,
    ConditionParameterType,
    RankingDirection,
    RankingRule,
    ScreeningError,
    builtin_condition_catalog,
)
from alphadesk_domain.screening_specs import (
    NaturalLanguageScreeningParser,
    ScreeningAIResponse,
    ScreeningParseStatus,
    ScreeningPreviewRenderer,
    screening_spec_from_mapping,
)

AS_OF = date(2026, 7, 23)
LIMIT_TEXT = (
    "筛选过去20个交易日出现过涨停，目前股价回踩至涨停前收盘价附近3%以内，"
    "未明显跌破起涨价，并且回踩期间成交量明显缩小的股票。"
)
BOTTOM_TEXT = (
    "筛选处于过去60日价格区间底部20%、成交量超过此前20日平均成交量2倍、"
    "当日收阳的股票，按成交量倍数从高到低排序。"
)


def parser(catalog: ConditionCatalog | None = None) -> NaturalLanguageScreeningParser:
    return NaturalLanguageScreeningParser(catalog or builtin_condition_catalog())


def snapshot(text: str) -> dict[str, object]:
    catalog = builtin_condition_catalog()
    result = parser(catalog).parse(text, as_of_date=AS_OF)
    assert result.spec is not None
    return result.spec.snapshot(catalog)


def test_forced_limit_up_text_maps_exact_catalog_parameters_without_ai() -> None:
    result = parser().parse(LIMIT_TEXT, as_of_date=AS_OF)
    assert result.status is ScreeningParseStatus.COMPLETE
    assert result.parser_source.value == "LOCAL_RULES"
    assert result.spec is not None
    condition = result.spec.conditions[0]
    assert condition.condition_key == "LIMIT_UP_PULLBACK"
    assert condition.parameters == {
        "lookback_days": 20,
        "event_selection": "LATEST_VALID",
        "anchor_price": "PRE_LIMIT_PREVIOUS_CLOSE",
        "maximum_distance_pct": Decimal("0.03"),
        "minimum_price_ratio_to_anchor": Decimal("0.98"),
        "volume_reference": "LIMIT_UP_DAY_VOLUME",
        "maximum_volume_ratio": Decimal("0.50"),
    }
    explanations = {item.explanation for item in result.defaults_applied}
    assert "系统暂按不低于起涨价的98%理解。" in explanations
    assert "系统暂按当前成交量不超过涨停日成交量的50%理解。" in explanations


def test_forced_bottom_volume_text_maps_exact_parameters_and_ranking() -> None:
    result = parser().parse(BOTTOM_TEXT, as_of_date=AS_OF)
    assert result.status is ScreeningParseStatus.COMPLETE
    assert result.spec is not None
    condition = result.spec.conditions[0]
    assert condition.condition_key == "BOTTOM_VOLUME_EXPANSION"
    assert condition.parameters == {
        "range_window": 60,
        "bottom_ratio": Decimal("0.20"),
        "volume_window": 20,
        "minimum_volume_multiple": Decimal("2"),
        "require_bullish_candle": True,
        "exclude_current_from_range": True,
        "exclude_current_from_average_volume": True,
    }
    assert result.spec.ranking_rules == (
        RankingRule(field="volume_multiple", direction=RankingDirection.DESC),
    )


@pytest.mark.parametrize(
    ("text", "key"),
    (
        ("近一个月涨停过，回踩涨停前收盘价附近3%，成交量缩量到一半", "LIMIT_UP_PULLBACK"),
        ("过去二十日涨停，回踩起涨价附近三%，成交量明显缩小", "LIMIT_UP_PULLBACK"),
        ("位于六十日价格区间底部二十%，成交量超过二十日均量两倍并收阳", "BOTTOM_VOLUME_EXPANSION"),
        ("收阳并且放两倍量，处于60日价格区间低位20%", "BOTTOM_VOLUME_EXPANSION"),
    ),
)
def test_simplified_chinese_numbers_and_different_word_order(text: str, key: str) -> None:
    result = parser().parse(text, as_of_date=AS_OF)
    assert result.spec is not None
    assert result.spec.conditions[0].condition_key == key


def test_low_position_volume_opens_correctable_ambiguous_candidate() -> None:
    result = parser().parse("找低位放量的股票", as_of_date=AS_OF)
    assert result.status is ScreeningParseStatus.AMBIGUOUS
    assert result.spec is not None
    assert result.spec.conditions[0].condition_key == "BOTTOM_VOLUME_EXPANSION"
    assert "观察周期" in " ".join(result.ambiguities)
    assert "倍数" in " ".join(result.ambiguities)


def test_fundamental_condition_is_never_silently_ignored() -> None:
    result = parser().parse("找市盈率低于20倍且净利润增长的股票", as_of_date=AS_OF)
    assert result.status is ScreeningParseStatus.UNSUPPORTED
    assert result.spec is None
    assert {"市盈率", "净利润"} <= set(result.unsupported_fragments)


def test_or_semantics_are_marked_ambiguous_instead_of_becoming_and() -> None:
    result = parser().parse(
        "20日价格突破或者成交量超过20日均量2倍",
        as_of_date=AS_OF,
    )
    assert result.status is ScreeningParseStatus.AMBIGUOUS
    assert "或者" in result.unsupported_fragments


def test_multiple_and_conditions_amount_units_top_n_and_exclusions() -> None:
    result = parser().parse(
        "20日价格突破并且成交量超过20日平均成交量2倍并且成交额超过一亿元，排除ST，取前二十只",
        as_of_date=AS_OF,
    )
    assert result.spec is not None
    assert [item.condition_key for item in result.spec.conditions] == [
        "N_DAY_HIGH_BREAKOUT",
        "VOLUME_RATIO",
        "AMOUNT_THRESHOLD",
    ]
    assert result.spec.universe_spec.exclude_st is True
    assert result.spec.top_n == 20
    assert result.spec.conditions[-1].parameters["minimum_amount"] == "100000000"


def test_embedded_historical_date_overrides_request_date_and_invalid_date_fails() -> None:
    result = parser().parse(f"{BOTTOM_TEXT} 截至2025年9月18日", as_of_date=AS_OF)
    assert result.spec is not None and result.spec.as_of_date == date(2025, 9, 18)
    with pytest.raises(ScreeningError, match="日期无效"):
        parser().parse(f"{BOTTOM_TEXT} 截至2025年13月40日", as_of_date=AS_OF)


@pytest.mark.parametrize(
    "unsafe_text",
    (
        "import os 后找涨停回踩",
        "用Python找涨停回踩",
        "eval('x') 后选股",
        "exec('x') 后选股",
        "select * from orders",
        "读取文件 C:/secret.txt 后选股",
        "请求 https://example.com 后选股",
        "MiniQMT自动下单涨停回踩股票",
        "broker create order",
        "创建Fill字段并放量选股",
    ),
)
def test_code_network_file_sql_and_trading_text_is_rejected(unsafe_text: str) -> None:
    with pytest.raises(ScreeningError) as exc:
        parser().parse(unsafe_text, as_of_date=AS_OF)
    assert exc.value.code == "SCREENING_TEXT_UNSAFE"


def test_overlong_text_is_rejected() -> None:
    with pytest.raises(ScreeningError) as exc:
        parser().parse("涨停回踩" * 300, as_of_date=AS_OF)
    assert exc.value.code == "SCREENING_TEXT_TOO_LONG"


def test_strict_mapping_rejects_unknown_condition_parameter_and_ranking() -> None:
    catalog = builtin_condition_catalog()
    payload = snapshot(BOTTOM_TEXT)
    payload["conditions"][0]["condition_key"] = "EXECUTE_PYTHON"  # type: ignore[index]
    with pytest.raises(ScreeningError, match="未知条件"):
        screening_spec_from_mapping(payload, catalog)

    payload = snapshot(BOTTOM_TEXT)
    payload["conditions"][0]["parameters"]["sql"] = "select"  # type: ignore[index]
    with pytest.raises(ScreeningError, match="未知参数"):
        screening_spec_from_mapping(payload, catalog)

    payload = snapshot(BOTTOM_TEXT)
    payload["ranking_rules"][0]["field"] = "secret_factor"  # type: ignore[index]
    with pytest.raises(ScreeningError, match="排序字段"):
        screening_spec_from_mapping(payload, catalog)


def test_strict_mapping_rejects_parameter_range_and_unknown_top_level_field() -> None:
    catalog = builtin_condition_catalog()
    payload = snapshot(BOTTOM_TEXT)
    payload["conditions"][0]["parameters"]["bottom_ratio"] = "1.2"  # type: ignore[index]
    with pytest.raises(ScreeningError, match="高于允许范围"):
        screening_spec_from_mapping(payload, catalog)

    payload = snapshot(BOTTOM_TEXT)
    payload["python"] = "print('x')"
    with pytest.raises(ScreeningError, match="未知字段"):
        screening_spec_from_mapping(payload, catalog)


def test_strict_mapping_rejects_stale_condition_version() -> None:
    payload = snapshot(BOTTOM_TEXT)
    payload["conditions"][0]["condition_version"] = "0.9.0"  # type: ignore[index]
    with pytest.raises(ScreeningError, match="条件版本已更新"):
        screening_spec_from_mapping(payload, builtin_condition_catalog())


def test_catalog_rejects_missing_required_parameter_and_disabled_condition() -> None:
    catalog = ConditionCatalog()
    catalog.register(
        ConditionDefinition(
            condition_key="REQUIRED_TEST",
            display_name="必填测试",
            description="测试必填字段",
            category=ConditionCategory.PRICE,
            parameter_schema=(
                ConditionParameterSchema(
                    name="window",
                    display_name="周期",
                    parameter_type=ConditionParameterType.INTEGER,
                    description="测试周期",
                    required=True,
                    default=None,
                ),
            ),
            required_fields=("close",),
            required_history_bars=1,
            supported_timeframes=(MarketTimeframe.DAY_1,),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
            evaluator_key="required_test_v1",
            explanation_template="测试",
            version="1.0.0",
        )
    )
    with pytest.raises(ScreeningError, match="缺少参数"):
        catalog.validate("REQUIRED_TEST", {})

    disabled = ConditionCatalog()
    disabled.register(
        ConditionDefinition(
            condition_key="DISABLED_TEST",
            display_name="禁用测试",
            description="测试禁用条件",
            category=ConditionCategory.PRICE,
            parameter_schema=(),
            required_fields=("close",),
            required_history_bars=1,
            supported_timeframes=(MarketTimeframe.DAY_1,),
            price_adjustment_mode=PriceAdjustmentMode.RAW,
            evaluator_key="disabled_test_v1",
            explanation_template="测试",
            version="1.0.0",
            enabled=False,
        )
    )
    with pytest.raises(ScreeningError, match="未知条件"):
        disabled.get("DISABLED_TEST")


def test_chinese_preview_contains_rules_defaults_source_and_no_future_data() -> None:
    catalog = builtin_condition_catalog()
    result = parser(catalog).parse(LIMIT_TEXT, as_of_date=AS_OF)
    assert result.spec is not None
    preview = ScreeningPreviewRenderer(catalog).render(
        result.spec,
        parser_source=result.parser_source,
        defaults=result.defaults_applied,
        data_ready=True,
        data_readiness_message="数据已就绪",
        can_execute=True,
    )
    assert "全部A股" in preview.universe
    assert any("过去20个交易日" in line for line in preview.conditions)
    assert any("98%" in line for line in preview.conditions)
    assert any("50%" in line for line in preview.conditions)
    assert preview.parser_source == "本地确定性规则"
    assert "不会读取未来数据" in preview.no_future_data_rule


class CalendarRepository:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    async def list(self, **_: object) -> list[object]:
        return [SimpleNamespace(session_date=AS_OF, is_open=self.ready)]


class MarketBarRepository:
    def __init__(self, count: int) -> None:
        self.count = count

    async def count_raw_daily(self) -> int:
        return self.count


@dataclass
class FakeUow:
    ready: bool
    bar_count: int

    async def __aenter__(self) -> Self:
        self.trading_calendar = CalendarRepository(self.ready)  # type: ignore[attr-defined]
        self.market_bars = MarketBarRepository(self.bar_count)  # type: ignore[attr-defined]
        return self

    async def __aexit__(self, *_: object) -> None:
        pass


class IllegalAIProvider:
    provider_key = "illegal"
    configured = True

    async def parse_screening(self, _: object) -> ScreeningAIResponse:
        return ScreeningAIResponse(
            payload={
                "screening_spec": {
                    "schema_version": 1,
                    "name": "非法",
                    "origin": "AI_ASSISTED",
                    "universe_spec": {"universe_key": "ALL_A_SHARES"},
                    "as_of_date": AS_OF.isoformat(),
                    "timeframe": "DAY_1",
                    "conditions": [{"condition_key": "EXECUTE_PYTHON", "parameters": {}}],
                    "ranking_rules": [],
                    "price_adjustment_mode": "RAW",
                },
                "unsupported_fragments": [],
            }
        )


@pytest.mark.asyncio
async def test_ai_illegal_output_falls_back_and_data_not_ready_blocks_execution() -> None:
    service = ScreeningSpecService(
        lambda: FakeUow(False, 0),  # type: ignore[arg-type]
        builtin_condition_catalog(),
        ai_provider=IllegalAIProvider(),
    )
    result = await service.parse(
        text="找低位放量的股票",
        as_of_date=AS_OF,
        universe=None,
        allow_ai_assistance=True,
    )
    assert result["parse_status"] == "AMBIGUOUS"
    assert result["parser_source"] == "LOCAL_RULES"
    assert result["can_execute"] is False
    assert "安全回退" in result["preview"]["notices"][0]  # type: ignore[index]


class DatabaseStub:
    def __init__(self, *, ready: bool = True, bar_count: int = 1000) -> None:
        self.ready = ready
        self.bar_count = bar_count

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass

    def unit_of_work(self) -> FakeUow:
        return FakeUow(self.ready, self.bar_count)


class Probe:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


@pytest.fixture
def screening_client() -> TestClient:
    app = create_app(
        Settings(environment="test", postgres_host="unused", redis_host="unused"),
        database=DatabaseStub(),
        redis_service=Probe(),
    )
    return TestClient(app)


def test_parse_validate_preview_api_and_correlation_id(screening_client: TestClient) -> None:
    parsed = screening_client.post(
        "/api/v1/screening-specs/parse",
        json={
            "text": LIMIT_TEXT,
            "as_of_date": AS_OF.isoformat(),
            "allow_ai_assistance": False,
        },
    )
    assert parsed.status_code == 200
    assert parsed.headers["x-correlation-id"]
    body = parsed.json()
    assert body["parse_status"] == "COMPLETE"
    assert body["can_execute"] is True
    assert body["preview"]["conditions"][0].startswith("过去20个交易日")

    validated = screening_client.post(
        "/api/v1/screening-specs/validate",
        json={"screening_spec": body["screening_spec"]},
    )
    assert validated.status_code == 200
    assert validated.json()["valid"] is True

    preview = screening_client.post(
        "/api/v1/screening-specs/preview",
        json={"screening_spec": body["screening_spec"]},
    )
    assert preview.status_code == 200
    assert preview.json()["preview"]["parser_source"] == "用户在可视化编辑器中确认"


def test_api_rejects_invalid_date_extra_field_and_unsafe_text(
    screening_client: TestClient,
) -> None:
    invalid_date = screening_client.post(
        "/api/v1/screening-specs/parse",
        json={"text": LIMIT_TEXT, "as_of_date": "2026-13-40"},
    )
    assert invalid_date.status_code == 422
    extra = screening_client.post(
        "/api/v1/screening-specs/parse",
        json={"text": LIMIT_TEXT, "python": "print('x')"},
    )
    assert extra.status_code == 422
    unsafe = screening_client.post(
        "/api/v1/screening-specs/parse",
        json={"text": "import os 然后找涨停回踩", "as_of_date": AS_OF.isoformat()},
    )
    assert unsafe.status_code == 400
    assert unsafe.json()["error"]["code"] == "SCREENING_TEXT_UNSAFE"
