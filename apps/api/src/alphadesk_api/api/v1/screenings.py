# ruff: noqa: RUF001
"""SC02-A condition catalog, templates and durable screening runs."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import (
    request_correlation_id,
    to_app_error,
    uow_factory,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.scanners import ScannerQueryService
from alphadesk_api.application.screenings import ScreeningRunService
from alphadesk_api.schemas.screenings import (
    ConditionDefinitionResponse,
    RankingRuleBody,
    ScreeningConditionBody,
    ScreeningCreateBody,
    ScreeningProgressResponse,
    ScreeningResultPageResponse,
    ScreeningResultResponse,
    ScreeningRunPageResponse,
    ScreeningRunResponse,
    ScreeningTemplateResponse,
    UniverseSpecBody,
)
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.scanners import ScanRun
from alphadesk_domain.screening import (
    ConditionCatalog,
    RankingDirection,
    RankingRule,
    ScreeningCondition,
    ScreeningError,
    ScreeningSpec,
    UniverseSpec,
    screening_templates,
)

router = APIRouter(tags=["research-screenings"])


def catalog(request: Request) -> ConditionCatalog:
    return cast(ConditionCatalog, request.app.state.screening_condition_catalog)


def _domain_spec(body: ScreeningCreateBody) -> ScreeningSpec:
    return ScreeningSpec(
        schema_version=body.schema_version,
        name=body.name,
        origin=body.origin,
        universe_spec=_domain_universe(body.universe_spec),
        as_of_date=body.as_of_date,
        timeframe=MarketTimeframe(body.timeframe),
        conditions=tuple(_domain_condition(item) for item in body.conditions),
        exclusions=body.exclusions,
        ranking_rules=tuple(_domain_ranking(item) for item in body.ranking_rules),
        top_n=body.top_n,
        price_adjustment_mode=PriceAdjustmentMode(body.price_adjustment_mode),
    )


def _domain_universe(body: UniverseSpecBody) -> UniverseSpec:
    return UniverseSpec(
        universe_key=body.universe_key,
        excluded_instrument_ids=tuple(body.excluded_instrument_ids),
        exclude_st=body.exclude_st,
        exclude_bse=body.exclude_bse,
        exclude_star_market=body.exclude_star_market,
        exclude_chinext=body.exclude_chinext,
    )


def _domain_condition(body: ScreeningConditionBody) -> ScreeningCondition:
    return ScreeningCondition(
        condition_key=body.condition_key,
        parameters=body.parameters,
    )


def _domain_ranking(body: RankingRuleBody) -> RankingRule:
    return RankingRule(field=body.field, direction=RankingDirection(body.direction))


def _run_response(run: ScanRun, *, replayed: bool = False) -> ScreeningRunResponse:
    return ScreeningRunResponse(
        screening_id=run.id,
        name=str(run.screening_spec.get("name", run.scanner_key)),
        status=run.status.value,
        current_phase=run.status.value,
        spec=run.screening_spec,
        total_instruments=run.total_instruments,
        processed_instruments=run.instruments_scanned,
        ready_instruments=run.data_ready_instruments,
        insufficient_data_count=run.insufficient_history,
        indeterminate_count=run.indeterminate_count,
        failed_count=run.failed_instruments,
        matched_count=run.matches_found,
        progress_percent=run.progress_percent,
        elapsed_ms=run.elapsed_ms,
        query_count=run.query_count,
        bars_read=run.bars_read,
        batch_count=run.batch_count,
        execution_stats=run.execution_stats,
        error=(
            None
            if run.error_code is None
            else {"code": run.error_code, "message": run.error_message or "筛选失败"}
        ),
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        replayed=replayed,
    )


@router.get(
    "/screening-conditions",
    response_model=list[ConditionDefinitionResponse],
)
async def list_screening_conditions(request: Request) -> list[ConditionDefinitionResponse]:
    return [
        ConditionDefinitionResponse.model_validate(item.response_dict())
        for item in catalog(request).list()
    ]


@router.get(
    "/screening-templates",
    response_model=list[ScreeningTemplateResponse],
)
async def list_screening_templates(request: Request) -> list[ScreeningTemplateResponse]:
    condition_catalog = catalog(request)
    values = []
    descriptions = {
        "LIMIT_UP_PULLBACK": "最近涨停后回踩起涨锚点，且成交量缩至涨停日的一半以内",
        "BOTTOM_VOLUME_EXPANSION": "价格处于60日区间底部，成交量超过20日均量2倍且收阳",
    }
    for item in screening_templates():
        key = item.conditions[0].condition_key
        values.append(
            ScreeningTemplateResponse(
                template_key=key,
                display_name=item.name,
                description=descriptions[key],
                spec=item.snapshot(condition_catalog),
            )
        )
    return values


@router.post(
    "/research/screenings",
    response_model=ScreeningRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_screening(request: Request, body: ScreeningCreateBody) -> ScreeningRunResponse:
    try:
        outcome = await ScreeningRunService(
            uow_factory(request),
            catalog(request),
            source_code=request.app.state.settings.authoritative_market_source,
        ).enqueue(
            _domain_spec(body),
            correlation_id=request_correlation_id(request),
            idempotency_key=body.idempotency_key,
        )
        return _run_response(outcome.run, replayed=outcome.replayed)
    except ScreeningError as exc:
        raise to_app_error(ApplicationError(exc.code, str(exc))) from exc
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get(
    "/research/screenings",
    response_model=ScreeningRunPageResponse,
)
async def list_screenings(
    request: Request,
    run_status: str | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ScreeningRunPageResponse:
    async with uow_factory(request)() as uow:
        items, _ = await uow.scan_runs.list(
            scanner_key=None,
            status=run_status,
            instrument_id=None,
            created_from=None,
            created_to=None,
            offset=0,
            limit=10_000,
        )
    filtered = [item for item in items if item.screening_spec]
    total = len(filtered)
    start = (page - 1) * page_size
    return ScreeningRunPageResponse(
        items=[_run_response(item) for item in filtered[start : start + page_size]],
        page=page,
        page_size=page_size,
        total=total,
    )


async def _get_screening(request: Request, screening_id: UUID) -> ScanRun:
    async with uow_factory(request)() as uow:
        run = await uow.scan_runs.get_by_id(screening_id)
    if run is None or not run.screening_spec:
        raise to_app_error(ApplicationError("SCREENING_RUN_NOT_FOUND", "筛选任务不存在"))
    return run


@router.get(
    "/research/screenings/{screening_id}",
    response_model=ScreeningRunResponse,
)
async def get_screening(request: Request, screening_id: UUID) -> ScreeningRunResponse:
    return _run_response(await _get_screening(request, screening_id))


@router.get(
    "/research/screenings/{screening_id}/progress",
    response_model=ScreeningProgressResponse,
)
async def get_screening_progress(request: Request, screening_id: UUID) -> ScreeningProgressResponse:
    run = await _get_screening(request, screening_id)
    return ScreeningProgressResponse(
        screening_id=run.id,
        status=run.status.value,
        total_instruments=run.total_instruments,
        processed_instruments=run.instruments_scanned,
        ready_instruments=run.data_ready_instruments,
        insufficient_data_count=run.insufficient_history,
        indeterminate_count=run.indeterminate_count,
        failed_count=run.failed_instruments,
        matched_count=run.matches_found,
        progress_percent=run.progress_percent,
        elapsed_ms=run.elapsed_ms,
    )


@router.get(
    "/research/screenings/{screening_id}/results",
    response_model=ScreeningResultPageResponse,
)
async def get_screening_results(
    request: Request,
    screening_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ScreeningResultPageResponse:
    await _get_screening(request, screening_id)
    try:
        items = await ScannerQueryService(uow_factory(request)).results(screening_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    total = len(items)
    start = (page - 1) * page_size
    return ScreeningResultPageResponse(
        items=[
            ScreeningResultResponse(
                result_id=item.result.id,
                screening_id=item.result.scan_run_id,
                rank=item.result.rank,
                instrument_id=item.result.instrument_id,
                symbol=item.symbol,
                exchange=item.exchange,
                instrument_name=item.instrument_name,
                score=str(item.result.score),
                reference_price=str(item.result.reference_price),
                matched_at=item.result.matched_at,
                reason_code=item.result.reason_code,
                reason=item.result.reason,
                metrics=item.result.metrics,
            )
            for item in items[start : start + page_size]
        ],
        page=page,
        page_size=page_size,
        total=total,
    )
