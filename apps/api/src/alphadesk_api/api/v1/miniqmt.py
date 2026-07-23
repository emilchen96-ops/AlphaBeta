"""MiniQMT read-only market-data and subscription APIs."""

from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.api.v1.market_common import request_correlation_id, uow_factory
from alphadesk_api.application.intraday import IntradayAggregationService
from alphadesk_api.application.miniqmt_market_data import (
    AGENT_STATUS_KEY,
    HISTORY_QUEUE_KEY,
    MiniQMTInstrumentCatalogService,
    MiniQMTMinuteBarService,
    MiniQMTQuoteIngestionService,
    MiniQMTSubscriptionService,
    update_agent_status,
)
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.free_market_cache import QuoteCache, read_json
from alphadesk_api.infrastructure.models import (
    InstrumentModel,
    MarketActiveSubscriptionModel,
    MarketBarModel,
    MarketDataSourceModel,
    MarketSubscriptionSetModel,
)
from alphadesk_api.schemas.miniqmt import (
    AgentStatusRequest,
    GenericResponse,
    HistoryBackfillRequest,
    InstrumentCatalogIngestRequest,
    MinuteBarIngestRequest,
    QuoteSnapshotIngestRequest,
    SubscriptionSyncReportRequest,
    TemporarySubscriptionRequest,
)
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.miniqmt_market import (
    MiniQMTTradingDisabledError,
    QuoteSnapshot,
    TradingStatus,
    miniqmt_provider_symbol,
)

router = APIRouter(tags=["miniqmt-market-data"])


def _redis(request: Request) -> Redis:
    client = getattr(request.app.state.redis, "client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="实时行情缓存不可用")
    return cast(Redis, client)


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    database = request.app.state.database
    if not isinstance(database, DatabaseService):
        raise HTTPException(status_code=503, detail="数据库不可用")
    return database.session_factory


def _subscriptions(request: Request) -> MiniQMTSubscriptionService:
    settings = request.app.state.settings
    return MiniQMTSubscriptionService(
        _sessions(request),
        _redis(request),
        max_subscriptions=settings.miniqmt_max_subscriptions,
        benchmark_symbols=settings.miniqmt_benchmark_symbols,
    )


def _agent_authorized(request: Request, token: str | None) -> None:
    configured = request.app.state.settings.miniqmt_agent_token
    if configured is not None:
        if token is None or not secrets.compare_digest(configured.get_secret_value(), token):
            raise HTTPException(status_code=401, detail="Windows行情代理认证失败")
        return
    host = request.client.host if request.client is not None else ""
    if host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="未配置行情代理令牌, 仅允许本机访问")


@router.get("/miniqmt/market-data/status", response_model=GenericResponse)
async def market_data_status(request: Request) -> GenericResponse:
    redis = _redis(request)
    agent = await read_json(redis, AGENT_STATUS_KEY)
    async with _sessions(request)() as session:
        desired = int(
            await session.scalar(
                select(MarketSubscriptionSetModel.desired_count)
                .order_by(MarketSubscriptionSetModel.created_at.desc())
                .limit(1)
            )
            or 0
        )
        active = int(
            await session.scalar(
                select(func.count())
                .select_from(MarketActiveSubscriptionModel)
                .where(MarketActiveSubscriptionModel.status == "SUBSCRIBED")
            )
            or 0
        )
        failed = int(
            await session.scalar(
                select(func.count())
                .select_from(MarketActiveSubscriptionModel)
                .where(MarketActiveSubscriptionModel.status == "FAILED")
            )
            or 0
        )
        latest_bar = await session.scalar(
            select(func.max(MarketBarModel.bar_time))
            .join(
                MarketDataSourceModel,
                MarketDataSourceModel.id == MarketBarModel.source_id,
            )
            .where(
                MarketBarModel.timeframe == "MINUTE_1",
                MarketDataSourceModel.source_code == "MINIQMT",
            )
        )
    settings = request.app.state.settings
    return GenericResponse(
        data={
            # XtQuant and its data directory belong to the separate Windows Agent.
            # The containerized API only needs the gateway enabled and an Agent heartbeat.
            "configured": settings.miniqmt_market_data_enabled,
            "state": (agent or {}).get("state", "NOT_CONFIGURED"),
            "agent": agent,
            "desired_count": desired,
            "active_count": active,
            "failed_count": failed,
            "latest_minute_bar_time": latest_bar,
            "source": "MINIQMT",
            "market_data_capability": "ENABLED",
            "trading_capability": "DISABLED",
            "trading_message": "交易功能: 未启用",
        }
    )


@router.get("/market-subscriptions/desired", response_model=GenericResponse)
async def desired_subscriptions(request: Request) -> GenericResponse:
    return GenericResponse(data=await _subscriptions(request).desired())


@router.get("/market-subscriptions/active", response_model=GenericResponse)
async def active_subscriptions(request: Request) -> GenericResponse:
    return GenericResponse(data={"items": await _subscriptions(request).active()})


@router.get("/market-subscriptions/diff", response_model=GenericResponse)
async def subscription_diff(request: Request) -> GenericResponse:
    return GenericResponse(data=await _subscriptions(request).diff())


@router.post("/market-subscriptions/rebuild", response_model=GenericResponse)
async def rebuild_subscriptions(request: Request) -> GenericResponse:
    return GenericResponse(data=await _subscriptions(request).rebuild())


@router.post("/market-subscriptions/sync", response_model=GenericResponse)
async def sync_subscriptions(request: Request) -> GenericResponse:
    return GenericResponse(
        data=await _subscriptions(request).begin_sync(request_correlation_id(request))
    )


@router.post("/market-subscriptions/temporary", response_model=GenericResponse)
async def temporary_subscription(
    request: Request, payload: TemporarySubscriptionRequest
) -> GenericResponse:
    service = _subscriptions(request)
    if payload.enabled:
        await service.add_temporary(payload.instrument_id)
    else:
        await service.remove_temporary(payload.instrument_id)
    return GenericResponse(data={"enabled": payload.enabled})


async def _quote_response(request: Request, instrument_id: UUID) -> dict[str, object]:
    snapshot = await QuoteCache(
        _redis(request), request.app.state.settings.miniqmt_quote_ttl_seconds
    ).get(instrument_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="该股票暂无实时行情")
    async with _sessions(request)() as session:
        instrument = await session.get(InstrumentModel, instrument_id)
    if instrument is None:
        raise HTTPException(status_code=404, detail="股票不存在")
    quote = snapshot.quote
    previous = quote.previous_close
    change = quote.last_price - previous if previous is not None else None
    change_percent = (
        change / previous * 100
        if change is not None and previous is not None and previous != 0
        else None
    )
    flags = quote.quality_flags
    return {
        "instrument_id": str(instrument_id),
        "symbol": instrument.symbol,
        "exchange": instrument.exchange,
        "name": instrument.name,
        "display_name": f"{instrument.name} ({instrument.symbol}.{instrument.exchange})",
        "market_time": quote.quote_time,
        "received_at": quote.received_at,
        "ingested_at": flags.get("ingested_at"),
        "last_price": quote.last_price,
        "change": change,
        "change_percent": change_percent,
        "open_price": quote.open,
        "high_price": quote.high,
        "low_price": quote.low,
        "previous_close": previous,
        "volume": quote.volume,
        "amount": quote.amount,
        "bid_price_1": quote.bid_price_1,
        "ask_price_1": quote.ask_price_1,
        "bid_volume_1": quote.bid_volume_1,
        "ask_volume_1": quote.ask_volume_1,
        "upper_limit_price": flags.get("upper_limit_price"),
        "lower_limit_price": flags.get("lower_limit_price"),
        "trading_status": flags.get("trading_status", "UNKNOWN"),
        "source": "MINIQMT",
        "revision": snapshot.revision.revision,
        "is_test_data": False,
        "schema_version": 1,
    }


@router.get("/quotes", response_model=GenericResponse)
async def list_quotes(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> GenericResponse:
    async with _sessions(request)() as session:
        ids = list(
            await session.scalars(
                select(MarketActiveSubscriptionModel.instrument_id)
                .where(MarketActiveSubscriptionModel.status == "SUBSCRIBED")
                .order_by(MarketActiveSubscriptionModel.instrument_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
    items = []
    for instrument_id in ids:
        try:
            items.append(await _quote_response(request, instrument_id))
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
    return GenericResponse(data={"items": items, "page": page, "page_size": page_size})


@router.get("/quotes/{instrument_id}", response_model=GenericResponse)
async def get_quote(request: Request, instrument_id: UUID) -> GenericResponse:
    return GenericResponse(data=await _quote_response(request, instrument_id))


@router.post("/miniqmt/history/backfill", response_model=GenericResponse)
async def request_history_backfill(
    request: Request, payload: HistoryBackfillRequest
) -> GenericResponse:
    settings = request.app.state.settings
    if payload.timeframe not in {"DAY_1", "MINUTE_1"}:
        raise HTTPException(status_code=422, detail="仅支持日线或1分钟历史补数")
    if payload.end_at <= payload.start_at:
        raise HTTPException(status_code=422, detail="历史补数结束时间必须晚于开始时间")
    if len(payload.instrument_ids) > settings.miniqmt_history_max_instruments:
        raise HTTPException(status_code=422, detail="历史补数股票数量超过限制")
    if (payload.end_at - payload.start_at).days > settings.miniqmt_history_max_days:
        raise HTTPException(status_code=422, detail="历史补数时间范围超过限制")
    async with _sessions(request)() as session:
        instruments = list(
            await session.scalars(
                select(InstrumentModel)
                .where(InstrumentModel.id.in_(payload.instrument_ids))
                .order_by(InstrumentModel.exchange, InstrumentModel.symbol)
            )
        )
    if len(instruments) != len(set(payload.instrument_ids)):
        raise HTTPException(status_code=422, detail="历史补数包含不存在的股票")
    history_instruments = [
        {
            "instrument_id": str(instrument.id),
            "provider_symbol": miniqmt_provider_symbol(instrument.symbol, instrument.exchange),
        }
        for instrument in instruments
    ]
    request_id = request_correlation_id(request)
    await cast(
        Awaitable[Any],
        _redis(request).rpush(
            HISTORY_QUEUE_KEY,
            json.dumps(
                {
                    "request_id": str(request_id),
                    **payload.model_dump(mode="json"),
                    "instruments": history_instruments,
                }
            ),
        ),
    )
    return GenericResponse(
        data={"request_id": str(request_id), "status": "QUEUED", "provider": "MINIQMT"}
    )


@router.post("/miniqmt/agent/status", response_model=GenericResponse)
async def agent_status(
    request: Request,
    payload: AgentStatusRequest,
    x_alphadesk_agent_token: str | None = Header(default=None),
) -> GenericResponse:
    _agent_authorized(request, x_alphadesk_agent_token)
    await update_agent_status(_redis(request), payload.model_dump(mode="json"))
    return GenericResponse(data={"accepted": True})


@router.post("/miniqmt/agent/instruments", response_model=GenericResponse)
async def ingest_agent_instruments(
    request: Request,
    payload: InstrumentCatalogIngestRequest,
    x_alphadesk_agent_token: str | None = Header(default=None),
) -> GenericResponse:
    _agent_authorized(request, x_alphadesk_agent_token)
    result = await MiniQMTInstrumentCatalogService(_sessions(request)).ingest(
        [item.model_dump(mode="python") for item in payload.items],
        sync_token=payload.sync_token,
        complete=payload.complete,
    )
    return GenericResponse(data=result)


@router.get("/miniqmt/agent/history/next", response_model=GenericResponse)
async def next_history_request(
    request: Request,
    x_alphadesk_agent_token: str | None = Header(default=None),
) -> GenericResponse:
    _agent_authorized(request, x_alphadesk_agent_token)
    raw = await cast(Awaitable[Any], _redis(request).lpop(HISTORY_QUEUE_KEY))
    return GenericResponse(data={"request": json.loads(str(raw)) if raw is not None else None})


@router.post("/miniqmt/agent/quotes", response_model=GenericResponse)
async def ingest_agent_quote(
    request: Request,
    payload: QuoteSnapshotIngestRequest,
    x_alphadesk_agent_token: str | None = Header(default=None),
) -> GenericResponse:
    _agent_authorized(request, x_alphadesk_agent_token)
    try:
        snapshot = QuoteSnapshot(
            **payload.model_dump(exclude={"trading_status"}),
            trading_status=TradingStatus(payload.trading_status),
            source="MINIQMT",
        )
        changed, reason, revision = await MiniQMTQuoteIngestionService(
            _sessions(request),
            QuoteCache(_redis(request), request.app.state.settings.miniqmt_quote_ttl_seconds),
            _redis(request),
        ).ingest(snapshot)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"行情快照无效: {exc}") from exc
    return GenericResponse(data={"changed": changed, "reason": reason, "revision": revision})


@router.post("/miniqmt/agent/minute-bars", response_model=GenericResponse)
async def ingest_agent_minute_bars(
    request: Request,
    payload: MinuteBarIngestRequest,
    x_alphadesk_agent_token: str | None = Header(default=None),
) -> GenericResponse:
    _agent_authorized(request, x_alphadesk_agent_token)
    result = await MiniQMTMinuteBarService(_sessions(request)).ingest(
        [item.model_dump(mode="python") for item in payload.items]
    )
    shanghai = ZoneInfo("Asia/Shanghai")
    minute_items = [item for item in payload.items if item.timeframe == "MINUTE_1"]
    touched = {
        (item.instrument_id, item.bar_time.astimezone(shanghai).date()) for item in minute_items
    }
    aggregated = 0
    incomplete_windows = 0
    for instrument_id, session_date in sorted(touched, key=lambda value: (str(value[0]), value[1])):
        start_at = datetime.combine(session_date, time.min, tzinfo=shanghai).astimezone(UTC)
        end_at = start_at + timedelta(days=1)
        created, incomplete, _ = await IntradayAggregationService(uow_factory(request)).run(
            instrument_id=instrument_id,
            source_code="MINIQMT",
            start_at=start_at,
            end_at=end_at,
            targets=(
                MarketTimeframe.MINUTE_5,
                MarketTimeframe.MINUTE_15,
                MarketTimeframe.MINUTE_30,
                MarketTimeframe.MINUTE_60,
            ),
            dry_run=False,
        )
        aggregated += created
        incomplete_windows += incomplete
    result["aggregated"] = aggregated
    result["incomplete_windows"] = incomplete_windows
    await _redis(request).publish(
        "alphadesk:market:v1:events",
        json.dumps(
            {
                "schema_version": 1,
                "type": "minute_bar_closed",
                "event_type": "minute_bar_closed",
                "instrument_id": None,
                "market_time": None,
                "occurred_at": datetime.now(UTC).isoformat(),
                "payload": result,
            }
        ),
    )
    return GenericResponse(data=result)


@router.post("/miniqmt/agent/subscription-sync/{sync_run_id}", response_model=GenericResponse)
async def report_agent_sync(
    request: Request,
    sync_run_id: UUID,
    payload: SubscriptionSyncReportRequest,
    x_alphadesk_agent_token: str | None = Header(default=None),
) -> GenericResponse:
    _agent_authorized(request, x_alphadesk_agent_token)
    return GenericResponse(
        data=await _subscriptions(request).report_sync(
            sync_run_id,
            subscriptions=[item.model_dump(mode="json") for item in payload.subscriptions],
            unsubscriptions=[item.model_dump(mode="json") for item in payload.unsubscriptions],
        )
    )


@router.post("/miniqmt/agent/trading", status_code=status.HTTP_403_FORBIDDEN)
async def reject_agent_trading(
    request: Request,
    x_alphadesk_agent_token: str | None = Header(default=None),
) -> None:
    _agent_authorized(request, x_alphadesk_agent_token)
    error = MiniQMTTradingDisabledError()
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": error.code, "message": str(error)},
    )
