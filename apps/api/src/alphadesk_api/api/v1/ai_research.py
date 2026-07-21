"""A01 provider status, grounded analyses and research insights."""

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.ai_research import (
    AIResearchAnalysisService,
    AIResearchIntegrityService,
    AIResearchQueryService,
    AnalysisRequest,
    InsightDetail,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.infrastructure.ai_research_provider import (
    describe_ai_provider,
    test_ai_provider,
)
from alphadesk_api.schemas.ai_research import (
    AIAnalysisCreateBody,
    AIAnalysisRunPageResponse,
    AIAnalysisRunResponse,
    AIIntegrityResponse,
    AIProviderStatusResponse,
    AIProviderTestBody,
    AIProviderTestResponse,
    ResearchEvidenceResponse,
    ResearchInsightPageResponse,
    ResearchInsightResponse,
)
from alphadesk_domain.ai_research import (
    AIAnalysisRun,
    AIAnalysisType,
    AIResearchProvider,
    ResearchEvidence,
    ResearchInsight,
)

router = APIRouter(tags=["ai-research"])


def provider(request: Request) -> AIResearchProvider:
    return cast(AIResearchProvider, request.app.state.ai_research_provider)


def evidence_response(item: ResearchEvidence) -> ResearchEvidenceResponse:
    return ResearchEvidenceResponse(
        evidence_id=item.id,
        information_item_id=item.information_item_id,
        market_event_id=item.market_event_id,
        evidence_text=item.evidence_text,
        evidence_location=item.evidence_location,
    )


def insight_response(
    item: ResearchInsight, evidence: tuple[ResearchEvidence, ...] = ()
) -> ResearchInsightResponse:
    return ResearchInsightResponse(
        insight_id=item.id,
        analysis_run_id=item.analysis_run_id,
        insight_type=item.insight_type,
        title=item.title,
        summary=item.summary,
        impact_direction=item.impact_direction.value,
        importance_score=format(item.importance_score.normalize(), "f"),
        confidence=format(item.confidence.normalize(), "f"),
        time_horizon=item.time_horizon,
        key_facts=list(item.key_facts),
        uncertainties=list(item.uncertainties),
        research_questions=list(item.research_questions),
        structured_output=item.structured_output,
        schema_version=item.schema_version,
        created_at=item.created_at,
        evidence=[evidence_response(value) for value in evidence],
    )


def run_response(
    run: AIAnalysisRun,
    *,
    replayed: bool = False,
    insight: ResearchInsight | None = None,
    evidence: tuple[ResearchEvidence, ...] = (),
) -> AIAnalysisRunResponse:
    return AIAnalysisRunResponse(
        analysis_id=run.id,
        provider_key=run.provider_key,
        model_name=run.model_name,
        analysis_type=run.analysis_type.value,
        prompt_template_key=run.prompt_template_key,
        prompt_version=run.prompt_version,
        input_document_ids=list(run.input_document_ids),
        input_event_ids=list(run.input_event_ids),
        instrument_ids=list(run.instrument_ids),
        user_question=run.user_question,
        status=run.status.value,
        input_token_count=run.input_token_count,
        output_token_count=run.output_token_count,
        total_token_count=run.total_token_count,
        estimated_cost=(
            None if run.estimated_cost is None else format(run.estimated_cost.normalize(), "f")
        ),
        cost_currency="USD" if run.estimated_cost is not None else None,
        is_real_provider=run.provider_key == "openai_compatible",
        started_at=run.started_at,
        completed_at=run.completed_at,
        failed_at=run.failed_at,
        error=(
            None
            if run.error_code is None
            else {"code": run.error_code, "message": run.error_message or "AI analysis failed"}
        ),
        correlation_id=run.correlation_id,
        created_at=run.created_at,
        replayed=replayed,
        insight=None if insight is None else insight_response(insight, evidence),
        capabilities={
            "creates_signals": False,
            "creates_orders": False,
            "uses_scanner": False,
            "uses_risk": False,
            "uses_broker": False,
            "modifies_portfolio": False,
            "has_long_term_memory": False,
        },
    )


@router.get("/ai/providers/status", response_model=AIProviderStatusResponse)
async def ai_provider_status(request: Request) -> AIProviderStatusResponse:
    snapshot = describe_ai_provider(provider(request))
    message = {
        "DISABLED": "真实 AI Provider 尚未配置; 默认安全禁用",
        "FAKE": "Fake Provider 仅用于测试和明确的本地演示",
        "REAL_CONFIGURED": "真实 AI Provider 已配置, 尚未完成本进程连通测试",
        "REAL_AVAILABLE": "真实 AI Provider 已配置且最近连通成功",
        "REAL_UNAVAILABLE": "真实 AI Provider 配置不完整或最近连通失败",
    }[snapshot.mode]
    return AIProviderStatusResponse(
        provider_key=snapshot.provider_key,
        model=snapshot.model_name,
        model_name=snapshot.model_name,
        configured=snapshot.configured,
        available=snapshot.available,
        mode=snapshot.mode,
        real_provider_available=snapshot.mode == "REAL_AVAILABLE",
        base_url_summary=snapshot.base_url_summary,
        last_success_at=snapshot.last_success_at,
        last_failure_at=snapshot.last_failure_at,
        last_error_code=snapshot.last_error_code,
        capabilities=list(snapshot.capabilities),
        warnings=list(snapshot.warnings),
        message=message,
    )


@router.post("/ai/providers/test", response_model=AIProviderTestResponse)
async def test_ai_provider_connection(
    request: Request, body: AIProviderTestBody
) -> AIProviderTestResponse:
    del body
    if request.app.state.settings.environment not in {"development", "test"}:
        raise to_app_error(
            ApplicationError(
                "AI_PROVIDER_TEST_FORBIDDEN",
                "provider connectivity test is only available in development or test",
            )
        )
    result = await test_ai_provider(provider(request))
    return AIProviderTestResponse(
        success=result.success,
        provider_key=result.provider_key,
        model_name=result.model_name,
        mode=result.mode,
        latency_ms=result.latency_ms,
        error_code=result.error_code,
        warnings=list(result.warnings),
    )


@router.post(
    "/ai/analyses",
    response_model=AIAnalysisRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ai_analysis(request: Request, body: AIAnalysisCreateBody) -> AIAnalysisRunResponse:
    try:
        try:
            analysis_type = AIAnalysisType(body.analysis_type)
        except ValueError as exc:
            raise ApplicationError("AI_ANALYSIS_TYPE_INVALID", "analysis type is invalid") from exc
        outcome = await AIResearchAnalysisService(uow_factory(request), provider(request)).analyze(
            AnalysisRequest(
                analysis_type=analysis_type,
                event_ids=tuple(body.event_ids),
                information_item_ids=tuple(body.information_item_ids),
                instrument_ids=tuple(body.instrument_ids),
                question=body.question,
                idempotency_key=body.idempotency_key,
                correlation_id=request_correlation_id(request),
            )
        )
        return run_response(
            outcome.run,
            replayed=outcome.replayed,
            insight=outcome.insight,
            evidence=outcome.evidence,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/ai/analyses", response_model=AIAnalysisRunPageResponse)
async def list_ai_analyses(
    request: Request,
    analysis_type: str | None = None,
    run_status: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> AIAnalysisRunPageResponse:
    items, total = await AIResearchQueryService(uow_factory(request)).runs(
        analysis_type=analysis_type,
        status=run_status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return AIAnalysisRunPageResponse(
        items=[run_response(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/ai/analyses/{analysis_id}", response_model=AIAnalysisRunResponse)
async def get_ai_analysis(request: Request, analysis_id: UUID) -> AIAnalysisRunResponse:
    outcome = await AIResearchQueryService(uow_factory(request)).run(analysis_id)
    if outcome is None:
        raise to_app_error(ApplicationError("AI_ANALYSIS_RUN_NOT_FOUND", "analysis not found"))
    return run_response(outcome.run, insight=outcome.insight, evidence=outcome.evidence)


@router.get("/research-insights", response_model=ResearchInsightPageResponse)
async def list_research_insights(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ResearchInsightPageResponse:
    values, total = await AIResearchQueryService(uow_factory(request)).insights(
        offset=(page - 1) * page_size, limit=page_size
    )
    return ResearchInsightPageResponse(
        items=[insight_response(item) for item in values],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/research-insights/{insight_id}", response_model=ResearchInsightResponse)
async def get_research_insight(request: Request, insight_id: UUID) -> ResearchInsightResponse:
    detail: InsightDetail | None = await AIResearchQueryService(uow_factory(request)).insight(
        insight_id
    )
    if detail is None:
        raise to_app_error(ApplicationError("RESEARCH_INSIGHT_NOT_FOUND", "insight not found"))
    return insight_response(detail.insight, detail.evidence)


@router.get("/ai/analyses/{analysis_id}/integrity", response_model=AIIntegrityResponse)
async def ai_analysis_integrity(request: Request, analysis_id: UUID) -> AIIntegrityResponse:
    try:
        issues = await AIResearchIntegrityService(uow_factory(request)).verify(analysis_id)
        return AIIntegrityResponse(analysis_id=analysis_id, valid=not issues, issues=issues)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
