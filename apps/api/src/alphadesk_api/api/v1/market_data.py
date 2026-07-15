"""Read-only market-data query and source APIs."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from alphadesk_api.api.v1.market_common import to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.market_data import MarketDataQueryService
from alphadesk_api.schemas.market import (
    MarketBarResponse,
    MarketBarsResponse,
    MarketDataSourceResponse,
    MarketFreshnessResponse,
    MarketLatestItemResponse,
    MarketLatestResponse,
    MarketSyncRunResponse,
)
from alphadesk_domain.enums import AdjustmentType, MarketTimeframe
from alphadesk_domain.market import MarketBar, MarketDataFreshness

router = APIRouter(prefix="/market-data", tags=["market-data"])


def query_service(request: Request) -> MarketDataQueryService:
    return MarketDataQueryService(
        uow_factory(request),
        minute_stale_seconds=request.app.state.settings.market_minute_stale_seconds,
    )


def bar_response(bar: MarketBar, source_code: str) -> MarketBarResponse:
    return MarketBarResponse(
        instrument_id=bar.instrument_id,
        source_code=source_code,
        timeframe=bar.timeframe,
        adjustment_type=bar.adjustment_type,
        bar_time=bar.bar_time,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        amount=bar.amount,
        vwap=bar.vwap,
        received_at=bar.received_at,
        quality_status=bar.quality_status,
    )


def freshness_response(value: MarketDataFreshness) -> MarketFreshnessResponse:
    return MarketFreshnessResponse(
        source_code=value.source_code,
        freshness_status=value.status,
        latest_bar_time=value.latest_bar_time,
        latest_received_at=value.latest_received_at,
        calculated_at=value.calculated_at,
    )


@router.get("/bars", response_model=MarketBarsResponse)
async def get_bars(
    request: Request,
    instrument_id: UUID,
    timeframe: MarketTimeframe = MarketTimeframe.DAY_1,
    adjustment_type: AdjustmentType = AdjustmentType.NONE,
    source_code: str | None = Query(default=None, max_length=64),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=500, ge=1),
) -> MarketBarsResponse:
    maximum = request.app.state.settings.market_bar_query_limit
    if limit > maximum:
        raise to_app_error(
            ApplicationError("MARKET_DATA_LIMIT_EXCEEDED", f"最多返回 {maximum} 根K线")
        )
    if (start is not None and start.tzinfo is None) or (end is not None and end.tzinfo is None):
        raise to_app_error(ApplicationError("MARKET_DATA_INVALID_RANGE", "时间范围必须包含时区"))
    resolved_end = (end or datetime.now(UTC)).astimezone(UTC)
    resolved_start = (start or resolved_end - timedelta(days=730)).astimezone(UTC)
    if resolved_start > resolved_end:
        raise to_app_error(
            ApplicationError("MARKET_DATA_INVALID_RANGE", "开始时间不能晚于结束时间")
        )
    try:
        source, items, freshness = await query_service(request).bars(
            instrument_id=instrument_id,
            timeframe=timeframe,
            adjustment=adjustment_type,
            source_code=source_code,
            start=resolved_start,
            end=resolved_end,
            limit=limit,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return MarketBarsResponse(
        source_code=source.source_code,
        items=[bar_response(item, source.source_code) for item in items],
        freshness=freshness_response(freshness),
    )


@router.get("/latest", response_model=MarketLatestResponse)
async def get_latest(
    request: Request,
    instrument_ids: Annotated[list[UUID], Query(min_length=1, max_length=100)],
    timeframe: MarketTimeframe = MarketTimeframe.DAY_1,
    adjustment_type: AdjustmentType = AdjustmentType.NONE,
    source_code: str | None = Query(default=None, max_length=64),
) -> MarketLatestResponse:
    try:
        source, values = await query_service(request).latest(
            instrument_ids=instrument_ids,
            timeframe=timeframe,
            adjustment=adjustment_type,
            source_code=source_code,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return MarketLatestResponse(
        source_code=source.source_code,
        items=[
            MarketLatestItemResponse(
                bar=bar_response(bar, source.source_code),
                freshness=freshness_response(freshness),
            )
            for bar, freshness in values
        ],
    )


@router.get("/sources", response_model=list[MarketDataSourceResponse])
async def get_sources(request: Request) -> list[MarketDataSourceResponse]:
    values = await query_service(request).sources()
    return [
        MarketDataSourceResponse(
            id=value.id,
            source_code=value.source_code,
            name=value.name,
            status=value.status,
            priority=value.priority,
            supports_realtime=value.supports_realtime,
            supported_timeframes=value.supported_timeframes,
            updated_at=value.updated_at,
        )
        for value in values
    ]


@router.get("/sync-runs", response_model=list[MarketSyncRunResponse])
async def get_sync_runs(
    request: Request, limit: int = Query(default=20, ge=1, le=100)
) -> list[MarketSyncRunResponse]:
    values = await query_service(request).sync_runs(limit)
    return [MarketSyncRunResponse(**asdict(value)) for value in values]
