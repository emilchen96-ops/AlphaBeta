"""Bounded local D03 intraday HTTP API."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.intraday import (
    IntradayAggregationService,
    IntradayMarketDataImportService,
    IntradayOverviewService,
    IntradayQualityService,
    IntradayQueryService,
    ensure_fixture_catalog,
    fixture_rows,
)
from alphadesk_api.infrastructure.intraday_provider import (
    FixtureIntradayMarketDataProvider,
)
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketSyncStatus,
    MarketTimeframe,
    SyncTriggerType,
)
from alphadesk_domain.intraday import INTRADAY_TIMEFRAMES, IntradayConflictPolicy
from alphadesk_domain.market import MarketSyncRun
from alphadesk_domain.market_reference import PriceAdjustmentMode

router = APIRouter(prefix="/intraday", tags=["intraday"])


class FixtureImportRequest(BaseModel):
    provider: Literal["D03_FIXTURE"] = "D03_FIXTURE"
    source_timezone: str = "Asia/Shanghai"
    target_timeframes: list[MarketTimeframe] = Field(
        default_factory=lambda: list(INTRADAY_TIMEFRAMES[1:]), max_length=4
    )
    conflict_policy: IntradayConflictPolicy = IntradayConflictPolicy.KEEP_EXISTING
    continue_on_error: bool = True
    dry_run: bool = False


class AggregationRequest(BaseModel):
    instrument_id: UUID
    source_code: str = Field(default="MINIQMT", min_length=1, max_length=64)
    start_at: datetime
    end_at: datetime
    targets: list[MarketTimeframe] = Field(min_length=1, max_length=4)
    dry_run: bool = False


class QualityRequest(BaseModel):
    instrument_id: UUID
    source_code: str = Field(default="MINIQMT", min_length=1, max_length=64)
    timeframe: MarketTimeframe = MarketTimeframe.MINUTE_1
    start_at: datetime
    end_at: datetime


def serializable(value: object) -> object:
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {key: serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    return value


def run_dict(run: MarketSyncRun) -> dict[str, object]:
    return serializable(asdict(run))  # type: ignore[return-value]


@router.get("/providers")
async def providers(request: Request) -> dict[str, object]:
    enabled = request.app.state.settings.miniqmt_market_data_enabled
    return {
        "items": [
            {
                "provider_key": "MINIQMT",
                "health": "AVAILABLE" if enabled else "DISABLED",
                "supported_timeframes": [item.value for item in INTRADAY_TIMEFRAMES],
                "input_types": ["miniqmt"],
                "message": (
                    "MiniQMT 是唯一正式分钟行情来源"
                    if enabled
                    else "请启动并配置 MiniQMT 只读行情代理"
                ),
            }
        ],
        "limits": {
            "http_upload": False,
            "timestamp_semantics": "BAR_START",
            "authoritative_adjustment": "RAW",
        },
    }


@router.post("/imports")
async def create_import(request: Request, payload: FixtureImportRequest) -> dict[str, object]:
    try:
        settings = request.app.state.settings
        if settings.environment != "test" and not settings.allow_test_market_data:
            raise ApplicationError(
                "TEST_MARKET_DATA_DISABLED",
                "正式环境已禁用测试分钟数据导入",
            )
        if not payload.dry_run:
            await ensure_fixture_catalog(uow_factory(request))
        result = await IntradayMarketDataImportService(
            uow_factory(request), batch_size=request.app.state.settings.intraday_import_batch_size
        ).run(
            FixtureIntradayMarketDataProvider(fixture_rows()),
            source_code="D03_FIXTURE",
            source_timezone=payload.source_timezone,
            target_timeframes=tuple(payload.target_timeframes),
            conflict_policy=payload.conflict_policy,
            continue_on_error=payload.continue_on_error,
            dry_run=payload.dry_run,
            correlation_id=request_correlation_id(request),
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return serializable(asdict(result))  # type: ignore[return-value]


@router.get("/imports")
async def imports(
    request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 25
) -> dict[str, object]:
    async with uow_factory(request)() as uow:
        runs = await uow.market_sync_runs.list_recent(limit * 4)
    values = [item for item in runs if item.metadata.get("operation_type") == "INTRADAY_IMPORT"]
    return {"items": [run_dict(item) for item in values[:limit]]}


@router.get("/imports/{run_id}")
async def import_detail(request: Request, run_id: UUID) -> dict[str, object]:
    async with uow_factory(request)() as uow:
        run = await uow.market_sync_runs.get_by_id(run_id)
    if run is None or run.metadata.get("operation_type") != "INTRADAY_IMPORT":
        raise to_app_error(ApplicationError("INTRADAY_IMPORT_FAILED", "分钟导入运行不存在"))
    return run_dict(run)


@router.post("/aggregations")
async def aggregate(request: Request, payload: AggregationRequest) -> dict[str, object]:
    invalid = [item for item in payload.targets if item not in INTRADAY_TIMEFRAMES[1:]]
    if invalid:
        raise to_app_error(
            ApplicationError("INTRADAY_TIMEFRAME_NOT_SUPPORTED", "目标周期必须是5/15/30/60分钟")
        )
    async with uow_factory(request)() as uow:
        source = await uow.market_data_sources.get_by_code(payload.source_code)
    if source is None:
        raise to_app_error(ApplicationError("INTRADAY_PROVIDER_NOT_AVAILABLE", "分钟行情源不存在"))
    run = MarketSyncRun(
        source_id=source.id,
        trigger_type=SyncTriggerType.MANUAL,
        status=MarketSyncStatus.RUNNING,
        timeframe=MarketTimeframe.MINUTE_1,
        adjustment_type=AdjustmentType.NONE,
        requested_symbols=(str(payload.instrument_id),),
        requested_start=payload.start_at,
        requested_end=payload.end_at,
        started_at=datetime.now(UTC),
        correlation_id=request_correlation_id(request),
        metadata={
            "operation_type": "INTRADAY_AGGREGATION",
            "targets": [item.value for item in payload.targets],
            "aggregation_version": "D03_SESSION_V1",
            "window_policy": "STRICT_COMPLETE_WINDOW",
            "dry_run": payload.dry_run,
        },
    )
    async with uow_factory(request)() as uow:
        await uow.market_sync_runs.add(run)
        await uow.commit()
    try:
        inserted, incomplete, output = await IntradayAggregationService(uow_factory(request)).run(
            instrument_id=payload.instrument_id,
            source_code=payload.source_code,
            start_at=payload.start_at,
            end_at=payload.end_at,
            targets=tuple(payload.targets),
            dry_run=payload.dry_run,
            correlation_id=run.correlation_id,
        )
        status = MarketSyncStatus.PARTIALLY_SUCCEEDED if incomplete else MarketSyncStatus.SUCCEEDED
        metadata = {
            **run.metadata,
            "input_estimate": len(output),
            "aggregated_bars_created": inserted,
            "incomplete_windows": incomplete,
        }
        async with uow_factory(request)() as uow:
            await uow.market_sync_runs.update_status(
                run.id,
                status=status,
                completed_at=datetime.now(UTC),
                total_received=len(output),
                total_inserted=inserted,
                total_updated=0,
                total_rejected=incomplete,
                error_summary=None,
                metadata=metadata,
            )
            await uow.commit()
        run.status = status
        run.metadata = metadata
        return run_dict(run)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/aggregations/{run_id}")
async def aggregation_detail(request: Request, run_id: UUID) -> dict[str, object]:
    async with uow_factory(request)() as uow:
        run = await uow.market_sync_runs.get_by_id(run_id)
    if run is None or run.metadata.get("operation_type") != "INTRADAY_AGGREGATION":
        raise to_app_error(ApplicationError("INTRADAY_AGGREGATION_FAILED", "聚合运行不存在"))
    return run_dict(run)


@router.post("/quality-runs")
async def quality_run(request: Request, payload: QualityRequest) -> dict[str, object]:
    try:
        run = await IntradayQualityService(uow_factory(request)).run(
            instrument_id=payload.instrument_id,
            source_code=payload.source_code,
            timeframe=payload.timeframe,
            start_at=payload.start_at,
            end_at=payload.end_at,
            correlation_id=request_correlation_id(request),
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return serializable(asdict(run))  # type: ignore[return-value]


@router.get("/quality-runs")
async def quality_runs(request: Request, page: int = 1, page_size: int = 20) -> dict[str, object]:
    async with uow_factory(request)() as uow:
        runs, total = await uow.market_data_quality_runs.list_recent(
            offset=(page - 1) * page_size, limit=min(page_size, 100)
        )
    values = [item for item in runs if item.metadata.get("scope") == "D03_INTRADAY"]
    return {"items": [serializable(asdict(item)) for item in values], "total": total}


@router.get("/quality-runs/{run_id}")
async def quality_detail(request: Request, run_id: UUID) -> dict[str, object]:
    async with uow_factory(request)() as uow:
        run = await uow.market_data_quality_runs.get_by_id(run_id)
        issues, total = await uow.market_data_quality_issues.list_for_run(
            run_id, offset=0, limit=500
        )
    if run is None or run.metadata.get("scope") != "D03_INTRADAY":
        raise to_app_error(ApplicationError("INTRADAY_QUALITY_RUN_NOT_FOUND", "分钟质量运行不存在"))
    return {
        "run": serializable(asdict(run)),
        "issues": [serializable(asdict(item)) for item in issues],
        "total": total,
    }


@router.get("/coverage")
async def coverage(
    request: Request,
    source_code: str = "MINIQMT",
    instrument_id: UUID | None = None,
    timeframe: MarketTimeframe | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, object]:
    try:
        if (
            start_at is not None
            and end_at is not None
            and start_at.tzinfo is not None
            and end_at.tzinfo is not None
            and (end_at - start_at).days > request.app.state.settings.intraday_max_date_range_days
        ):
            raise ApplicationError("INTRADAY_QUERY_TOO_LARGE", "覆盖度日期范围超过服务端上限")
        items = await IntradayOverviewService(uow_factory(request)).coverage(
            source_code,
            instrument_id=instrument_id,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return {"items": items}


@router.get("/readiness")
async def readiness(request: Request, source_code: str = "MINIQMT") -> dict[str, object]:
    return {"items": await IntradayOverviewService(uow_factory(request)).readiness(source_code)}


@router.get("/bars")
async def bars(
    request: Request,
    instrument_id: UUID,
    timeframe: MarketTimeframe,
    start_at: datetime,
    end_at: datetime,
    source_code: str = "MINIQMT",
    adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW,
    limit: Annotated[int, Query(ge=1, le=5_000)] = 2_000,
    cursor: datetime | None = None,
) -> dict[str, object]:
    effective_start = start_at
    if cursor is not None:
        if cursor.tzinfo is None or cursor < start_at or cursor >= end_at:
            raise to_app_error(
                ApplicationError("INTRADAY_INVALID_TIMESTAMP", "分页cursor必须位于查询时间范围内")
            )
        effective_start = cursor + timedelta(microseconds=1)
    try:
        values = await IntradayQueryService(
            uow_factory(request),
            max_bars=request.app.state.settings.intraday_query_max_bars,
            max_date_range_days=request.app.state.settings.intraday_max_date_range_days,
        ).bars(
            instrument_id=instrument_id,
            source_code=source_code,
            timeframe=timeframe,
            start_at=effective_start,
            end_at=end_at,
            adjustment_mode=adjustment_mode,
            limit=limit,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return {
        "items": [serializable(asdict(item)) for item in values],
        "timestamp_semantics": "BAR_START",
        "timezone": "UTC",
        "display_timezone": "Asia/Shanghai",
        "next_cursor": values[-1].bar_time.isoformat() if len(values) == limit else None,
        "historical": True,
        "realtime": False,
    }
