"""Product-facing quick-backtest endpoints using BT01 as the execution engine."""

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import (
    request_correlation_id,
    to_app_error,
    uow_factory,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.research_backtests import (
    QuickBacktestRequest,
    QuickBacktestService,
    ResearchBacktestQueryService,
)
from alphadesk_api.core.config import Settings
from alphadesk_api.schemas.research_backtests import (
    QuickBacktestBody,
    ResearchBacktestPageResponse,
)
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_spec import StrategySpecError, strategy_spec_from_dict

router = APIRouter(prefix="/research", tags=["research-backtests"])


def _registry(request: Request) -> StrategyRegistry:
    return cast(StrategyRegistry, request.app.state.strategy_registry)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


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
            uow_factory(request), _registry(request), _settings(request)
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
                minimum_commission=_decimal(body.minimum_commission, "最低佣金"),
                stamp_duty_rate=_decimal(body.stamp_duty_rate, "印花税率"),
                transfer_fee_rate=_decimal(body.transfer_fee_rate, "过户费率"),
                slippage_basis_points=_decimal(body.slippage_basis_points, "滑点"),
                maximum_volume_participation=(
                    None
                    if body.maximum_volume_participation is None
                    else _decimal(body.maximum_volume_participation, "最大成交量参与率")
                ),
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
