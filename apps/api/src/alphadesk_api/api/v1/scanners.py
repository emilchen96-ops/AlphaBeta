"""SC01 scanner catalog, synchronous runs and immutable results."""

from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.scanners import (
    ScannerCatalogService,
    ScannerIntegrityService,
    ScannerQueryService,
    ScannerRunRequest,
    ScannerRunService,
    ScanResultDto,
)
from alphadesk_api.schemas.scanners import (
    ScannerCatalogResponse,
    ScannerIntegrityResponse,
    ScanResultListResponse,
    ScanResultResponse,
    ScanRunCreateBody,
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
        instrument_ids=list(run.instrument_ids),
        timeframe=run.timeframe.value,
        as_of=run.as_of,
        status=run.status.value,
        instruments_scanned=run.instruments_scanned,
        matches_found=run.matches_found,
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


@router.post("/scan-runs", response_model=ScanRunResponse, status_code=status.HTTP_201_CREATED)
async def create_scan_run(request: Request, body: ScanRunCreateBody) -> ScanRunResponse:
    try:
        try:
            timeframe = MarketTimeframe(body.timeframe)
        except ValueError as exc:
            raise ApplicationError(
                "SCANNER_TIMEFRAME_NOT_SUPPORTED", "timeframe is invalid"
            ) from exc
        outcome = await ScannerRunService(uow_factory(request), registry(request)).run(
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
async def get_scan_results(request: Request, scan_run_id: UUID) -> ScanResultListResponse:
    try:
        items = await ScannerQueryService(uow_factory(request)).results(scan_run_id)
        return ScanResultListResponse(
            items=[result_response(item) for item in items], total=len(items)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/scan-runs/{scan_run_id}/integrity", response_model=ScannerIntegrityResponse)
async def get_scan_integrity(request: Request, scan_run_id: UUID) -> ScannerIntegrityResponse:
    try:
        issues = await ScannerIntegrityService(uow_factory(request)).verify(scan_run_id)
        return ScannerIntegrityResponse(scan_run_id=scan_run_id, valid=not issues, issues=issues)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
