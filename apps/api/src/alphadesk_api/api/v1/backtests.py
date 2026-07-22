"""BT01 synchronous daily backtest HTTP endpoints."""

from collections.abc import Sequence
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.backtests import (
    BacktestIntegrityService,
    BacktestQueryService,
    BacktestService,
    CreateBacktestRequest,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.strategies import StrategyResearchService
from alphadesk_api.core.config import Settings
from alphadesk_api.schemas.backtests import (
    BacktestCollectionResponse,
    BacktestCreateBody,
    BacktestIntegrityResponse,
    BacktestMetricResponse,
    BacktestPageResponse,
    BacktestRunResponse,
)
from alphadesk_domain.backtest import BacktestRunStatus
from alphadesk_domain.broker import AshareSimpleFeeModel, FixedBasisPointsSlippageModel
from alphadesk_domain.enums import MarketTimeframe, OrderType, TimeInForce
from alphadesk_domain.strategy import StrategyRegistry

router = APIRouter(tags=["daily-backtests"])


def _registry(request: Request) -> StrategyRegistry:
    return cast(StrategyRegistry, request.app.state.strategy_registry)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _decimal(value: str, name: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ApplicationError("BACKTEST_INVALID_CONFIGURATION", f"{name} is invalid") from exc
    if not result.is_finite():
        raise ApplicationError("BACKTEST_INVALID_CONFIGURATION", f"{name} must be finite")
    return result


def _json(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json(item) for item in value]
    return value


def _collection(items: Sequence[Any]) -> BacktestCollectionResponse:
    return BacktestCollectionResponse(
        items=[cast(dict[str, Any], _json(asdict(item))) for item in items]
    )


@router.post("/backtests", response_model=BacktestRunResponse, status_code=status.HTTP_201_CREATED)
async def create_backtest(request: Request, body: BacktestCreateBody) -> BacktestRunResponse:
    registry = _registry(request)
    parameter_service = StrategyResearchService(uow_factory(request), registry)
    try:
        fee = body.fee_configuration
        slippage = body.slippage_configuration
        service = BacktestService(uow_factory(request), registry, _settings(request))
        result = await service.run(
            CreateBacktestRequest(
                strategy_key=body.strategy_key,
                parameters=parameter_service.parameters(body.strategy_key, body.parameters),
                instrument_ids=tuple(body.instrument_ids),
                timeframe=MarketTimeframe(body.timeframe),
                start_at=body.start_at,
                end_at=body.end_at,
                initial_cash=_decimal(body.initial_cash, "initial_cash"),
                order_type=OrderType(body.order_type),
                time_in_force=TimeInForce(body.time_in_force),
                fee_configuration=AshareSimpleFeeModel(
                    commission_rate=_decimal(fee.commission_rate, "commission_rate"),
                    minimum_commission=_decimal(fee.minimum_commission, "minimum_commission"),
                    stamp_duty_rate=_decimal(fee.stamp_duty_rate, "stamp_duty_rate"),
                    transfer_fee_rate=_decimal(fee.transfer_fee_rate, "transfer_fee_rate"),
                ),
                slippage_configuration=FixedBasisPointsSlippageModel(
                    basis_points=_decimal(slippage.basis_points, "basis_points"),
                    maximum_slippage=(
                        None
                        if slippage.maximum_slippage is None
                        else _decimal(slippage.maximum_slippage, "maximum_slippage")
                    ),
                ),
                maximum_volume_participation=(
                    None
                    if body.maximum_volume_participation is None
                    else _decimal(body.maximum_volume_participation, "maximum_volume_participation")
                ),
                benchmark_symbol=body.benchmark_symbol,
                data_source_code=body.data_source_code,
                idempotency_key=body.idempotency_key,
                correlation_id=request_correlation_id(request),
                strategy_price_adjustment_mode=body.strategy_price_adjustment_mode,
            )
        )
        detail = await BacktestQueryService(uow_factory(request)).detail(result.run.id)
        detail["replayed"] = result.replayed
        return BacktestRunResponse.model_validate(detail)
    except (ApplicationError, ValueError) as exc:
        if isinstance(exc, ApplicationError):
            raise to_app_error(exc) from exc
        raise to_app_error(
            ApplicationError("BACKTEST_INVALID_CONFIGURATION", "backtest request is invalid")
        ) from exc


@router.get("/backtests", response_model=BacktestPageResponse)
async def list_backtests(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    run_status: BacktestRunStatus | None = None,
) -> BacktestPageResponse:
    result = await BacktestQueryService(uow_factory(request)).list(
        page=page,
        page_size=page_size,
        status=None if run_status is None else run_status.value,
    )
    return BacktestPageResponse.model_validate(result)


@router.get("/backtests/{backtest_id}", response_model=BacktestRunResponse)
async def backtest_detail(request: Request, backtest_id: UUID) -> BacktestRunResponse:
    try:
        return BacktestRunResponse.model_validate(
            await BacktestQueryService(uow_factory(request)).detail(backtest_id)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{backtest_id}/metrics", response_model=BacktestMetricResponse)
async def backtest_metrics(request: Request, backtest_id: UUID) -> BacktestMetricResponse:
    try:
        metrics = await BacktestQueryService(uow_factory(request)).metrics(backtest_id)
        return BacktestMetricResponse(metrics=cast(dict[str, Any], _json(asdict(metrics))))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{backtest_id}/equity-curve", response_model=BacktestCollectionResponse)
async def backtest_equity(request: Request, backtest_id: UUID) -> BacktestCollectionResponse:
    try:
        return _collection(
            await BacktestQueryService(uow_factory(request)).equity_curve(backtest_id)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{backtest_id}/trades", response_model=BacktestCollectionResponse)
async def backtest_trades(request: Request, backtest_id: UUID) -> BacktestCollectionResponse:
    try:
        return _collection(await BacktestQueryService(uow_factory(request)).trades(backtest_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{backtest_id}/signals", response_model=BacktestCollectionResponse)
async def backtest_signals(request: Request, backtest_id: UUID) -> BacktestCollectionResponse:
    try:
        return _collection(await BacktestQueryService(uow_factory(request)).signals(backtest_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{backtest_id}/risk-decisions", response_model=BacktestCollectionResponse)
async def backtest_risks(request: Request, backtest_id: UUID) -> BacktestCollectionResponse:
    try:
        return _collection(
            await BacktestQueryService(uow_factory(request)).risk_decisions(backtest_id)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{backtest_id}/orders", response_model=BacktestCollectionResponse)
async def backtest_orders(request: Request, backtest_id: UUID) -> BacktestCollectionResponse:
    try:
        return _collection(await BacktestQueryService(uow_factory(request)).orders(backtest_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{backtest_id}/fills", response_model=BacktestCollectionResponse)
async def backtest_fills(request: Request, backtest_id: UUID) -> BacktestCollectionResponse:
    try:
        return _collection(await BacktestQueryService(uow_factory(request)).fills(backtest_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{backtest_id}/timeline", response_model=BacktestCollectionResponse)
async def backtest_timeline(request: Request, backtest_id: UUID) -> BacktestCollectionResponse:
    try:
        return _collection(await BacktestQueryService(uow_factory(request)).timeline(backtest_id))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/backtests/{backtest_id}/integrity", response_model=BacktestIntegrityResponse)
async def backtest_integrity(request: Request, backtest_id: UUID) -> BacktestIntegrityResponse:
    try:
        report = await BacktestIntegrityService(uow_factory(request)).verify(backtest_id)
        return BacktestIntegrityResponse(
            run_id=report.run_id,
            passed=report.passed,
            checked_at=report.checked_at,
            issues=[cast(dict[str, Any], _json(asdict(item))) for item in report.issues],
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
