"""Read-only market-data query and source APIs."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from redis.asyncio import Redis

from alphadesk_api.api.v1.market_common import (
    request_correlation_id,
    to_app_error,
    uow_factory,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.historical_market_data import InstrumentUniverseSyncService
from alphadesk_api.application.market_data import MarketDataQueryService
from alphadesk_api.application.market_data_operations import (
    DailyMarketDataUpdateService,
    MarketDataQualityIntegrityService,
    MarketDataQualityQueryService,
    MarketDataQualityService,
    MarketDataReadinessService,
)
from alphadesk_api.application.market_reference import AdjustedHistoricalMarketDataService
from alphadesk_api.infrastructure.free_market_cache import (
    HEARTBEAT_KEY,
    STATUS_KEY,
    SUBSCRIPTIONS_KEY,
    QuoteCache,
    read_json,
)
from alphadesk_api.infrastructure.market_data import BaoStockHistoricalMarketDataAdapter
from alphadesk_api.schemas.market import (
    DailyUpdateRequest,
    DailyUpdateResponse,
    MarketBarResponse,
    MarketBarsResponse,
    MarketDataOverviewResponse,
    MarketDataQualityIssueResponse,
    MarketDataQualityRunResponse,
    MarketDataSourceResponse,
    MarketFreshnessResponse,
    MarketLatestItemResponse,
    MarketLatestResponse,
    MarketSyncRunResponse,
    QualityRunDetailResponse,
    QualityRunPageResponse,
    QualityRunRequest,
    ReadinessCapabilityResponse,
    UniverseCoverageResponse,
)
from alphadesk_api.schemas.realtime_market import (
    LatestQuotesResponse,
    QuoteResponse,
    RealtimeStatusResponse,
    SubscriptionSummaryResponse,
)
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataIssueSeverity,
    MarketTimeframe,
    QuoteFreshnessStatus,
)
from alphadesk_domain.market import MarketBar, MarketDataFreshness
from alphadesk_domain.market_reference import AdjustedBar, PriceAdjustmentMode

router = APIRouter(prefix="/market-data", tags=["market-data"])


def query_service(request: Request) -> MarketDataQueryService:
    return MarketDataQueryService(
        uow_factory(request),
        minute_stale_seconds=request.app.state.settings.market_minute_stale_seconds,
    )


async def _operations_instruments(
    request: Request,
    *,
    universe_key: str,
    max_instruments: int | None,
    instrument_ids: list[UUID] | None = None,
) -> list[Instrument]:
    settings = request.app.state.settings
    limit = max_instruments or settings.market_backfill_max_instruments
    if limit > settings.market_backfill_max_instruments:
        raise ApplicationError(
            "MARKET_DATA_TOO_MANY_INSTRUMENTS",
            f"单次操作最多 {settings.market_backfill_max_instruments} 个标的",
        )
    return await InstrumentUniverseSyncService(uow_factory(request)).resolve_universe(
        universe="manual" if instrument_ids else universe_key,
        limit=limit,
        instrument_ids=instrument_ids,
    )


def _readiness_service(request: Request) -> MarketDataReadinessService:
    return MarketDataReadinessService(
        uow_factory(request),
        backtest_minimum_bars=request.app.state.settings.market_data_backtest_minimum_bars,
    )


def bar_response(
    bar: MarketBar, source_code: str, adjusted: AdjustedBar | None = None
) -> MarketBarResponse:
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
        adjustment_mode=(PriceAdjustmentMode.RAW if adjusted is None else adjusted.adjustment_mode),
        factor=None if adjusted is None else adjusted.factor,
        reference_factor=None if adjusted is None else adjusted.reference_factor,
        raw_bar_id=bar.id if adjusted is None else adjusted.raw_bar_id,
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
    adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW,
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
        if adjustment_mode is PriceAdjustmentMode.QFQ and (
            timeframe is not MarketTimeframe.DAY_1 or adjustment_type is not AdjustmentType.NONE
        ):
            raise ApplicationError(
                "MARKET_ADJUSTMENT_MODE_NOT_SUPPORTED", "QFQ 仅支持原始 DAY_1 历史行情"
            )
        source, items, freshness = await query_service(request).bars(
            instrument_id=instrument_id,
            timeframe=timeframe,
            adjustment=adjustment_type,
            source_code=source_code,
            start=resolved_start,
            end=resolved_end,
            limit=limit,
        )
        adjusted_items = await AdjustedHistoricalMarketDataService(
            uow_factory(request)
        ).adjust_existing(items, adjustment_mode)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return MarketBarsResponse(
        source_code=source.source_code,
        items=[
            bar_response(adjusted.as_market_bar(), source.source_code, adjusted)
            for adjusted in adjusted_items
        ],
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
            provider_tier=value.provider_tier,
            supports_quotes=value.supports_quotes,
            supports_recent_minute_bars=value.supports_recent_minute_bars,
            last_health_check_at=value.last_health_check_at,
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


@router.get("/sync-runs/{run_id}", response_model=MarketSyncRunResponse)
async def get_sync_run(request: Request, run_id: UUID) -> MarketSyncRunResponse:
    try:
        value = await query_service(request).sync_run(run_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return MarketSyncRunResponse(**asdict(value))


@router.post(
    "/daily-updates",
    response_model=DailyUpdateResponse,
    summary="Synchronously update bounded historical daily bars; this may take time",
)
async def create_daily_update(request: Request, payload: DailyUpdateRequest) -> DailyUpdateResponse:
    try:
        instruments = await _operations_instruments(
            request,
            universe_key=payload.universe_key,
            max_instruments=payload.max_instruments,
            instrument_ids=payload.instrument_ids or None,
        )
        factory = getattr(request.app.state, "historical_market_adapter_factory", None)
        adapter = factory() if callable(factory) else BaoStockHistoricalMarketDataAdapter()
        settings = request.app.state.settings
        value = await DailyMarketDataUpdateService(
            uow_factory(request),
            default_start_date=settings.market_daily_default_start_date,
            max_instruments=settings.market_backfill_max_instruments,
            batch_size=settings.market_backfill_batch_size,
            max_retries=settings.market_backfill_max_retries,
            request_interval_seconds=settings.market_backfill_request_interval_seconds,
            future_tolerance_seconds=settings.market_future_tolerance_seconds,
        ).update(
            adapter=adapter,
            instruments=instruments,
            universe_key=payload.universe_key,
            target_date=payload.target_date,
            continue_on_error=payload.continue_on_error,
            dry_run=payload.dry_run,
            correlation_id=request_correlation_id(request),
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return DailyUpdateResponse(**asdict(value))


@router.post("/quality-runs", response_model=QualityRunDetailResponse)
async def create_quality_run(
    request: Request, payload: QualityRunRequest
) -> QualityRunDetailResponse:
    if (
        payload.range_start is not None
        and payload.range_end is not None
        and payload.range_start > payload.range_end
    ):
        raise to_app_error(
            ApplicationError("MARKET_DATA_INVALID_RANGE", "质量检查开始时间不能晚于结束时间")
        )
    if any(
        value is not None and value.tzinfo is None
        for value in (payload.range_start, payload.range_end)
    ):
        raise to_app_error(
            ApplicationError("MARKET_DATA_INVALID_RANGE", "质量检查时间必须包含时区")
        )
    try:
        instruments = await _operations_instruments(
            request,
            universe_key=payload.universe_key,
            max_instruments=payload.max_instruments,
        )
        settings = request.app.state.settings
        result = await MarketDataQualityService(
            uow_factory(request),
            stale_calendar_days=settings.market_data_stale_calendar_days,
            minimum_bars=settings.market_data_backtest_minimum_bars,
        ).verify(
            instruments=instruments,
            universe_key=payload.universe_key,
            provider=payload.provider,
            correlation_id=request_correlation_id(request),
            range_start=payload.range_start,
            range_end=payload.range_end,
        )
        mismatches = await MarketDataQualityIntegrityService(uow_factory(request)).verify(
            result.run.id
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return QualityRunDetailResponse(
        run=MarketDataQualityRunResponse(**asdict(result.run)),
        issues=[MarketDataQualityIssueResponse(**asdict(item)) for item in result.issues],
        issue_page=1,
        issue_page_size=max(1, len(result.issues)),
        issue_total=len(result.issues),
        integrity_mismatches=mismatches,
    )


@router.get("/quality-runs", response_model=QualityRunPageResponse)
async def get_quality_runs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> QualityRunPageResponse:
    values, total = await MarketDataQualityQueryService(uow_factory(request)).list_runs(
        page=page, page_size=page_size
    )
    return QualityRunPageResponse(
        items=[MarketDataQualityRunResponse(**asdict(item)) for item in values],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/quality-runs/{run_id}", response_model=QualityRunDetailResponse)
async def get_quality_run(
    request: Request,
    run_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    severity: MarketDataIssueSeverity | None = None,
    issue_type: str | None = Query(default=None, max_length=64),
    instrument_id: UUID | None = None,
) -> QualityRunDetailResponse:
    service = MarketDataQualityQueryService(uow_factory(request))
    try:
        run = await service.run(run_id)
        issues, total = await service.issues(
            run_id,
            page=page,
            page_size=page_size,
            severity=severity,
            issue_type=issue_type,
            instrument_id=instrument_id,
        )
        mismatches = await MarketDataQualityIntegrityService(uow_factory(request)).verify(run_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return QualityRunDetailResponse(
        run=MarketDataQualityRunResponse(**asdict(run)),
        issues=[MarketDataQualityIssueResponse(**asdict(item)) for item in issues],
        issue_page=page,
        issue_page_size=page_size,
        issue_total=total,
        integrity_mismatches=mismatches,
    )


@router.get("/coverage", response_model=UniverseCoverageResponse)
async def get_coverage(
    request: Request,
    universe_key: str = Query(default="research", max_length=64),
    provider: str = Query(default="baostock", max_length=64),
    max_instruments: int | None = Query(default=None, ge=1, le=500),
) -> UniverseCoverageResponse:
    try:
        instruments = await _operations_instruments(
            request, universe_key=universe_key, max_instruments=max_instruments
        )
        value = await _readiness_service(request).coverage(
            instruments=instruments, universe_key=universe_key, provider=provider
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return UniverseCoverageResponse(**asdict(value))


@router.get("/readiness", response_model=list[ReadinessCapabilityResponse])
async def get_readiness(
    request: Request,
    universe_key: str = Query(default="research", max_length=64),
    provider: str = Query(default="baostock", max_length=64),
    max_instruments: int | None = Query(default=None, ge=1, le=500),
) -> list[ReadinessCapabilityResponse]:
    try:
        instruments = await _operations_instruments(
            request, universe_key=universe_key, max_instruments=max_instruments
        )
        values = await _readiness_service(request).readiness(
            instruments=instruments, provider=provider
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return [ReadinessCapabilityResponse(**asdict(item)) for item in values]


@router.get("/overview", response_model=MarketDataOverviewResponse)
async def get_market_data_overview(
    request: Request,
    universe_key: str = Query(default="research", max_length=64),
    provider: str = Query(default="baostock", max_length=64),
    max_instruments: int | None = Query(default=None, ge=1, le=500),
) -> MarketDataOverviewResponse:
    try:
        instruments = await _operations_instruments(
            request, universe_key=universe_key, max_instruments=max_instruments
        )
        value = await _readiness_service(request).overview(
            instruments=instruments, universe_key=universe_key, provider=provider
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return MarketDataOverviewResponse(**asdict(value))


def _redis_client(request: Request) -> Redis:
    client = getattr(request.app.state.redis, "client", None)
    if client is None:
        raise to_app_error(ApplicationError("REALTIME_CACHE_UNAVAILABLE", "实时行情缓存不可用"))
    return cast(Redis, client)


@router.get("/quotes/latest", response_model=LatestQuotesResponse)
async def get_latest_quotes(
    request: Request,
    instrument_ids: Annotated[list[UUID], Query(min_length=1, max_length=100)],
) -> LatestQuotesResponse:
    now = datetime.now(UTC)
    snapshots = await QuoteCache(
        _redis_client(request), request.app.state.settings.free_market_quote_ttl_seconds
    ).get_many(instrument_ids)
    found = {item.quote.instrument_id for item in snapshots}
    items = []
    for snapshot in snapshots:
        quote = snapshot.quote
        age = max(0, int((now - quote.received_at).total_seconds()))
        freshness = (
            QuoteFreshnessStatus.FRESH
            if age <= request.app.state.settings.free_market_stale_seconds
            else QuoteFreshnessStatus.STALE
        )
        items.append(
            QuoteResponse(
                **asdict(quote),
                revision=snapshot.revision.revision,
                freshness=freshness,
                age_seconds=age,
            )
        )
    return LatestQuotesResponse(
        items=items,
        missing_instrument_ids=[item for item in instrument_ids if item not in found],
        calculated_at=now,
    )


@router.get("/realtime/status", response_model=RealtimeStatusResponse)
async def realtime_status(request: Request) -> RealtimeStatusResponse:
    client = _redis_client(request)
    status_value = await read_json(client, STATUS_KEY) or {
        "enabled": request.app.state.settings.free_market_data_enabled,
        "state": "NOT_STARTED",
    }
    status_value["worker_heartbeat"] = await read_json(client, HEARTBEAT_KEY)
    return RealtimeStatusResponse(**status_value)


@router.get("/realtime/subscriptions", response_model=SubscriptionSummaryResponse)
async def realtime_subscriptions(request: Request) -> SubscriptionSummaryResponse:
    return SubscriptionSummaryResponse(
        **((await read_json(_redis_client(request), SUBSCRIPTIONS_KEY)) or {})
    )
