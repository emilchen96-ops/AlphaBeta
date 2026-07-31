# ruff: noqa: RUF001
"""SC02-A condition catalog, templates and durable screening runs."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from redis.exceptions import RedisError

from alphadesk_api.api.v1.market_common import (
    request_correlation_id,
    to_app_error,
    uow_factory,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.miniqmt_market_data import HISTORY_QUEUE_KEY
from alphadesk_api.application.scanners import ScannerQueryService
from alphadesk_api.application.screening_specs import ScreeningSpecService
from alphadesk_api.application.screenings import (
    BACKFILL_SECONDS_PER_BATCH,
    ScreeningRunService,
)
from alphadesk_api.application.user_screenings import (
    ScreeningWatchlistService,
    UserScreeningService,
)
from alphadesk_api.schemas.screenings import (
    ConditionDefinitionResponse,
    RankingRuleBody,
    ScreeningConditionBody,
    ScreeningConditionGroupBody,
    ScreeningCreateBody,
    ScreeningParseResponse,
    ScreeningPreviewEnvelopeResponse,
    ScreeningProgressResponse,
    ScreeningResultPageResponse,
    ScreeningResultResponse,
    ScreeningRetryBody,
    ScreeningRunPageResponse,
    ScreeningRunResponse,
    ScreeningSpecBody,
    ScreeningTemplateResponse,
    ScreeningTextParseBody,
    ScreeningValidationResponse,
    ScreeningWatchlistBody,
    ScreeningWatchlistResponse,
    UniverseSpecBody,
    UserScreeningPageResponse,
    UserScreeningResponse,
    UserScreeningRunBody,
    UserScreeningWriteBody,
)
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.scanners import ScanRun
from alphadesk_domain.screening import (
    ConditionCatalog,
    ConditionGroupOperator,
    RankingDirection,
    RankingRule,
    ScreeningCondition,
    ScreeningConditionGroup,
    ScreeningError,
    ScreeningSpec,
    ScreeningTemplateDefinition,
    UniverseSpec,
    screening_template_catalog,
)
from alphadesk_domain.user_screenings import UserScreeningStatus

router = APIRouter(tags=["research-screenings"])

STAGE_LABELS = {
    "QUEUED": "等待开始",
    "PLANNING": "正在分析数据需求",
    "CHECKING_COVERAGE": "正在检查本地数据",
    "BACKFILLING_MARKET_DATA": "正在补齐历史行情",
    "BACKFILLING_REFERENCE_DATA": "正在补齐交易状态",
    "VERIFYING_DATA": "正在检查数据质量",
    "PREPARING_FEATURES": "正在准备选股指标",
    "SCREENING": "正在执行全市场选股",
    "COMPLETED": "已完成",
    "PARTIAL_FAILED": "部分完成",
    "FAILED": "失败",
    "CANCELED": "已取消",
}


def catalog(request: Request) -> ConditionCatalog:
    return cast(ConditionCatalog, request.app.state.screening_condition_catalog)


def _domain_spec(body: ScreeningCreateBody, condition_catalog: ConditionCatalog) -> ScreeningSpec:
    nodes = list(body.conditions)
    if body.root_group is not None:
        nodes.extend(_condition_bodies(body.root_group))
    for item in nodes:
        definition = condition_catalog.get(item.condition_key)
        if item.condition_version is not None and item.condition_version != definition.version:
            raise ScreeningError(
                "SCREENING_CONDITION_VERSION_MISMATCH",
                f"{definition.display_name}的条件版本已更新，请重新解析或确认条件",
            )
    return ScreeningSpec(
        schema_version=body.schema_version,
        name=body.name,
        origin=body.origin,
        universe_spec=_domain_universe(body.universe_spec),
        as_of_date=body.as_of_date,
        timeframe=MarketTimeframe(body.timeframe),
        conditions=tuple(_domain_condition(item) for item in body.conditions),
        root_group=(None if body.root_group is None else _domain_group(body.root_group)),
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


def _condition_bodies(group: ScreeningConditionGroupBody) -> list[ScreeningConditionBody]:
    return [
        condition
        for child in group.children
        for condition in (
            _condition_bodies(child) if isinstance(child, ScreeningConditionGroupBody) else [child]
        )
    ]


def _domain_group(body: ScreeningConditionGroupBody) -> ScreeningConditionGroup:
    return ScreeningConditionGroup(
        operator=ConditionGroupOperator(body.operator),
        children=tuple(
            _domain_group(child)
            if isinstance(child, ScreeningConditionGroupBody)
            else _domain_condition(child)
            for child in body.children
        ),
    )


def _domain_ranking(body: RankingRuleBody) -> RankingRule:
    return RankingRule(field=body.field, direction=RankingDirection(body.direction))


def _run_response(run: ScanRun, *, replayed: bool = False) -> ScreeningRunResponse:
    preparation = run.execution_stats.get("data_preparation")
    plan = run.execution_stats.get("data_requirement_plan")
    stage = (
        str(preparation.get("stage", run.status.value))
        if isinstance(preparation, dict)
        else run.status.value
    )
    return ScreeningRunResponse(
        screening_id=run.id,
        name=str(run.screening_spec.get("name", run.scanner_key)),
        status=run.status.value,
        current_phase=stage,
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
        data_requirement_plan=plan if isinstance(plan, dict) else None,
        data_preparation=preparation if isinstance(preparation, dict) else None,
    )


@router.get(
    "/screening-conditions",
    response_model=list[ConditionDefinitionResponse],
)
@router.get(
    "/research/screening-conditions",
    response_model=list[ConditionDefinitionResponse],
)
async def list_screening_conditions(
    request: Request,
    query: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ConditionDefinitionResponse]:
    items = catalog(request).search(query=query, category=category)
    return [
        ConditionDefinitionResponse.model_validate(item.response_dict())
        for item in items[offset : offset + limit]
    ]


@router.get(
    "/screening-conditions/{condition_key}",
    response_model=ConditionDefinitionResponse,
)
@router.get(
    "/research/screening-conditions/{condition_key}",
    response_model=ConditionDefinitionResponse,
)
async def get_screening_condition(
    request: Request,
    condition_key: str,
) -> ConditionDefinitionResponse:
    try:
        return ConditionDefinitionResponse.model_validate(
            catalog(request).get(condition_key).response_dict()
        )
    except ScreeningError as exc:
        raise to_app_error(ApplicationError(exc.code, str(exc))) from exc


def _spec_service(request: Request) -> ScreeningSpecService:
    return ScreeningSpecService(
        uow_factory(request),
        catalog(request),
        ai_provider=request.app.state.ai_research_provider,
    )


def _template_enabled(
    item: ScreeningTemplateDefinition,
    condition_catalog: ConditionCatalog,
) -> bool:
    try:
        return bool(item.enabled) and all(
            condition_catalog.get(condition.condition_key).enabled
            for condition in item.spec.conditions
        )
    except ScreeningError:
        return False


@router.post(
    "/screening-specs/parse",
    response_model=ScreeningParseResponse,
)
async def parse_screening_spec(
    request: Request,
    body: ScreeningTextParseBody,
) -> ScreeningParseResponse:
    try:
        result = await _spec_service(request).parse(
            text=body.text,
            as_of_date=body.as_of_date,
            universe=(None if body.universe is None else _domain_universe(body.universe)),
            allow_ai_assistance=body.allow_ai_assistance,
        )
        return ScreeningParseResponse.model_validate(result)
    except ScreeningError as exc:
        raise to_app_error(ApplicationError(exc.code, str(exc))) from exc
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post(
    "/screening-specs/validate",
    response_model=ScreeningValidationResponse,
)
async def validate_screening_spec(
    request: Request,
    body: ScreeningSpecBody,
) -> ScreeningValidationResponse:
    try:
        result = await _spec_service(request).validate(body.screening_spec.model_dump(mode="json"))
        return ScreeningValidationResponse.model_validate(result)
    except ScreeningError as exc:
        raise to_app_error(ApplicationError(exc.code, str(exc))) from exc


@router.post(
    "/screening-specs/preview",
    response_model=ScreeningPreviewEnvelopeResponse,
)
async def preview_screening_spec(
    request: Request,
    body: ScreeningSpecBody,
) -> ScreeningPreviewEnvelopeResponse:
    try:
        result = await _spec_service(request).preview(body.screening_spec.model_dump(mode="json"))
        return ScreeningPreviewEnvelopeResponse.model_validate(result)
    except ScreeningError as exc:
        raise to_app_error(ApplicationError(exc.code, str(exc))) from exc


@router.get(
    "/screening-templates",
    response_model=list[ScreeningTemplateResponse],
)
async def list_screening_templates(request: Request) -> list[ScreeningTemplateResponse]:
    condition_catalog = catalog(request)
    return [
        ScreeningTemplateResponse(
            template_key=item.template_key,
            display_name=item.display_name,
            description=item.description,
            timeframe=item.timeframe,
            required_data=item.required_data,
            enabled=_template_enabled(item, condition_catalog),
            spec=item.spec.snapshot(condition_catalog),
        )
        for item in screening_template_catalog()
    ]


@router.get(
    "/screening-templates/{template_key}",
    response_model=ScreeningTemplateResponse,
)
async def get_screening_template(request: Request, template_key: str) -> ScreeningTemplateResponse:
    item = next(
        (value for value in screening_template_catalog() if value.template_key == template_key),
        None,
    )
    if item is None:
        raise to_app_error(ApplicationError("SCREENING_TEMPLATE_NOT_FOUND", "没有找到该模板"))
    return ScreeningTemplateResponse(
        template_key=item.template_key,
        display_name=item.display_name,
        description=item.description,
        timeframe=item.timeframe,
        required_data=item.required_data,
        enabled=_template_enabled(item, catalog(request)),
        spec=item.spec.snapshot(catalog(request)),
    )


def _user_service(request: Request) -> UserScreeningService:
    return UserScreeningService(
        uow_factory(request),
        catalog(request),
        source_code=request.app.state.settings.authoritative_market_source,
    )


@router.post(
    "/user-screenings",
    response_model=UserScreeningResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_screening(
    request: Request, body: UserScreeningWriteBody
) -> UserScreeningResponse:
    try:
        result = await _user_service(request).create(
            name=body.name,
            description=body.description,
            source_text=body.source_text,
            screening_spec=body.screening_spec.model_dump(mode="json"),
            origin=body.origin,
        )
        return UserScreeningResponse.model_validate(result)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/user-screenings", response_model=UserScreeningPageResponse)
async def list_user_screenings(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_archived: bool = False,
) -> UserScreeningPageResponse:
    return UserScreeningPageResponse.model_validate(
        await _user_service(request).list(
            page=page, page_size=page_size, include_archived=include_archived
        )
    )


@router.get("/user-screenings/{screening_id}", response_model=UserScreeningResponse)
async def get_user_screening(request: Request, screening_id: UUID) -> UserScreeningResponse:
    try:
        return UserScreeningResponse.model_validate(await _user_service(request).get(screening_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.put("/user-screenings/{screening_id}", response_model=UserScreeningResponse)
async def update_user_screening(
    request: Request, screening_id: UUID, body: UserScreeningWriteBody
) -> UserScreeningResponse:
    try:
        return UserScreeningResponse.model_validate(
            await _user_service(request).update(
                screening_id,
                name=body.name,
                description=body.description,
                source_text=body.source_text,
                screening_spec=body.screening_spec.model_dump(mode="json"),
                origin=body.origin,
            )
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/user-screenings/{screening_id}/clone", response_model=UserScreeningResponse)
async def clone_user_screening(request: Request, screening_id: UUID) -> UserScreeningResponse:
    try:
        return UserScreeningResponse.model_validate(
            await _user_service(request).clone(screening_id)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/user-screenings/{screening_id}/archive", response_model=UserScreeningResponse)
async def archive_user_screening(request: Request, screening_id: UUID) -> UserScreeningResponse:
    try:
        return UserScreeningResponse.model_validate(
            await _user_service(request).set_status(screening_id, UserScreeningStatus.ARCHIVED)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/user-screenings/{screening_id}/restore", response_model=UserScreeningResponse)
async def restore_user_screening(request: Request, screening_id: UUID) -> UserScreeningResponse:
    try:
        return UserScreeningResponse.model_validate(
            await _user_service(request).set_status(screening_id, UserScreeningStatus.ACTIVE)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post(
    "/user-screenings/{screening_id}/run",
    response_model=ScreeningRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_user_screening(
    request: Request, screening_id: UUID, body: UserScreeningRunBody
) -> ScreeningRunResponse:
    try:
        outcome = await _user_service(request).run(
            screening_id,
            as_of_date=body.as_of_date,
            correlation_id=request_correlation_id(request),
            idempotency_key=body.idempotency_key,
            use_existing_data_only=body.use_existing_data_only,
        )
        return _run_response(outcome.run, replayed=outcome.replayed)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


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
            _domain_spec(body, catalog(request)),
            correlation_id=request_correlation_id(request),
            idempotency_key=body.idempotency_key,
            use_existing_data_only=body.use_existing_data_only,
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
    as_of_from: date | None = None,
    as_of_to: date | None = None,
    plan_name: str | None = Query(default=None, max_length=128),
    source_type: Literal["TEMPLATE", "CUSTOM"] | None = Query(default=None),
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
    if as_of_from is not None:
        filtered = [item for item in filtered if item.as_of.date() >= as_of_from]
    if as_of_to is not None:
        filtered = [item for item in filtered if item.as_of.date() <= as_of_to]
    if plan_name:
        normalized_name = plan_name.strip().casefold()
        filtered = [
            item
            for item in filtered
            if normalized_name in str(item.screening_spec.get("name", "")).casefold()
        ]
    if source_type is not None:
        filtered = [
            item
            for item in filtered
            if (str(item.screening_spec.get("origin", "")) == "BUILTIN_TEMPLATE")
            is (source_type == "TEMPLATE")
        ]
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
    preparation = run.execution_stats.get("data_preparation", {})
    if not isinstance(preparation, dict):
        preparation = {}
    stage = str(preparation.get("stage", run.status.value))
    total_batches = max(0, int(preparation.get("queued_batch_count", 0)))
    pending_batches = await _pending_backfill_batches(request, screening_id)
    processed_batches = (
        max(0, total_batches - min(total_batches, pending_batches))
        if pending_batches is not None
        else 0
    )
    backfill_percent: int | None = None
    remaining_seconds: int | None = None
    if total_batches > 0 and pending_batches is not None:
        calculated = int(processed_batches / total_batches * 100)
        backfill_percent = (
            min(calculated, 99) if stage == "BACKFILLING_MARKET_DATA" else min(calculated, 100)
        )
        remaining_seconds = max(0, pending_batches * BACKFILL_SECONDS_PER_BATCH)
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
        current_stage=stage,
        stage_label=STAGE_LABELS.get(stage, stage),
        current_action=str(preparation.get("current_action", STAGE_LABELS.get(stage, stage))),
        downloading_count=int(preparation.get("downloading_count", 0)),
        provider_failed_count=int(preparation.get("provider_failed_count", 0)),
        quality_failed_count=int(preparation.get("quality_failed_count", 0)),
        not_applicable_count=int(preparation.get("not_applicable_count", 0)),
        listing_history_short_count=int(preparation.get("listing_history_short_count", 0)),
        currently_suspended_count=int(preparation.get("currently_suspended_count", 0)),
        stale_data_count=int(preparation.get("stale_data_count", 0)),
        data_gap_count=int(preparation.get("data_gap_count", 0)),
        calendar_mismatch_count=int(preparation.get("calendar_mismatch_count", 0)),
        calendar_mismatch_dates=[
            str(item)
            for item in preparation.get("calendar_mismatch_dates", [])
            if isinstance(item, str)
        ],
        excluded_count=run.excluded_instruments,
        backfill_total_batches=total_batches,
        backfill_pending_batches=pending_batches,
        backfill_processed_batches=processed_batches,
        backfill_progress_percent=backfill_percent,
        backfill_estimated_remaining_seconds=remaining_seconds,
    )


async def _pending_backfill_batches(
    request: Request,
    screening_id: UUID,
) -> int | None:
    """Count only queued MiniQMT batches that belong to this screening run."""

    client = getattr(request.app.state.redis, "client", None)
    if client is None:
        return None
    try:
        raw_items = await client.lrange(HISTORY_QUEUE_KEY, 0, -1)
    except (RedisError, ConnectionError, TimeoutError, OSError):
        return None
    pending = 0
    for raw in raw_items:
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            payload = json.loads(text)
        except (UnicodeDecodeError, TypeError, ValueError):
            continue
        if isinstance(payload, dict) and str(payload.get("scan_run_id")) == str(screening_id):
            pending += 1
    return pending


@router.post(
    "/research/screenings/{screening_id}/cancel",
    response_model=ScreeningRunResponse,
)
async def cancel_screening(request: Request, screening_id: UUID) -> ScreeningRunResponse:
    try:
        run = await ScreeningRunService(
            uow_factory(request),
            catalog(request),
            source_code=request.app.state.settings.authoritative_market_source,
        ).cancel(screening_id)
        return _run_response(run)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post(
    "/research/screenings/{screening_id}/retry-failed",
    response_model=ScreeningRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_failed_screening(
    request: Request,
    screening_id: UUID,
    body: ScreeningRetryBody,
) -> ScreeningRunResponse:
    try:
        outcome = await ScreeningRunService(
            uow_factory(request),
            catalog(request),
            source_code=request.app.state.settings.authoritative_market_source,
        ).retry_failed(
            screening_id,
            correlation_id=request_correlation_id(request),
            idempotency_key=body.idempotency_key,
        )
        return _run_response(outcome.run, replayed=outcome.replayed)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


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


@router.post(
    "/research/screenings/{screening_id}/add-to-watchlist",
    response_model=ScreeningWatchlistResponse,
)
async def add_screening_results_to_watchlist(
    request: Request,
    screening_id: UUID,
    body: ScreeningWatchlistBody,
) -> ScreeningWatchlistResponse:
    try:
        result = await ScreeningWatchlistService(
            uow_factory(request),
            item_limit=request.app.state.settings.watchlist_item_limit,
        ).add(
            scan_run_id=screening_id,
            instrument_ids=body.instrument_ids,
            watchlist_id=body.watchlist_id,
            new_watchlist_name=body.new_watchlist_name,
            realtime_monitor=body.realtime_monitor,
            correlation_id=request_correlation_id(request),
        )
        return ScreeningWatchlistResponse.model_validate(result)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
