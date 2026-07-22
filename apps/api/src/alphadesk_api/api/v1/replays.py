"""RT01 historical replay HTTP endpoints."""

from collections.abc import Sequence
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.replays import (
    CreateReplayRequest,
    ReplayControlRequest,
    ReplayEventPublisher,
    ReplayIntegrityService,
    ReplayQueryService,
    ReplayService,
)
from alphadesk_api.application.strategies import StrategyResearchService
from alphadesk_api.core.config import Settings
from alphadesk_api.schemas.replays import (
    ReplayCollectionResponse,
    ReplayControlBody,
    ReplayCreateBody,
    ReplayEventPageResponse,
    ReplayIntegrityResponse,
    ReplayPageResponse,
    ReplayRunResponse,
    ReplaySpeedBody,
    ReplayStateResponse,
)
from alphadesk_domain.broker import AshareSimpleFeeModel, FixedBasisPointsSlippageModel
from alphadesk_domain.enums import OrderType, TimeInForce
from alphadesk_domain.replay import (
    ReplayControlActionType,
    ReplayEventType,
    ReplayRunStatus,
    ReplaySpeedMode,
)
from alphadesk_domain.strategy import StrategyRegistry

router = APIRouter(tags=["historical-replays"])


def _registry(request: Request) -> StrategyRegistry:
    return cast(StrategyRegistry, request.app.state.strategy_registry)


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _decimal(value: str, name: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ApplicationError("REPLAY_INVALID_CONFIGURATION", f"{name} is invalid") from exc
    if not result.is_finite():
        raise ApplicationError("REPLAY_INVALID_CONFIGURATION", f"{name} must be finite")
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
    if isinstance(value, tuple | list):
        return [_json(item) for item in value]
    return value


def _collection(items: Sequence[Any]) -> ReplayCollectionResponse:
    return ReplayCollectionResponse(
        items=[cast(dict[str, Any], _json(asdict(item))) for item in items]
    )


def _service(request: Request) -> ReplayService:
    redis = getattr(request.app.state, "redis", None)
    client = getattr(redis, "client", None)
    return ReplayService(
        uow_factory(request),
        _registry(request),
        _settings(request),
        ReplayEventPublisher(client),
    )


@router.post("/replays", response_model=ReplayRunResponse, status_code=status.HTTP_201_CREATED)
async def create_replay(request: Request, body: ReplayCreateBody) -> ReplayRunResponse:
    registry = _registry(request)
    parameters = StrategyResearchService(uow_factory(request), registry).parameters(
        body.strategy_key, body.parameters
    )
    try:
        fee = body.fee_configuration
        slippage = body.slippage_configuration
        result = await _service(request).create(
            CreateReplayRequest(
                strategy_key=body.strategy_key,
                parameters=parameters,
                instrument_ids=tuple(body.instrument_ids),
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
                speed_mode=ReplaySpeedMode(body.speed_mode),
                idempotency_key=body.idempotency_key,
                risk_configuration_reference=body.risk_configuration_reference,
                data_source_code=body.data_source_code,
                correlation_id=request_correlation_id(request),
                strategy_price_adjustment_mode=body.strategy_price_adjustment_mode,
            )
        )
        detail = await ReplayQueryService(uow_factory(request)).detail(result.run.id)
        detail["replayed"] = result.replayed
        return ReplayRunResponse.model_validate(detail)
    except (ApplicationError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, ApplicationError)
            else ApplicationError("REPLAY_INVALID_CONFIGURATION", "replay request is invalid")
        )
        raise to_app_error(error) from exc


@router.get("/replays", response_model=ReplayPageResponse)
async def list_replays(
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    run_status: ReplayRunStatus | None = None,
) -> ReplayPageResponse:
    result = await ReplayQueryService(uow_factory(request)).list(
        page=page,
        page_size=page_size,
        status=None if run_status is None else run_status.value,
    )
    return ReplayPageResponse.model_validate(result)


@router.get("/replays/{replay_id}", response_model=ReplayRunResponse)
async def replay_detail(request: Request, replay_id: UUID) -> ReplayRunResponse:
    try:
        return ReplayRunResponse.model_validate(
            await ReplayQueryService(uow_factory(request)).detail(replay_id)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


async def _control(
    request: Request,
    replay_id: UUID,
    body: ReplayControlBody,
    action: ReplayControlActionType,
    speed: ReplaySpeedMode | None = None,
) -> ReplayRunResponse:
    try:
        run = await _service(request).control(
            ReplayControlRequest(
                replay_run_id=replay_id,
                action_type=action,
                idempotency_key=body.idempotency_key,
                expected_run_version=body.expected_run_version,
                requested_speed=speed,
                correlation_id=request_correlation_id(request),
            )
        )
        return ReplayRunResponse.model_validate(
            await ReplayQueryService(uow_factory(request)).detail(run.id)
        )
    except (ApplicationError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, ApplicationError)
            else ApplicationError("REPLAY_INVALID_CONFIGURATION", "control request is invalid")
        )
        raise to_app_error(error) from exc


@router.post("/replays/{replay_id}/start", response_model=ReplayRunResponse)
async def start_replay(
    request: Request, replay_id: UUID, body: ReplayControlBody
) -> ReplayRunResponse:
    return await _control(request, replay_id, body, ReplayControlActionType.START)


@router.post("/replays/{replay_id}/pause", response_model=ReplayRunResponse)
async def pause_replay(
    request: Request, replay_id: UUID, body: ReplayControlBody
) -> ReplayRunResponse:
    return await _control(request, replay_id, body, ReplayControlActionType.PAUSE)


@router.post("/replays/{replay_id}/resume", response_model=ReplayRunResponse)
async def resume_replay(
    request: Request, replay_id: UUID, body: ReplayControlBody
) -> ReplayRunResponse:
    return await _control(request, replay_id, body, ReplayControlActionType.RESUME)


@router.post("/replays/{replay_id}/step", response_model=ReplayRunResponse)
async def step_replay(
    request: Request, replay_id: UUID, body: ReplayControlBody
) -> ReplayRunResponse:
    return await _control(request, replay_id, body, ReplayControlActionType.STEP)


@router.post("/replays/{replay_id}/stop", response_model=ReplayRunResponse)
async def stop_replay(
    request: Request, replay_id: UUID, body: ReplayControlBody
) -> ReplayRunResponse:
    return await _control(request, replay_id, body, ReplayControlActionType.STOP)


@router.post("/replays/{replay_id}/speed", response_model=ReplayRunResponse)
async def set_replay_speed(
    request: Request, replay_id: UUID, body: ReplaySpeedBody
) -> ReplayRunResponse:
    try:
        speed = ReplaySpeedMode(body.speed_mode)
    except ValueError as exc:
        raise to_app_error(
            ApplicationError("REPLAY_INVALID_CONFIGURATION", "speed mode is invalid")
        ) from exc
    return await _control(request, replay_id, body, ReplayControlActionType.SET_SPEED, speed)


@router.get("/replays/{replay_id}/events", response_model=ReplayEventPageResponse)
async def replay_events(
    request: Request,
    replay_id: UUID,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    event_type: ReplayEventType | None = None,
    instrument_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> ReplayEventPageResponse:
    try:
        result = await ReplayQueryService(uow_factory(request)).events(
            replay_id,
            after_sequence=after_sequence,
            event_type=None if event_type is None else event_type.value,
            instrument_id=instrument_id,
            page=page,
            page_size=page_size,
        )
        return ReplayEventPageResponse.model_validate(result)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/replays/{replay_id}/state", response_model=ReplayStateResponse)
async def replay_state(request: Request, replay_id: UUID) -> ReplayStateResponse:
    try:
        return ReplayStateResponse(
            state=cast(
                dict[str, Any],
                _json(await ReplayQueryService(uow_factory(request)).state(replay_id)),
            )
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/replays/{replay_id}/equity", response_model=ReplayCollectionResponse)
async def replay_equity(request: Request, replay_id: UUID) -> ReplayCollectionResponse:
    return _collection(await ReplayQueryService(uow_factory(request)).equity(replay_id))


@router.get("/replays/{replay_id}/signals", response_model=ReplayCollectionResponse)
async def replay_signals(request: Request, replay_id: UUID) -> ReplayCollectionResponse:
    return _collection(await ReplayQueryService(uow_factory(request)).signals(replay_id))


@router.get("/replays/{replay_id}/risk-decisions", response_model=ReplayCollectionResponse)
async def replay_risks(request: Request, replay_id: UUID) -> ReplayCollectionResponse:
    return _collection(await ReplayQueryService(uow_factory(request)).risk_decisions(replay_id))


@router.get("/replays/{replay_id}/orders", response_model=ReplayCollectionResponse)
async def replay_orders(request: Request, replay_id: UUID) -> ReplayCollectionResponse:
    return _collection(await ReplayQueryService(uow_factory(request)).orders(replay_id))


@router.get("/replays/{replay_id}/fills", response_model=ReplayCollectionResponse)
async def replay_fills(request: Request, replay_id: UUID) -> ReplayCollectionResponse:
    return _collection(await ReplayQueryService(uow_factory(request)).fills(replay_id))


@router.get("/replays/{replay_id}/integrity", response_model=ReplayIntegrityResponse)
async def replay_integrity(request: Request, replay_id: UUID) -> ReplayIntegrityResponse:
    try:
        report = await ReplayIntegrityService(uow_factory(request)).verify(replay_id)
        return ReplayIntegrityResponse.model_validate(asdict(report))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
