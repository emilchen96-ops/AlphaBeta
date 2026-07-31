"""TA01 durable multi-agent research task orchestration."""

# ruff: noqa: RUF001

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_domain.ai_research import AIResearchError
from alphadesk_domain.ai_workbench import (
    WORKBENCH_PROMPT_VERSION,
    MultiAgentResearchProvider,
    MultiAgentResearchReport,
    MultiAgentResearchStep,
    MultiAgentResearchTask,
    ResearchAgentRole,
    ResearchAgentStatus,
    ResearchDepth,
    ResearchTaskStatus,
    StructuredResearchRequest,
    roles_for_depth,
)
from alphadesk_domain.enums import AdjustmentType, MarketTimeframe
from alphadesk_domain.unit_of_work import UnitOfWork

ROLE_LABELS = {
    ResearchAgentRole.MARKET_ANALYST: "市场环境分析师",
    ResearchAgentRole.TECHNICAL_ANALYST: "技术面分析师",
    ResearchAgentRole.FUNDAMENTAL_ANALYST: "基本面分析师",
    ResearchAgentRole.NEWS_ANALYST: "资讯与事件分析师",
    ResearchAgentRole.BULL_RESEARCHER: "看多研究员",
    ResearchAgentRole.BEAR_RESEARCHER: "看空研究员",
    ResearchAgentRole.RISK_REVIEWER: "风险复核员",
    ResearchAgentRole.RESEARCH_MANAGER: "研究经理",
}

SECTION_ORDER = (
    ("research_overview", "一、调研概览"),
    ("market_environment", "二、市场环境"),
    ("technical_analysis", "三、技术面"),
    ("fundamental_analysis", "四、基本面"),
    ("news_events", "五、资讯与事件"),
    ("bull_case", "六、看多论证"),
    ("bear_case", "七、看空论证"),
    ("risk_review", "八、风险与不确定性"),
    ("conclusion", "九、综合结论"),
    ("sources", "十、资料来源"),
)

ROLE_SECTION = {
    ResearchAgentRole.MARKET_ANALYST: "market_environment",
    ResearchAgentRole.TECHNICAL_ANALYST: "technical_analysis",
    ResearchAgentRole.FUNDAMENTAL_ANALYST: "fundamental_analysis",
    ResearchAgentRole.NEWS_ANALYST: "news_events",
    ResearchAgentRole.BULL_RESEARCHER: "bull_case",
    ResearchAgentRole.BEAR_RESEARCHER: "bear_case",
    ResearchAgentRole.RISK_REVIEWER: "risk_review",
    ResearchAgentRole.RESEARCH_MANAGER: "conclusion",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateResearchTaskRequest:
    instrument_id: UUID
    question: str
    depth: ResearchDepth
    start_date: date
    end_date: date
    idempotency_key: str
    correlation_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchTaskDetail:
    task: MultiAgentResearchTask
    instrument: dict[str, object]
    steps: tuple[MultiAgentResearchStep, ...]
    report: MultiAgentResearchReport | None


class AIResearchWorkbenchService:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, provider: MultiAgentResearchProvider
    ) -> None:
        self._uow_factory = uow_factory
        self._provider = provider

    async def create(self, request: CreateResearchTaskRequest) -> MultiAgentResearchTask:
        question = " ".join(request.question.split())
        if not question:
            raise ApplicationError("AI_RESEARCH_QUESTION_REQUIRED", "调研问题不能为空")
        if request.start_date > request.end_date:
            raise ApplicationError("AI_RESEARCH_DATE_RANGE_INVALID", "资料时间范围无效")
        if not self._provider.configured:
            raise ApplicationError(
                "AI_PROVIDER_DISABLED",
                "真实 AI Provider 尚未配置，请在项目根目录 .env 中配置后重启服务",
            )
        snapshot: dict[str, object] = {
            "instrument_id": str(request.instrument_id),
            "question": question,
            "depth": request.depth.value,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "prompt_version": WORKBENCH_PROMPT_VERSION,
        }
        async with self._uow_factory() as uow:
            existing = await uow.ai_research_tasks.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if existing.request_snapshot != snapshot:
                    raise ApplicationError(
                        "AI_RESEARCH_IDEMPOTENCY_CONFLICT",
                        "该幂等键已用于另一项 AI 调研",
                    )
                return existing
            instrument = await uow.instruments.get_by_id(request.instrument_id)
            if instrument is None:
                raise ApplicationError("AI_RESEARCH_INSTRUMENT_NOT_FOUND", "研究股票不存在")
            task = MultiAgentResearchTask(
                instrument_id=request.instrument_id,
                question=question,
                depth=request.depth,
                start_date=request.start_date,
                end_date=request.end_date,
                provider_key=self._provider.provider_key,
                model_name=self._provider.model_name,
                idempotency_key=request.idempotency_key,
                correlation_id=request.correlation_id,
                request_snapshot=snapshot,
            )
            steps = [
                MultiAgentResearchStep(task_id=task.id, role=role, ordinal=index)
                for index, role in enumerate(roles_for_depth(request.depth))
            ]
            await uow.ai_research_tasks.add(task)
            await uow.ai_research_steps.add_many(steps)
            await uow.commit()
            return task

    async def get(self, task_id: UUID) -> ResearchTaskDetail:
        async with self._uow_factory() as uow:
            return await self._detail(uow, task_id)

    async def list(
        self, *, status: str | None, offset: int, limit: int
    ) -> tuple[list[ResearchTaskDetail], int]:
        async with self._uow_factory() as uow:
            tasks, total = await uow.ai_research_tasks.list(
                status=status, offset=offset, limit=limit
            )
            details = [await self._detail(uow, task.id) for task in tasks]
            return details, total

    async def cancel(self, task_id: UUID) -> MultiAgentResearchTask:
        async with self._uow_factory() as uow:
            task = await uow.ai_research_tasks.get_by_id(task_id)
            if task is None:
                raise ApplicationError("AI_RESEARCH_TASK_NOT_FOUND", "AI 调研任务不存在")
            task.cancel()
            await uow.ai_research_tasks.update(task)
            await uow.commit()
            return task

    async def retry(self, task_id: UUID) -> MultiAgentResearchTask:
        async with self._uow_factory() as uow:
            task = await uow.ai_research_tasks.get_by_id(task_id)
            if task is None:
                raise ApplicationError("AI_RESEARCH_TASK_NOT_FOUND", "AI 调研任务不存在")
            try:
                task.retry()
            except ValueError as exc:
                raise ApplicationError(
                    "AI_RESEARCH_TASK_NOT_RETRYABLE", "只有失败的 AI 调研任务可以重试"
                ) from exc
            for step in await uow.ai_research_steps.list_by_task(task_id):
                if step.status is ResearchAgentStatus.FAILED:
                    step.status = ResearchAgentStatus.PENDING
                    step.error_code = None
                    step.error_message = None
                    step.started_at = None
                    step.completed_at = None
                    step.updated_at = datetime.now(UTC)
                    await uow.ai_research_steps.update(step)
            await uow.ai_research_tasks.update(task)
            await uow.commit()
            return task

    async def _detail(self, uow: UnitOfWork, task_id: UUID) -> ResearchTaskDetail:
        task = await uow.ai_research_tasks.get_by_id(task_id)
        if task is None:
            raise ApplicationError("AI_RESEARCH_TASK_NOT_FOUND", "AI 调研任务不存在")
        instrument = await uow.instruments.get_by_id(task.instrument_id)
        if instrument is None:
            raise ApplicationError("AI_RESEARCH_INSTRUMENT_NOT_FOUND", "研究股票不存在")
        return ResearchTaskDetail(
            task=task,
            instrument={
                "id": str(instrument.id),
                "symbol": instrument.symbol,
                "exchange": instrument.exchange,
                "name": instrument.name,
            },
            steps=tuple(await uow.ai_research_steps.list_by_task(task_id)),
            report=await uow.ai_research_reports.get_by_task(task_id),
        )


class AIResearchTaskProcessor:
    """One durable worker iteration. Completed steps make retries idempotent."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        provider: MultiAgentResearchProvider,
        *,
        stale_seconds: int = 300,
    ) -> None:
        self._uow_factory = uow_factory
        self._provider = provider
        self._stale_seconds = stale_seconds

    async def run_once(self) -> UUID | None:
        task_id = await self._claim()
        if task_id is None:
            return None
        try:
            await self._prepare_data(task_id)
            await self._run_steps(task_id)
            await self._generate_report(task_id)
        except (ApplicationError, AIResearchError, RuntimeError, ValueError) as exc:
            code = getattr(exc, "code", "AI_RESEARCH_WORKER_FAILED")
            await self._fail(task_id, str(code), str(exc))
        return task_id

    async def _claim(self) -> UUID | None:
        stale_before = datetime.now(UTC) - timedelta(seconds=self._stale_seconds)
        async with self._uow_factory() as uow:
            task = await uow.ai_research_tasks.claim_next(stale_before=stale_before)
            if task is None:
                return None
            task.advance(ResearchTaskStatus.PREPARING_DATA, 5, "正在准备本地研究资料")
            await uow.ai_research_tasks.update(task)
            await uow.commit()
            return task.id

    async def _prepare_data(self, task_id: UUID) -> None:
        async with self._uow_factory() as uow:
            task = await self._require_active_task(uow, task_id)
            if task.data_snapshot:
                return
            instrument = await uow.instruments.get_by_id(task.instrument_id)
            source = await uow.market_data_sources.get_by_code("MINIQMT")
            if instrument is None or source is None:
                raise ApplicationError(
                    "AI_RESEARCH_DATA_SOURCE_UNAVAILABLE",
                    "研究股票或 MiniQMT 本地行情源不可用",
                )
            start = datetime.combine(task.start_date, datetime.min.time(), tzinfo=UTC)
            end = datetime.combine(task.end_date, datetime.max.time(), tzinfo=UTC)
            bars = await uow.market_bars.get_bars(
                instrument_id=task.instrument_id,
                source_id=source.id,
                timeframe=MarketTimeframe.DAY_1,
                adjustment_type=AdjustmentType.NONE,
                start=start,
                end=end,
                limit=1500,
            )
            if not bars:
                raise ApplicationError(
                    "AI_RESEARCH_MARKET_DATA_UNAVAILABLE",
                    "所选时间范围没有本地 MiniQMT 历史日线，请先在数据中心补齐",
                )
            items, _ = await uow.information_items.list(
                search=None,
                source_id=None,
                instrument_id=task.instrument_id,
                theme_key=None,
                offset=0,
                limit=100,
            )
            items = [item for item in items if start <= item.published_at <= end]
            task.data_snapshot = {
                "instrument": {
                    "id": str(instrument.id),
                    "symbol": instrument.symbol,
                    "exchange": instrument.exchange,
                    "name": instrument.name,
                },
                "source": "MINIQMT",
                "bar_count": len(bars),
                "information_count": len(items),
                "market_bars": [
                    {
                        "source_id": f"market-bar:{bar.bar_time.date().isoformat()}",
                        "date": bar.bar_time.date().isoformat(),
                        "open": str(bar.open),
                        "high": str(bar.high),
                        "low": str(bar.low),
                        "close": str(bar.close),
                        "volume": str(bar.volume),
                        "amount": None if bar.amount is None else str(bar.amount),
                    }
                    for bar in bars
                ],
                "information": [
                    {
                        "source_id": f"information:{item.id}",
                        "title": item.normalized_title,
                        "content": item.normalized_content[:4000],
                        "published_at": item.published_at.isoformat(),
                    }
                    for item in items
                ],
            }
            task.advance(ResearchTaskStatus.RUNNING_AGENTS, 15, "本地资料准备完成")
            await uow.ai_research_tasks.update(task)
            await uow.commit()

    async def _run_steps(self, task_id: UUID) -> None:
        async with self._uow_factory() as uow:
            initial = await self._require_active_task(uow, task_id)
            payload = dict(initial.data_snapshot)
            payload["question"] = initial.question
            payload["date_range"] = {
                "start": initial.start_date.isoformat(),
                "end": initial.end_date.isoformat(),
            }
            steps = await uow.ai_research_steps.list_by_task(task_id)
        previous: list[dict[str, object]] = []
        for index, step in enumerate(steps):
            if step.status is ResearchAgentStatus.COMPLETED:
                previous.append(step.structured_output)
                continue
            async with self._uow_factory() as uow:
                task = await self._require_active_task(uow, task_id)
                stage_status = self._status_for_role(step.role)
                progress = 18 + int((index / max(len(steps), 1)) * 68)
                task.advance(stage_status, progress, f"{ROLE_LABELS[step.role]}正在工作")
                step.status = ResearchAgentStatus.RUNNING
                step.started_at = datetime.now(UTC)
                step.updated_at = step.started_at
                await uow.ai_research_tasks.update(task)
                await uow.ai_research_steps.update(step)
                await uow.commit()
            request_payload = {**payload, "previous_agent_outputs": previous}
            try:
                response = await self._provider.complete_structured(
                    StructuredResearchRequest(
                        role=step.role,
                        system_prompt=self._system_prompt(step.role),
                        payload=request_payload,
                        schema_name=f"alphadesk_{step.role.value.lower()}_output",
                        output_schema=self._output_schema(
                            manager=step.role is ResearchAgentRole.RESEARCH_MANAGER
                        ),
                    )
                )
                self._validate_output(response.output, step.role)
                self._validate_citations(response.output, request_payload)
                step.status = ResearchAgentStatus.COMPLETED
                step.title = str(response.output["title"])
                step.summary = str(response.output["summary"])
                step.structured_output = response.output
                citations = response.output.get("citations", [])
                step.citations = tuple(cast_citations(citations))
                step.input_token_count = response.input_token_count
                step.output_token_count = response.output_token_count
                previous.append(response.output)
            except (AIResearchError, RuntimeError, ValueError) as exc:
                step.status = ResearchAgentStatus.FAILED
                step.error_code = str(getattr(exc, "code", "AI_AGENT_FAILED"))[:64]
                step.error_message = str(exc)[:1000]
            step.completed_at = datetime.now(UTC)
            step.updated_at = step.completed_at
            async with self._uow_factory() as uow:
                await self._require_active_task(uow, task_id)
                await uow.ai_research_steps.update(step)
                await uow.commit()

    async def _generate_report(self, task_id: UUID) -> None:
        async with self._uow_factory() as uow:
            task = await self._require_active_task(uow, task_id)
            existing = await uow.ai_research_reports.get_by_task(task_id)
            if existing is not None:
                task.finish(partial=False)
                await uow.ai_research_tasks.update(task)
                await uow.commit()
                return
            task.advance(ResearchTaskStatus.GENERATING_REPORT, 92, "正在生成结构化调研报告")
            steps = await uow.ai_research_steps.list_by_task(task_id)
            instrument = await uow.instruments.get_by_id(task.instrument_id)
            if instrument is None:
                raise ApplicationError("AI_RESEARCH_INSTRUMENT_NOT_FOUND", "研究股票不存在")
            completed = [step for step in steps if step.status is ResearchAgentStatus.COMPLETED]
            if not completed:
                raise ApplicationError("AI_RESEARCH_ALL_AGENTS_FAILED", "所有调研角色均执行失败")
            manager = next(
                (step for step in completed if step.role is ResearchAgentRole.RESEARCH_MANAGER),
                None,
            )
            sections: dict[str, object] = {
                "research_overview": {
                    "title": "调研概览",
                    "summary": task.question,
                    "findings": [
                        f"资料范围：{task.start_date.isoformat()} 至 {task.end_date.isoformat()}",
                        f"调研深度：{task.depth.value}",
                        f"模型：{task.provider_key} / {task.model_name}",
                    ],
                }
            }
            citations: list[dict[str, object]] = []
            for step in completed:
                sections[ROLE_SECTION[step.role]] = step.structured_output
                citations.extend(step.citations)
            for key, _ in SECTION_ORDER:
                sections.setdefault(
                    key,
                    {
                        "title": "资料不足",
                        "summary": "本次调研未生成该部分。",
                        "findings": [],
                        "risks": [],
                        "uncertainties": ["对应角色未完成或快速模式未启用该角色。"],
                    },
                )
            unique_citations = list(
                {str(item.get("source_id")): item for item in citations}.values()
            )
            sections["sources"] = {
                "title": "资料来源",
                "summary": f"共引用 {len(unique_citations)} 项可追溯资料。",
                "items": unique_citations,
            }
            manager_output = {} if manager is None else manager.structured_output
            summary = str(
                manager_output.get("executive_summary")
                or manager_output.get("summary")
                or completed[-1].summary
            )
            limitations = [
                "本报告仅供研究参考，不构成投资建议。",
                "资料来自 AlphaDesk 本地已准备的数据，可能不完整或存在时滞。",
            ]
            if task.provider_key == "fake":
                limitations.append(
                    "本报告由 Fake Provider 生成，仅用于流程验收，不是真实 AI 调研。"
                )
            report = MultiAgentResearchReport(
                task_id=task.id,
                title=f"{instrument.name}（{instrument.symbol}）AI 调研报告",
                executive_summary=summary,
                stance=str(manager_output.get("stance") or "中性"),
                confidence=str(manager_output.get("confidence") or "有限"),
                sections=sections,
                citations=tuple(unique_citations),
                limitations=tuple(limitations),
                markdown=render_markdown(
                    title=f"{instrument.name}（{instrument.symbol}）AI 调研报告",
                    summary=summary,
                    stance=str(manager_output.get("stance") or "中性"),
                    confidence=str(manager_output.get("confidence") or "有限"),
                    sections=sections,
                    limitations=limitations,
                ),
            )
            failed = [step for step in steps if step.status is ResearchAgentStatus.FAILED]
            await uow.ai_research_reports.add(report)
            task.finish(
                partial=bool(failed),
                warnings=tuple(
                    f"{ROLE_LABELS[step.role]}未完成：{step.error_message or step.error_code}"
                    for step in failed
                ),
            )
            await uow.ai_research_tasks.update(task)
            await uow.commit()

    async def _fail(self, task_id: UUID, code: str, message: str) -> None:
        async with self._uow_factory() as uow:
            task = await uow.ai_research_tasks.get_by_id(task_id)
            if task is None or task.terminal:
                return
            task.fail(code, message or "AI 调研任务失败")
            await uow.ai_research_tasks.update(task)
            await uow.commit()

    @staticmethod
    async def _require_active_task(uow: UnitOfWork, task_id: UUID) -> MultiAgentResearchTask:
        task = await uow.ai_research_tasks.get_by_id(task_id)
        if task is None:
            raise ApplicationError("AI_RESEARCH_TASK_NOT_FOUND", "AI 调研任务不存在")
        if task.status is ResearchTaskStatus.CANCELED:
            raise ApplicationError("AI_RESEARCH_TASK_CANCELED", "AI 调研任务已取消")
        return task

    @staticmethod
    def _status_for_role(role: ResearchAgentRole) -> ResearchTaskStatus:
        if role in {ResearchAgentRole.BULL_RESEARCHER, ResearchAgentRole.BEAR_RESEARCHER}:
            return ResearchTaskStatus.DEBATING
        if role is ResearchAgentRole.RISK_REVIEWER:
            return ResearchTaskStatus.RISK_REVIEW
        if role is ResearchAgentRole.RESEARCH_MANAGER:
            return ResearchTaskStatus.GENERATING_REPORT
        return ResearchTaskStatus.RUNNING_AGENTS

    @staticmethod
    def _system_prompt(role: ResearchAgentRole) -> str:
        return (
            f"你是 AlphaDesk 的{ROLE_LABELS[role]}。只使用输入资料，严禁编造数据，"
            "每项事实必须引用输入中存在的 source_id。明确区分事实、推断、风险和未知。"
            "输出严格符合给定 JSON Schema；内容仅供研究，不构成投资建议。"
        )

    @staticmethod
    def _output_schema(*, manager: bool) -> dict[str, object]:
        properties: dict[str, object] = {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "findings": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "uncertainties": {"type": "array", "items": {"type": "string"}},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source_id": {"type": "string"},
                        "source_type": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["source_id", "source_type", "title"],
                },
            },
        }
        required = ["title", "summary", "findings", "risks", "uncertainties", "citations"]
        if manager:
            properties.update(
                {
                    "stance": {"type": "string"},
                    "confidence": {"type": "string"},
                    "executive_summary": {"type": "string"},
                }
            )
            required.extend(["stance", "confidence", "executive_summary"])
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        }

    @staticmethod
    def _validate_output(output: dict[str, object], role: ResearchAgentRole) -> None:
        required = {"title", "summary", "findings", "risks", "uncertainties", "citations"}
        if role is ResearchAgentRole.RESEARCH_MANAGER:
            required |= {"stance", "confidence", "executive_summary"}
        if not required.issubset(output):
            raise ValueError("AI 角色输出缺少必填字段")

    @staticmethod
    def _validate_citations(output: dict[str, object], payload: dict[str, object]) -> None:
        available: set[str] = set()
        for field in ("market_bars", "information"):
            items = payload.get(field, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and item.get("source_id"):
                        available.add(str(item["source_id"]))
        citations = cast_citations(output.get("citations", []))
        unknown = [
            str(item.get("source_id"))
            for item in citations
            if str(item.get("source_id")) not in available
        ]
        if unknown:
            raise ValueError(f"AI 输出包含无法追溯的资料引用：{', '.join(unknown[:3])}")


def cast_citations(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("AI citations must be a list")
    return [item for item in value if isinstance(item, dict)]


def render_markdown(
    *,
    title: str,
    summary: str,
    stance: str,
    confidence: str,
    sections: dict[str, object],
    limitations: list[str],
) -> str:
    lines = [
        f"# {title}",
        "",
        f"> 综合倾向：{stance}；置信度：{confidence}",
        "",
        summary,
        "",
    ]
    for key, heading in SECTION_ORDER:
        value = sections.get(key, {})
        section = value if isinstance(value, dict) else {}
        lines.extend([f"## {heading}", "", str(section.get("summary") or "暂无内容"), ""])
        for label, field in (
            ("主要发现", "findings"),
            ("风险", "risks"),
            ("不确定性", "uncertainties"),
        ):
            items = section.get(field, [])
            if isinstance(items, list) and items:
                lines.append(f"### {label}")
                lines.extend(f"- {item}" for item in items)
                lines.append("")
    lines.extend(["## 重要限制", ""])
    lines.extend(f"- {item}" for item in limitations)
    lines.append("")
    return "\n".join(lines)


def decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)
