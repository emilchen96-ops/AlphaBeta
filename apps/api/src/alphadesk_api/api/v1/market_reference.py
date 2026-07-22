"""D02 bounded reference-data synchronization and read APIs."""

from dataclasses import asdict
from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from alphadesk_api.api.v1.market_common import to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.historical_market_data import InstrumentUniverseSyncService
from alphadesk_api.application.market_reference import (
    MarketReferenceProvider,
    MarketReferenceQueryService,
    ReferenceMarketDataSyncService,
)
from alphadesk_api.infrastructure.market_reference import FixtureMarketReferenceProvider
from alphadesk_api.schemas.market_reference import (
    AdjustmentFactorResponse,
    CalendarSessionResponse,
    LifecycleEventResponse,
    MarketReferenceStatusResponse,
    ReferenceSyncRequest,
    ReferenceSyncResponse,
    TradingStatusResponse,
)
from alphadesk_domain.entities import Instrument

router = APIRouter(prefix="/market-reference", tags=["market-reference"])


def _provider(request: Request, requested: str) -> tuple[MarketReferenceProvider, str]:
    if requested.lower() == "fixture":
        return FixtureMarketReferenceProvider(), "FIXTURE"
    if requested.lower() == "tushare":
        settings = request.app.state.settings
        if not settings.tushare_enabled or settings.tushare_token is None:
            raise ApplicationError(
                "MARKET_REFERENCE_PROVIDER_NOT_CONFIGURED", "Tushare Provider 未配置"
            )
        raise ApplicationError(
            "MARKET_REFERENCE_PROVIDER_NOT_CONFIGURED", "Tushare Adapter 本地联调未启用"
        )
    raise ApplicationError("MARKET_REFERENCE_PROVIDER_NOT_CONFIGURED", "未知参考数据 Provider")


async def _instruments(request: Request, payload: ReferenceSyncRequest) -> list[Instrument]:
    values = await InstrumentUniverseSyncService(uow_factory(request)).resolve_universe(
        universe="manual" if payload.instrument_ids else payload.universe,
        limit=payload.max_instruments,
        instrument_ids=payload.instrument_ids or None,
    )
    if not values:
        raise ApplicationError(
            "MARKET_REFERENCE_DATA_NOT_READY", "所选股票池没有可同步的 Instrument"
        )
    return values


def _range(payload: ReferenceSyncRequest) -> tuple[date, date]:
    end = payload.end or date.today()
    start = payload.start or end - timedelta(days=365)
    if start > end:
        raise ApplicationError("MARKET_REFERENCE_SYNC_FAILED", "开始日期不能晚于结束日期")
    if (end - start).days > 3660:
        raise ApplicationError("MARKET_REFERENCE_SYNC_FAILED", "单次同步范围最多十年")
    return start, end


def _sync_service(request: Request, provider_name: str) -> ReferenceMarketDataSyncService:
    provider, name = _provider(request, provider_name)
    return ReferenceMarketDataSyncService(uow_factory(request), provider, name)


@router.get("/status", response_model=MarketReferenceStatusResponse)
async def status(request: Request) -> MarketReferenceStatusResponse:
    value = await MarketReferenceQueryService(uow_factory(request)).status()
    return MarketReferenceStatusResponse(**asdict(value))


@router.post("/calendar/sync", response_model=ReferenceSyncResponse)
async def sync_calendar(request: Request, payload: ReferenceSyncRequest) -> ReferenceSyncResponse:
    try:
        start, end = _range(payload)
        value = await _sync_service(request, payload.provider).sync_calendar(
            start=start, end=end, exchanges=("SHSE", "SZSE"), dry_run=payload.dry_run
        )
        return ReferenceSyncResponse(**asdict(value))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/adjustments/sync", response_model=ReferenceSyncResponse)
async def sync_adjustments(
    request: Request, payload: ReferenceSyncRequest
) -> ReferenceSyncResponse:
    try:
        start, end = _range(payload)
        value = await _sync_service(request, payload.provider).sync_adjustments(
            instruments=await _instruments(request, payload),
            start=start,
            end=end,
            dry_run=payload.dry_run,
        )
        return ReferenceSyncResponse(**asdict(value))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/suspensions/sync", response_model=ReferenceSyncResponse)
async def sync_suspensions(
    request: Request, payload: ReferenceSyncRequest
) -> ReferenceSyncResponse:
    try:
        start, end = _range(payload)
        value = await _sync_service(request, payload.provider).sync_suspensions(
            instruments=await _instruments(request, payload),
            start=start,
            end=end,
            dry_run=payload.dry_run,
        )
        return ReferenceSyncResponse(**asdict(value))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/instrument-lifecycle/sync", response_model=ReferenceSyncResponse)
async def sync_lifecycle(request: Request, payload: ReferenceSyncRequest) -> ReferenceSyncResponse:
    try:
        value = await _sync_service(request, payload.provider).sync_lifecycle(
            instruments=await _instruments(request, payload), dry_run=payload.dry_run
        )
        return ReferenceSyncResponse(**asdict(value))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/calendar", response_model=list[CalendarSessionResponse])
async def calendar(
    request: Request,
    exchange: str | None = Query(default=None, max_length=8),
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[CalendarSessionResponse]:
    values = await MarketReferenceQueryService(uow_factory(request)).calendar(
        exchange=exchange, start=start, end=end, limit=limit
    )
    return [CalendarSessionResponse(**asdict(item)) for item in values]


@router.get("/adjustments", response_model=list[AdjustmentFactorResponse])
async def adjustments(
    request: Request,
    instrument_ids: Annotated[list[UUID] | None, Query(max_length=100)] = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[AdjustmentFactorResponse]:
    values = await MarketReferenceQueryService(uow_factory(request)).adjustments(
        instrument_ids=instrument_ids, start=start, end=end, limit=limit
    )
    return [AdjustmentFactorResponse(**asdict(item)) for item in values]


@router.get("/suspensions", response_model=list[TradingStatusResponse])
async def suspensions(
    request: Request,
    instrument_ids: Annotated[list[UUID] | None, Query(max_length=100)] = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[TradingStatusResponse]:
    values = await MarketReferenceQueryService(uow_factory(request)).suspensions(
        instrument_ids=instrument_ids, start=start, end=end, limit=limit
    )
    return [TradingStatusResponse(**asdict(item)) for item in values]


@router.get("/instrument-lifecycle", response_model=list[LifecycleEventResponse])
async def lifecycle(
    request: Request,
    instrument_ids: Annotated[list[UUID] | None, Query(max_length=100)] = None,
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[LifecycleEventResponse]:
    values = await MarketReferenceQueryService(uow_factory(request)).lifecycle(
        instrument_ids=instrument_ids, limit=limit
    )
    return [LifecycleEventResponse(**asdict(item)) for item in values]
