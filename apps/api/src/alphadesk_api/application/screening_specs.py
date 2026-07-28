# ruff: noqa: RUF001
"""SC02-B orchestration for safe natural-language screening specifications."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_domain.ai_research import AIResearchError
from alphadesk_domain.screening import ConditionCatalog, ScreeningError, ScreeningSpec, UniverseSpec
from alphadesk_domain.screening_specs import (
    AppliedScreeningDefault,
    LocalScreeningParseResult,
    NaturalLanguageScreeningParser,
    RecognizedScreeningCondition,
    ScreeningAIProvider,
    ScreeningAIRequest,
    ScreeningParserSource,
    ScreeningParseStatus,
    ScreeningPreviewRenderer,
    screening_spec_from_mapping,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


class ScreeningSpecService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        catalog: ConditionCatalog,
        *,
        ai_provider: object | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog
        self._parser = NaturalLanguageScreeningParser(catalog)
        self._renderer = ScreeningPreviewRenderer(catalog)
        self._ai_provider = ai_provider

    async def parse(
        self,
        *,
        text: str,
        as_of_date: date | None,
        universe: UniverseSpec | None,
        allow_ai_assistance: bool,
    ) -> dict[str, object]:
        resolved_date = as_of_date or await self.latest_completed_session()
        local = self._parser.parse(text, as_of_date=resolved_date, universe=universe)
        result = local
        ai_notice: str | None = None
        if (
            allow_ai_assistance
            and local.status
            in {
                ScreeningParseStatus.PARTIAL,
                ScreeningParseStatus.AMBIGUOUS,
                ScreeningParseStatus.UNSUPPORTED,
            }
            and local.potentially_catalog_matchable
        ):
            result, ai_notice = await self._try_ai(local, text=text, as_of_date=resolved_date)
        readiness = await self.data_readiness(
            result.spec.as_of_date if result.spec is not None else resolved_date
        )
        can_execute = (
            result.status is ScreeningParseStatus.COMPLETE
            and result.spec is not None
            and readiness["ready"] is True
        )
        preview = (
            None
            if result.spec is None
            else self._renderer.render(
                result.spec,
                parser_source=result.parser_source,
                defaults=result.defaults_applied,
                data_ready=bool(readiness["ready"]),
                data_readiness_message=str(readiness["message"]),
                can_execute=can_execute,
                notices=tuple(value for value in (ai_notice,) if value),
            ).response_dict()
        )
        return self._result_dict(result, preview=preview, can_execute=can_execute)

    async def validate(self, payload: Mapping[str, object]) -> dict[str, object]:
        spec = screening_spec_from_mapping(
            payload,
            self._catalog,
            forced_origin="USER_CORRECTED",
        )
        readiness = await self.data_readiness(spec.as_of_date)
        can_execute = bool(readiness["ready"])
        recognized = self._recognized(spec)
        preview = self._renderer.render(
            spec,
            parser_source="USER_CORRECTED",
            data_ready=can_execute,
            data_readiness_message=str(readiness["message"]),
            can_execute=can_execute,
        )
        return {
            "valid": True,
            "parse_status": ScreeningParseStatus.COMPLETE.value,
            "screening_spec": spec.snapshot(self._catalog),
            "recognized_conditions": [item.response_dict() for item in recognized],
            "preview": preview.response_dict(),
            "can_execute": can_execute,
        }

    async def preview(self, payload: Mapping[str, object]) -> dict[str, object]:
        spec = screening_spec_from_mapping(
            payload,
            self._catalog,
            forced_origin="USER_CORRECTED",
        )
        readiness = await self.data_readiness(spec.as_of_date)
        can_execute = bool(readiness["ready"])
        preview = self._renderer.render(
            spec,
            parser_source="USER_CORRECTED",
            data_ready=can_execute,
            data_readiness_message=str(readiness["message"]),
            can_execute=can_execute,
        )
        return {
            "screening_spec": spec.snapshot(self._catalog),
            "preview": preview.response_dict(),
            "can_execute": can_execute,
        }

    async def latest_completed_session(self, now: datetime | None = None) -> date:
        local_now = (now or datetime.now(UTC)).astimezone(SHANGHAI)
        end = local_now.date()
        try:
            async with self._uow_factory() as uow:
                sessions = await uow.trading_calendar.list(
                    exchange="SHSE",
                    start=end - timedelta(days=370),
                    end=end,
                    limit=500,
                )
        except Exception as exc:
            raise ApplicationError(
                "MARKET_CALENDAR_NOT_AVAILABLE",
                "无法读取交易日历，请先在页面选择一个已完成交易日",
            ) from exc
        open_dates = [
            item.session_date
            for item in sessions
            if item.is_open and (item.session_date < end or local_now.time() >= time(15, 10))
        ]
        if not open_dates:
            raise ApplicationError(
                "MARKET_CALENDAR_NOT_AVAILABLE",
                "交易日历中没有可用的已完成交易日",
            )
        return max(open_dates)

    async def data_readiness(self, as_of_date: date) -> dict[str, object]:
        try:
            async with self._uow_factory() as uow:
                sessions = await uow.trading_calendar.list(
                    exchange="SHSE",
                    start=as_of_date,
                    end=as_of_date,
                    limit=1,
                )
                bar_count = await uow.market_bars.count_raw_daily()
            is_session = bool(sessions and sessions[0].is_open)
            if not is_session:
                return {
                    "ready": False,
                    "message": "筛选日期不是已登记的A股交易日，请更换日期。",
                    "bar_count": bar_count,
                }
            if bar_count <= 0:
                return {
                    "ready": False,
                    "message": "本地尚无MiniQMT历史日线，当前规则不能执行。",
                    "bar_count": 0,
                }
            return {
                "ready": True,
                "message": (
                    f"本地已有{bar_count:,}根正式历史日K线；执行时仍会逐只检查所需窗口，"
                    "数据不足会单独计数。"
                ),
                "bar_count": bar_count,
            }
        except Exception:
            return {
                "ready": False,
                "message": "暂时无法确认本地历史日线是否就绪，请检查PostgreSQL连接。",
                "bar_count": 0,
            }

    async def _try_ai(
        self,
        local: LocalScreeningParseResult,
        *,
        text: str,
        as_of_date: date,
    ) -> tuple[LocalScreeningParseResult, str | None]:
        candidate = self._ai_provider
        parse_method = getattr(candidate, "parse_screening", None)
        if (
            candidate is None
            or not bool(getattr(candidate, "configured", False))
            or not callable(parse_method)
        ):
            return local, "AI辅助解析未配置，已保留本地确定性解析结果。"
        provider = cast(ScreeningAIProvider, candidate)
        request = ScreeningAIRequest(
            text=text,
            as_of_date=as_of_date,
            catalog=tuple(item.response_dict() for item in self._catalog.list()),
            local_status=local.status,
            local_ambiguities=local.ambiguities,
            local_unsupported_fragments=local.unsupported_fragments,
        )
        try:
            response = await provider.parse_screening(request)
            return self._validated_ai_result(response.payload, local), None
        except (AIResearchError, ScreeningError, TypeError, ValueError, KeyError):
            return local, "AI辅助结果未通过目录与参数校验，已安全回退到本地解析结果。"

    def _validated_ai_result(
        self,
        payload: Mapping[str, object],
        local: LocalScreeningParseResult,
    ) -> LocalScreeningParseResult:
        allowed = {"screening_spec", "unsupported_fragments"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ScreeningError(
                "AI_SCREENING_OUTPUT_INVALID",
                f"AI选股输出包含未知字段：{unknown[0]}",
            )
        raw_spec = payload.get("screening_spec")
        unsupported_raw = payload.get("unsupported_fragments", [])
        if not isinstance(raw_spec, Mapping) or not isinstance(unsupported_raw, list):
            raise ScreeningError("AI_SCREENING_OUTPUT_INVALID", "AI选股输出结构无效")
        if any(not isinstance(item, str) for item in unsupported_raw):
            raise ScreeningError("AI_SCREENING_OUTPUT_INVALID", "AI不支持片段格式无效")
        spec = screening_spec_from_mapping(
            raw_spec,
            self._catalog,
            forced_origin="AI_ASSISTED",
        )
        unsupported = tuple(str(item) for item in unsupported_raw)
        status = ScreeningParseStatus.PARTIAL if unsupported else ScreeningParseStatus.COMPLETE
        return LocalScreeningParseResult(
            status=status,
            parser_source=ScreeningParserSource.AI_ASSISTED,
            spec=spec,
            recognized_conditions=self._recognized(spec),
            ambiguities=() if not unsupported else local.ambiguities,
            unsupported_fragments=unsupported,
            defaults_applied=(),
            normalized_text=local.normalized_text,
            potentially_catalog_matchable=True,
        )

    def _recognized(self, spec: ScreeningSpec) -> tuple[RecognizedScreeningCondition, ...]:
        return tuple(
            RecognizedScreeningCondition(
                condition_key=condition.condition_key,
                display_name=self._catalog.get(condition.condition_key).display_name,
                matched_expression=self._catalog.get(condition.condition_key).description,
            )
            for condition in spec.conditions
        )

    def _result_dict(
        self,
        result: LocalScreeningParseResult,
        *,
        preview: dict[str, object] | None,
        can_execute: bool,
    ) -> dict[str, object]:
        return {
            "parse_status": result.status.value,
            "parser_source": result.parser_source.value,
            "screening_spec": (
                None if result.spec is None else result.spec.snapshot(self._catalog)
            ),
            "recognized_conditions": [
                item.response_dict() for item in result.recognized_conditions
            ],
            "ambiguities": list(result.ambiguities),
            "unsupported_fragments": list(result.unsupported_fragments),
            "defaults_applied": [
                cast(AppliedScreeningDefault, item).response_dict()
                for item in result.defaults_applied
            ],
            "preview": preview,
            "can_execute": can_execute,
        }
