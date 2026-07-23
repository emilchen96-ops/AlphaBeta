"""SC01 scanner catalog, synchronous runs and immutable results."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.scanners import (
    FullMarketScannerService,
    FullMarketScanRequest,
    ScannerCatalogService,
    ScannerIntegrityService,
    ScannerQueryService,
    ScannerRunRequest,
    ScannerRunService,
    ScannerUniverseFilters,
    ScanResultDto,
)
from alphadesk_api.schemas.scanners import (
    ScanDataPreparationResponse,
    ScannerCatalogResponse,
    ScannerIntegrityResponse,
    ScannerSessionDefaultResponse,
    ScanResultListResponse,
    ScanResultResponse,
    ScanRunCreateBody,
    ScanRunMemberListResponse,
    ScanRunMemberResponse,
    ScanRunPageResponse,
    ScanRunResponse,
)
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.scanners import ScannerRegistry, ScanRun

router = APIRouter(tags=["market-scanners"])


def registry(request: Request) -> ScannerRegistry:
    return cast(ScannerRegistry, request.app.state.scanner_registry)


def run_response(run: ScanRun, *, replayed: bool = False) -> ScanRunResponse:
    return ScanRunResponse(
        scan_run_id=run.id,
        scanner_key=run.scanner_key,
        scanner_version=run.scanner_version,
        parameters=run.parameters,
        universe_type=run.universe_type,
        # Full-market membership is exposed through the auditable members
        # endpoint; avoid returning thousands of internal UUIDs in every run.
        instrument_ids=(
            [] if run.universe_type == "ALL_ACTIVE_A_SHARES" else list(run.instrument_ids)
        ),
        universe_filters=run.universe_filters,
        source_code=run.source_code,
        timeframe=run.timeframe.value,
        as_of=run.as_of,
        status=run.status.value,
        current_phase=run.status.value,
        progress_percent=run.progress_percent,
        total_instruments=run.total_instruments,
        excluded_instruments=run.excluded_instruments,
        data_ready_instruments=run.data_ready_instruments,
        backfill_requested=run.backfill_requested,
        backfill_failed=run.backfill_failed,
        insufficient_history=run.insufficient_history,
        instruments_scanned=run.instruments_scanned,
        matches_found=run.matches_found,
        failed_instruments=run.failed_instruments,
        cancel_requested=run.cancel_requested,
        started_at=run.started_at,
        completed_at=run.completed_at,
        failed_at=run.failed_at,
        error=(
            None
            if run.error_code is None
            else {"code": run.error_code, "message": run.error_message or "scan failed"}
        ),
        correlation_id=run.correlation_id,
        created_at=run.created_at,
        replayed=replayed,
        capabilities={
            "creates_signals": False,
            "creates_orders": False,
            "uses_risk": False,
            "uses_broker": False,
            "modifies_portfolio": False,
            "is_realtime": False,
        },
        price_adjustment_mode=run.price_adjustment_mode,
    )


def result_response(item: ScanResultDto) -> ScanResultResponse:
    result = item.result
    return ScanResultResponse(
        scan_result_id=result.id,
        scan_run_id=result.scan_run_id,
        instrument_id=result.instrument_id,
        instrument={
            "symbol": item.symbol,
            "exchange": item.exchange,
            "name": item.instrument_name,
        },
        rank=result.rank,
        score=str(result.score),
        matched_at=result.matched_at,
        reference_price=str(result.reference_price),
        reason_code=result.reason_code,
        reason=result.reason,
        metrics=result.metrics,
        schema_version=result.schema_version,
        created_at=result.created_at,
    )


@router.get("/scanners/catalog", response_model=list[ScannerCatalogResponse])
async def scanner_catalog(request: Request) -> list[ScannerCatalogResponse]:
    return [
        ScannerCatalogResponse.model_validate(item)
        for item in ScannerCatalogService(registry(request)).list()
    ]


@router.get("/scanners/session-default", response_model=ScannerSessionDefaultResponse)
async def scanner_session_default(request: Request) -> ScannerSessionDefaultResponse:
    try:
        value = await FullMarketScannerService(
            uow_factory(request), registry(request)
        ).latest_completed_scan_date()
        return ScannerSessionDefaultResponse(scan_date=value)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/scan-runs", response_model=ScanRunResponse, status_code=status.HTTP_201_CREATED)
async def create_scan_run(request: Request, body: ScanRunCreateBody) -> ScanRunResponse:
    try:
        # Existing SC01 clients identify a custom-universe synchronous scan by
        # providing both instrument_ids and as_of.  Keep that sealed contract
        # working even though SC01-R now defaults new requests to all A shares.
        is_legacy_custom_request = bool(body.instrument_ids) and body.as_of is not None
        if not is_legacy_custom_request and body.universe_type == "ALL_ACTIVE_A_SHARES":
            service = FullMarketScannerService(uow_factory(request), registry(request))
            scan_date = body.scan_date or await service.latest_completed_scan_date()
            outcome = await service.enqueue(
                FullMarketScanRequest(
                    scanner_key=body.scanner_key,
                    parameters=body.parameters,
                    scan_date=scan_date,
                    filters=ScannerUniverseFilters(
                        **body.universe_filters.model_dump(mode="python")
                    ),
                    correlation_id=request_correlation_id(request),
                    idempotency_key=body.idempotency_key,
                )
            )
            return run_response(outcome.run, replayed=outcome.replayed)
        if not is_legacy_custom_request and body.universe_type not in {
            "CUSTOM_INSTRUMENTS",
            "INSTRUMENTS",
        }:
            raise ApplicationError("SCANNER_INVALID_UNIVERSE", "扫描范围类型无效")
        if not body.instrument_ids or body.as_of is None or body.idempotency_key is None:
            raise ApplicationError(
                "SCANNER_INVALID_UNIVERSE",
                "兼容的自定义股票扫描需要股票列表、截止时间和幂等键",
            )
        try:
            timeframe = MarketTimeframe(body.timeframe)
        except ValueError as exc:
            raise ApplicationError(
                "SCANNER_TIMEFRAME_NOT_SUPPORTED", "timeframe is invalid"
            ) from exc
        settings = request.app.state.settings
        outcome = await ScannerRunService(
            uow_factory(request),
            registry(request),
            authoritative_source_code=(
                None if settings.environment == "test" else settings.authoritative_market_source
            ),
        ).run(
            ScannerRunRequest(
                scanner_key=body.scanner_key,
                parameters=body.parameters,
                instrument_ids=tuple(body.instrument_ids),
                timeframe=timeframe,
                as_of=body.as_of,
                idempotency_key=body.idempotency_key,
                correlation_id=request_correlation_id(request),
                price_adjustment_mode=body.price_adjustment_mode,
            )
        )
        return run_response(outcome.run, replayed=outcome.replayed)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/scan-runs", response_model=ScanRunPageResponse)
async def list_scan_runs(
    request: Request,
    scanner_key: str | None = None,
    run_status: Annotated[str | None, Query(alias="status")] = None,
    instrument_id: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ScanRunPageResponse:
    items, total = await ScannerQueryService(uow_factory(request)).list_runs(
        scanner_key=scanner_key,
        status=run_status,
        instrument_id=instrument_id,
        created_from=created_from,
        created_to=created_to,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return ScanRunPageResponse(
        items=[run_response(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/scan-runs/{scan_run_id}", response_model=ScanRunResponse)
async def get_scan_run(request: Request, scan_run_id: UUID) -> ScanRunResponse:
    item = await ScannerQueryService(uow_factory(request)).get(scan_run_id)
    if item is None:
        raise to_app_error(ApplicationError("SCAN_RUN_NOT_FOUND", "scan run does not exist"))
    return run_response(item)


@router.get("/scan-runs/{scan_run_id}/results", response_model=ScanResultListResponse)
async def get_scan_results(
    request: Request,
    scan_run_id: UUID,
    instrument_id: UUID | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ScanResultListResponse:
    try:
        items = await ScannerQueryService(uow_factory(request)).results(scan_run_id)
        if instrument_id is not None:
            items = [item for item in items if item.result.instrument_id == instrument_id]
        if keyword:
            normalized = keyword.strip().casefold()
            items = [
                item
                for item in items
                if normalized in item.symbol.casefold()
                or normalized in item.instrument_name.casefold()
            ]
        total = len(items)
        items = items[(page - 1) * page_size : page * page_size]
        return ScanResultListResponse(
            items=[result_response(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get(
    "/scan-runs/{scan_run_id}/results/{scan_result_id}",
    response_model=ScanResultResponse,
)
async def get_scan_result(
    request: Request, scan_run_id: UUID, scan_result_id: UUID
) -> ScanResultResponse:
    try:
        item = await ScannerQueryService(uow_factory(request)).result(scan_run_id, scan_result_id)
        return result_response(item)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get(
    "/scan-runs/{scan_run_id}/members",
    response_model=ScanRunMemberListResponse,
)
async def get_scan_members(
    request: Request,
    scan_run_id: UUID,
    member_status: Annotated[str | None, Query(alias="status")] = None,
) -> ScanRunMemberListResponse:
    try:
        items, summary = await ScannerQueryService(uow_factory(request)).members(
            scan_run_id, status=member_status
        )
        return ScanRunMemberListResponse(
            items=[
                ScanRunMemberResponse(
                    instrument_id=item.instrument_id,
                    symbol=item.symbol,
                    exchange=item.exchange,
                    instrument_name=item.instrument_name,
                    status=item.status.value,
                    reason_code=item.reason_code,
                    reason=item.reason,
                    bars_available=item.bars_available,
                    required_bars=item.required_bars,
                )
                for item in items
            ],
            summary=summary,
            total=sum(summary.values()),
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get(
    "/scan-runs/{scan_run_id}/data-preparation",
    response_model=ScanDataPreparationResponse,
)
async def get_scan_data_preparation(
    request: Request, scan_run_id: UUID
) -> ScanDataPreparationResponse:
    try:
        service = ScannerQueryService(uow_factory(request))
        run = await service.get(scan_run_id)
        if run is None:
            raise ApplicationError("SCAN_RUN_NOT_FOUND", "扫描任务不存在")
        _, summary = await service.members(scan_run_id)
        return ScanDataPreparationResponse(
            scan_run_id=run.id,
            status=run.status.value,
            data_source=run.source_code,
            required_instruments=max(run.total_instruments - run.excluded_instruments, 0),
            ready_instruments=run.data_ready_instruments,
            backfill_requested=run.backfill_requested,
            backfill_failed=run.backfill_failed,
            insufficient_history=run.insufficient_history,
            member_summary=summary,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/scan-runs/{scan_run_id}/cancel", response_model=ScanRunResponse)
async def cancel_scan_run(request: Request, scan_run_id: UUID) -> ScanRunResponse:
    try:
        run = await ScannerQueryService(uow_factory(request)).cancel(scan_run_id)
        return run_response(run)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/scan-runs/{scan_run_id}/integrity", response_model=ScannerIntegrityResponse)
async def get_scan_integrity(request: Request, scan_run_id: UUID) -> ScannerIntegrityResponse:
    try:
        issues = await ScannerIntegrityService(uow_factory(request)).verify(scan_run_id)
        return ScannerIntegrityResponse(scan_run_id=scan_run_id, valid=not issues, issues=issues)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
