"""TA01 persistent multi-agent AI research HTTP API."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.ai_workbench import (
    ROLE_LABELS,
    AIResearchWorkbenchService,
    CreateResearchTaskRequest,
    ResearchTaskDetail,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.infrastructure.pdf_report import markdown_to_pdf
from alphadesk_api.schemas.ai_workbench import (
    ResearchAgentStepResponse,
    ResearchArtifactResponse,
    ResearchReportResponse,
    ResearchReportSummaryResponse,
    ResearchTaskCreateBody,
    ResearchTaskPageResponse,
    ResearchTaskResponse,
    ResearchWorkflowEventResponse,
)
from alphadesk_domain.ai_workbench import MultiAgentResearchProvider, ResearchDepth

router = APIRouter(tags=["ai-research-workbench"])


def service(request: Request) -> AIResearchWorkbenchService:
    provider = cast(MultiAgentResearchProvider, request.app.state.ai_workbench_provider)
    return AIResearchWorkbenchService(uow_factory(request), provider)


def report_summary(detail: ResearchTaskDetail) -> ResearchReportSummaryResponse | None:
    report = detail.report
    if report is None:
        return None
    return ResearchReportSummaryResponse(
        report_id=report.id,
        title=report.title,
        executive_summary=report.executive_summary,
        stance=report.stance,
        confidence=report.confidence,
        schema_version=report.schema_version,
        created_at=report.created_at,
    )


def task_response(detail: ResearchTaskDetail) -> ResearchTaskResponse:
    task = detail.task
    return ResearchTaskResponse(
        task_id=task.id,
        instrument=detail.instrument,
        question=task.question,
        depth=task.depth.value,
        start_date=task.start_date,
        end_date=task.end_date,
        provider_key=task.provider_key,
        model_name=task.model_name,
        engine_key=task.engine_key,
        engine_version=task.engine_version,
        checkpoint_key=task.checkpoint_key,
        execution_attempt=task.execution_attempt,
        last_checkpoint_at=task.last_checkpoint_at,
        is_real_provider=task.provider_key == "openai_compatible",
        status=task.status.value,
        progress_percent=task.progress_percent,
        current_stage=task.current_stage,
        warnings=list(task.warnings),
        error=(
            None
            if task.error_code is None
            else {"code": task.error_code, "message": task.error_message or "AI 调研失败"}
        ),
        correlation_id=task.correlation_id,
        started_at=task.started_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        steps=[
            ResearchAgentStepResponse(
                step_id=step.id,
                role=step.role.value,
                role_label=ROLE_LABELS[step.role],
                ordinal=step.ordinal,
                status=step.status.value,
                title=step.title,
                summary=step.summary,
                structured_output=step.structured_output,
                citations=list(step.citations),
                input_token_count=step.input_token_count,
                output_token_count=step.output_token_count,
                error=(
                    None
                    if step.error_code is None
                    else {
                        "code": step.error_code,
                        "message": step.error_message or "角色执行失败",
                    }
                ),
                started_at=step.started_at,
                completed_at=step.completed_at,
            )
            for step in detail.steps
        ],
        events=[
            ResearchWorkflowEventResponse(
                event_id=event.id,
                sequence=event.sequence,
                event_type=event.event_type,
                status=event.status,
                node_name=event.node_name,
                agent_role=None if event.agent_role is None else event.agent_role.value,
                tool_name=event.tool_name,
                payload=dict(event.payload),
                started_at=event.started_at,
                completed_at=event.completed_at,
                created_at=event.created_at,
            )
            for event in detail.events
        ],
        artifacts=[
            ResearchArtifactResponse(
                artifact_id=artifact.id,
                artifact_key=artifact.artifact_key,
                artifact_type=artifact.artifact_type,
                title=artifact.title,
                content_markdown=artifact.content_markdown,
                ordinal=artifact.ordinal,
                metadata=dict(artifact.artifact_metadata),
                source_ids=list(artifact.source_ids),
                created_at=artifact.created_at,
            )
            for artifact in detail.artifacts
        ],
        report=report_summary(detail),
        capabilities={
            "creates_signals": False,
            "creates_orders": False,
            "uses_broker": False,
            "modifies_portfolio": False,
            "supports_cancel": True,
            "supports_markdown_export": True,
            "supports_pdf_export": True,
            "uses_tradingagents_graph": task.engine_key == "tradingagents_graph",
            "persists_agent_reports": True,
            "persists_tool_trace": True,
            "supports_checkpoint_resume": True,
        },
    )


@router.post(
    "/ai/research-tasks",
    response_model=ResearchTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_research_task(
    request: Request, body: ResearchTaskCreateBody
) -> ResearchTaskResponse:
    try:
        depth = ResearchDepth(body.depth.upper())
        task = await service(request).create(
            CreateResearchTaskRequest(
                instrument_id=body.instrument_id,
                model_name=body.model_name,
                question=body.question,
                depth=depth,
                start_date=body.start_date,
                end_date=body.end_date,
                idempotency_key=body.idempotency_key,
                correlation_id=request_correlation_id(request),
            )
        )
        return task_response(await service(request).get(task.id))
    except ValueError as exc:
        raise to_app_error(ApplicationError("AI_RESEARCH_DEPTH_INVALID", "调研深度无效")) from exc
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/ai/research-tasks", response_model=ResearchTaskPageResponse)
async def list_research_tasks(
    request: Request,
    task_status: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ResearchTaskPageResponse:
    try:
        items, total = await service(request).list(
            status=task_status,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return ResearchTaskPageResponse(
            items=[task_response(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/ai/research-tasks/{task_id}", response_model=ResearchTaskResponse)
async def get_research_task(request: Request, task_id: UUID) -> ResearchTaskResponse:
    try:
        return task_response(await service(request).get(task_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/ai/research-tasks/{task_id}/cancel", response_model=ResearchTaskResponse)
async def cancel_research_task(request: Request, task_id: UUID) -> ResearchTaskResponse:
    try:
        await service(request).cancel(task_id)
        return task_response(await service(request).get(task_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/ai/research-tasks/{task_id}/retry", response_model=ResearchTaskResponse)
async def retry_research_task(request: Request, task_id: UUID) -> ResearchTaskResponse:
    try:
        await service(request).retry(task_id)
        return task_response(await service(request).get(task_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


def full_report(detail: ResearchTaskDetail) -> ResearchReportResponse:
    report = detail.report
    if report is None:
        raise ApplicationError("AI_RESEARCH_REPORT_NOT_READY", "AI 调研报告尚未生成")
    return ResearchReportResponse(
        report_id=report.id,
        task_id=report.task_id,
        title=report.title,
        executive_summary=report.executive_summary,
        stance=report.stance,
        confidence=report.confidence,
        sections=report.sections,
        citations=list(report.citations),
        limitations=list(report.limitations),
        markdown=report.markdown,
        schema_version=report.schema_version,
        created_at=report.created_at,
    )


@router.get("/ai/research-tasks/{task_id}/report", response_model=ResearchReportResponse)
async def get_research_report(request: Request, task_id: UUID) -> ResearchReportResponse:
    try:
        return full_report(await service(request).get(task_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/ai/reports/{task_id}", response_model=ResearchReportResponse)
async def get_research_report_alias(request: Request, task_id: UUID) -> ResearchReportResponse:
    """Stable report-oriented alias for integrations and future archive clients."""
    return await get_research_report(request, task_id)


@router.get("/ai/research-tasks/{task_id}/report/markdown")
async def export_research_markdown(request: Request, task_id: UUID) -> Response:
    try:
        report = full_report(await service(request).get(task_id))
        return Response(
            content=report.markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="ai-research-{task_id}.md"'},
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/ai/research-tasks/{task_id}/report/pdf")
async def export_research_pdf(request: Request, task_id: UUID) -> Response:
    try:
        report = full_report(await service(request).get(task_id))
        return Response(
            content=markdown_to_pdf(report.markdown, title=report.title),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="ai-research-{task_id}.pdf"'},
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
