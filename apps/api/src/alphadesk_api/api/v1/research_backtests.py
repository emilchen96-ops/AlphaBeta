"""Product-facing quick-backtest endpoints using BT01 as the execution engine."""

import json
from collections.abc import Awaitable
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from alphadesk_api.api.v1.market_common import (
    request_correlation_id,
    to_app_error,
    uow_factory,
)
from alphadesk_api.application.backtest_batches import (
    BacktestBatchQueryService,
    BacktestBatchService,
    CreateBacktestBatchRequest,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.miniqmt_market_data import HISTORY_QUEUE_KEY
from alphadesk_api.application.research_backtests import (
    QuickBacktestRequest,
    QuickBacktestService,
    ResearchBacktestQueryService,
)
from alphadesk_api.core.config import Settings
from alphadesk_api.schemas.research_backtests import (
    BacktestBatchBody,
    QuickBacktestBody,
    ResearchBacktestPageResponse,
)
from alphadesk_domain.backtest_batches import BacktestBatchScope
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_spec import StrategySpecError, strategy_spec_from_dict

router = APIRouter(prefix="/research", tags=["research-backtests"])


def _registry(request: Request) -> StrategyRegistry:
    return cast(StrategyRegistry, request.app.state.strategy_registry)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _backfill_enqueuer(request: Request):
    client = getattr(request.app.state.redis, "client", None)
    if client is None:
        return None

    async def enqueue(payload: dict[str, object]) -> int:
        return int(
            await cast(
                Awaitable[int],
                client.rpush(
                    HISTORY_QUEUE_KEY,
                    json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                ),
            )
        )

    return enqueue


def _decimal(value: str, name: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ApplicationError("QUICK_BACKTEST_INVALID", f"{name}格式不正确") from exc
    if not result.is_finite():
        raise ApplicationError("QUICK_BACKTEST_INVALID", f"{name}必须是有限数字")
    return result


@router.post(
    "/quick-backtests",
    status_code=status.HTTP_201_CREATED,
)
async def quick_backtest(request: Request, body: QuickBacktestBody) -> dict[str, Any]:
    try:
        spec = None if body.spec is None else strategy_spec_from_dict(body.spec)
        return await QuickBacktestService(
            uow_factory(request),
            _registry(request),
            _settings(request),
            _backfill_enqueuer(request),
        ).run(
            QuickBacktestRequest(
                instrument_id=body.instrument_id,
                start_at=body.start_at,
                end_at=body.end_at,
                initial_cash=_decimal(body.initial_cash, "初始资金"),
                spec=spec,
                user_strategy_id=body.user_strategy_id,
                price_adjustment_mode=body.price_adjustment_mode,
                commission_rate=_decimal(body.commission_rate, "佣金率"),
                minimum_commission=_decimal(body.minimum_commission or "5", "最低佣金"),
                stamp_duty_rate=_decimal(body.stamp_duty_rate, "印花税率"),
                transfer_fee_rate=_decimal(body.transfer_fee_rate, "过户费率"),
                slippage_basis_points=_decimal(body.slippage_basis_points, "滑点"),
                maximum_volume_participation=(
                    None
                    if body.maximum_volume_participation is None
                    else _decimal(body.maximum_volume_participation, "最大成交量参与率")
                ),
                execution_price_mode=body.execution_price_mode,
                signal_timeframe=body.signal_timeframe,
                auto_prepare_minute_data=body.auto_prepare_minute_data,
                optimistic_fill_assumption=body.optimistic_fill_assumption,
                position_size_ratio=(
                    None
                    if body.position_size_ratio is None
                    else _decimal(body.position_size_ratio, "单次买入仓位")
                ),
                maximum_entry_gap_ratio=(
                    None
                    if body.maximum_entry_gap_ratio is None
                    else _decimal(body.maximum_entry_gap_ratio, "最大允许高开幅度")
                ),
                time_in_force=body.time_in_force,
                idempotency_key=body.idempotency_key,
                correlation_id=request_correlation_id(request),
            )
        )
    except StrategySpecError as exc:
        raise to_app_error(ApplicationError(exc.code, str(exc))) from exc
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests", response_model=ResearchBacktestPageResponse)
async def research_backtests(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ResearchBacktestPageResponse:
    return ResearchBacktestPageResponse.model_validate(
        await ResearchBacktestQueryService(uow_factory(request)).list(
            page=page, page_size=page_size
        )
    )


@router.get("/backtests/{run_id}")
async def research_backtest_detail(request: Request, run_id: UUID) -> dict[str, Any]:
    try:
        return await ResearchBacktestQueryService(uow_factory(request)).detail(run_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{run_id}/summary")
async def research_backtest_summary(request: Request, run_id: UUID) -> dict[str, Any]:
    try:
        return await ResearchBacktestQueryService(uow_factory(request)).summary(run_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{run_id}/trades")
async def research_backtest_trades(request: Request, run_id: UUID) -> dict[str, Any]:
    try:
        return {"items": await ResearchBacktestQueryService(uow_factory(request)).trades(run_id)}
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{run_id}/signals")
async def research_backtest_signals(request: Request, run_id: UUID) -> dict[str, Any]:
    try:
        return {"items": await ResearchBacktestQueryService(uow_factory(request)).signals(run_id)}
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{run_id}/equity")
async def research_backtest_equity(request: Request, run_id: UUID) -> dict[str, Any]:
    try:
        return {"items": await ResearchBacktestQueryService(uow_factory(request)).equity(run_id)}
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/backtest-batches", status_code=status.HTTP_202_ACCEPTED)
async def create_backtest_batch(request: Request, body: BacktestBatchBody) -> dict[str, Any]:
    try:
        spec = None if body.spec is None else strategy_spec_from_dict(body.spec)
        return await BacktestBatchService(
            uow_factory(request),
            _registry(request),
            _settings(request),
        ).create(
            CreateBacktestBatchRequest(
                scope=BacktestBatchScope(body.scope),
                watchlist_id=body.watchlist_id,
                start_at=body.start_at,
                end_at=body.end_at,
                initial_cash=_decimal(body.initial_cash, "每只股票初始资金"),
                spec=spec,
                user_strategy_id=body.user_strategy_id,
                exclude_st=body.exclude_st,
                exclude_bse=body.exclude_bse,
                exclude_star_market=body.exclude_star_market,
                exclude_chinext=body.exclude_chinext,
                commission_rate=_decimal(body.commission_rate, "佣金率"),
                minimum_commission=_decimal(body.minimum_commission or "5", "最低佣金"),
                stamp_duty_rate=_decimal(body.stamp_duty_rate, "印花税率"),
                transfer_fee_rate=_decimal(body.transfer_fee_rate, "过户费率"),
                slippage_basis_points=_decimal(body.slippage_basis_points, "滑点"),
                maximum_volume_participation=(
                    None
                    if body.maximum_volume_participation is None
                    else _decimal(
                        body.maximum_volume_participation,
                        "最大成交量参与率",
                    )
                ),
                execution_price_mode=body.execution_price_mode,
                signal_timeframe=body.signal_timeframe,
                auto_prepare_minute_data=body.auto_prepare_minute_data,
                optimistic_fill_assumption=body.optimistic_fill_assumption,
                position_size_ratio=(
                    None
                    if body.position_size_ratio is None
                    else _decimal(body.position_size_ratio, "单次买入仓位")
                ),
                maximum_entry_gap_ratio=(
                    None
                    if body.maximum_entry_gap_ratio is None
                    else _decimal(
                        body.maximum_entry_gap_ratio,
                        "最大允许高开幅度",
                    )
                ),
                time_in_force=body.time_in_force,
                idempotency_key=body.idempotency_key,
                correlation_id=request_correlation_id(request),
            )
        )
    except StrategySpecError as exc:
        raise to_app_error(ApplicationError(exc.code, str(exc))) from exc
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtest-batches")
async def list_backtest_batches(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    return await BacktestBatchQueryService(uow_factory(request)).list(
        page=page,
        page_size=page_size,
    )


@router.get("/backtest-batches/{batch_id}")
async def get_backtest_batch(request: Request, batch_id: UUID) -> dict[str, Any]:
    try:
        return await BacktestBatchQueryService(uow_factory(request)).detail(batch_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/backtest-batches/{batch_id}/cancel")
async def cancel_backtest_batch(request: Request, batch_id: UUID) -> dict[str, Any]:
    try:
        return await BacktestBatchService(
            uow_factory(request), _registry(request), _settings(request)
        ).cancel(batch_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/backtest-batches/{batch_id}/retry-failed")
async def retry_failed_backtest_batch(
    request: Request, batch_id: UUID
) -> dict[str, Any]:
    try:
        return await BacktestBatchService(
            uow_factory(request), _registry(request), _settings(request)
        ).retry_failed(batch_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtest-batches/{batch_id}/results")
async def get_backtest_batch_results(
    request: Request,
    batch_id: UUID,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    try:
        return await BacktestBatchQueryService(uow_factory(request)).results(
            batch_id,
            page=page,
            page_size=page_size,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtest-batches/{batch_id}/summary")
async def get_backtest_batch_summary(request: Request, batch_id: UUID) -> dict[str, Any]:
    try:
        return await BacktestBatchQueryService(uow_factory(request)).summary(batch_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtest-batches/{batch_id}/export.csv")
async def export_backtest_batch_csv(request: Request, batch_id: UUID) -> Response:
    try:
        content = await BacktestBatchQueryService(uow_factory(request)).csv(batch_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="backtest-batch-{batch_id}.csv"'},
    )
