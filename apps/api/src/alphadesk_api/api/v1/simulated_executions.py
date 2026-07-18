"""B01-C local simulated-execution APIs; no external Broker is contacted."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.simulated_execution import (
    SimulatedBrokerExecutionService,
    SimulatedExecutionIntegrityService,
    SimulatedExecutionMarketInput,
    SimulatedExecutionQueryService,
)
from alphadesk_api.schemas.simulated_execution import (
    ExecutionAttemptPageResponse,
    ExecutionAttemptResponse,
    ExecutionDetailResponse,
    FillPageResponse,
    FillResponse,
    IntegrityIssueResponse,
    IntegrityReportResponse,
    SimulatedExecutionBody,
    SimulatedExecutionResultResponse,
)

router = APIRouter(tags=["simulated-executions"])


def _decimal(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ApplicationError("BROKER_EXECUTION_INVALID_REQUEST", f"{field} is invalid") from exc
    if not result.is_finite():
        raise ApplicationError("BROKER_EXECUTION_INVALID_REQUEST", f"{field} must be finite")
    return result


@router.post(
    "/orders/{order_id}/simulated-executions",
    response_model=SimulatedExecutionResultResponse,
)
async def execute_simulated_order(
    request: Request, order_id: UUID, body: SimulatedExecutionBody
) -> SimulatedExecutionResultResponse:
    try:
        result = await SimulatedBrokerExecutionService(uow_factory(request)).execute_market_input(
            SimulatedExecutionMarketInput(
                order_id=order_id,
                idempotency_key=body.idempotency_key,
                correlation_id=request_correlation_id(request),
                timestamp=body.timestamp,
                trading_status=body.trading_status,
                source=body.source,
                is_stale=body.is_stale,
                open=_decimal(body.open, "open"),
                high=_decimal(body.high, "high"),
                low=_decimal(body.low, "low"),
                close=_decimal(body.close, "close"),
                last_price=_decimal(body.last_price, "last_price"),
                bid_price=_decimal(body.bid_price, "bid_price"),
                ask_price=_decimal(body.ask_price, "ask_price"),
                available_volume=_decimal(body.available_volume, "available_volume"),
                price_limit_up=_decimal(body.price_limit_up, "price_limit_up"),
                price_limit_down=_decimal(body.price_limit_down, "price_limit_down"),
            )
        )
        total_fee = sum(
            (fill.commission + fill.tax + fill.other_fee for fill in result.fills), Decimal("0")
        )
        return SimulatedExecutionResultResponse(
            execution_attempt_id=result.attempt.id,
            order_id=result.order.id,
            order_status=result.order.status,
            result_status=result.attempt.result_status,
            requested_quantity=result.attempt.requested_quantity,
            previously_filled_quantity=result.attempt.previously_filled_quantity,
            attempted_quantity=result.attempt.attempted_quantity,
            filled_quantity=result.attempt.filled_quantity,
            remaining_quantity=result.attempt.remaining_quantity,
            average_fill_price=result.attempt.average_fill_price,
            fill_ids=[fill.id for fill in result.fills],
            total_fee=total_fee,
            rejection_code=result.attempt.rejection_code,
            message=result.attempt.message,
            warnings=[issue.message for issue in result.integrity_issues],
            correlation_id=result.attempt.correlation_id,
            idempotent=result.idempotent,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/orders/{order_id}/execution-attempts", response_model=ExecutionAttemptPageResponse)
async def list_order_execution_attempts(
    request: Request,
    order_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ExecutionAttemptPageResponse:
    try:
        result = cast(
            dict[str, Any],
            await SimulatedExecutionQueryService(uow_factory(request)).list_attempts(
                order_id, page=page, page_size=page_size
            ),
        )
        return ExecutionAttemptPageResponse(
            items=[ExecutionAttemptResponse.model_validate(item) for item in result["items"]],
            page=page,
            page_size=page_size,
            total=int(result["total"]),
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/simulated-executions/{execution_attempt_id}", response_model=ExecutionDetailResponse)
async def get_execution_attempt(
    request: Request, execution_attempt_id: UUID
) -> ExecutionDetailResponse:
    try:
        value = cast(
            dict[str, Any],
            await SimulatedExecutionQueryService(uow_factory(request)).execution_detail(
                execution_attempt_id
            ),
        )
        transitions = [
            {
                "from_status": item.from_status,
                "to_status": item.to_status,
                "actor_type": item.actor_type,
                "reason": item.reason,
                "occurred_at": item.occurred_at,
                "correlation_id": item.correlation_id,
            }
            for item in value["order_transitions"]
        ]
        return ExecutionDetailResponse(
            attempt=ExecutionAttemptResponse.model_validate(value["attempt"]),
            order_status=value["order_status"],
            order_transitions=transitions,
            fills=[FillResponse.model_validate(item) for item in value["fills"]],
            total_fee=value["total_fee"],
            integrity_issues=[
                IntegrityIssueResponse.model_validate(item) for item in value["integrity_issues"]
            ],
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


async def _fill_page(
    request: Request,
    *,
    account_id: UUID | None,
    instrument_id: UUID | None,
    order_id: UUID | None,
    side: str | None,
    executed_from: datetime | None,
    executed_to: datetime | None,
    page: int,
    page_size: int,
) -> FillPageResponse:
    result = cast(
        dict[str, Any],
        await SimulatedExecutionQueryService(uow_factory(request)).list_fills(
            account_id=account_id,
            instrument_id=instrument_id,
            order_id=order_id,
            side=side,
            executed_from=executed_from,
            executed_to=executed_to,
            page=page,
            page_size=page_size,
        ),
    )
    return FillPageResponse(
        items=[FillResponse.model_validate(item) for item in result["items"]],
        page=page,
        page_size=page_size,
        total=int(result["total"]),
    )


@router.get("/fills", response_model=FillPageResponse)
async def list_fills(
    request: Request,
    account_id: UUID | None = None,
    instrument_id: UUID | None = None,
    order_id: UUID | None = None,
    side: str | None = None,
    executed_from: datetime | None = None,
    executed_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> FillPageResponse:
    try:
        return await _fill_page(
            request,
            account_id=account_id,
            instrument_id=instrument_id,
            order_id=order_id,
            side=side,
            executed_from=executed_from,
            executed_to=executed_to,
            page=page,
            page_size=page_size,
        )
    except (ApplicationError, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, ApplicationError)
            else ApplicationError("BROKER_EXECUTION_INVALID_REQUEST", str(exc))
        )
        raise to_app_error(error) from exc


@router.get("/fills/{fill_id}", response_model=FillResponse)
async def get_fill(request: Request, fill_id: UUID) -> FillResponse:
    try:
        value = await SimulatedExecutionQueryService(uow_factory(request)).fill_detail(fill_id)
        return FillResponse.model_validate(value)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/orders/{order_id}/fills", response_model=FillPageResponse)
async def list_order_fills(
    request: Request,
    order_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> FillPageResponse:
    try:
        return await _fill_page(
            request,
            account_id=None,
            instrument_id=None,
            order_id=order_id,
            side=None,
            executed_from=None,
            executed_to=None,
            page=page,
            page_size=page_size,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get(
    "/orders/{order_id}/simulated-execution-integrity",
    response_model=IntegrityReportResponse,
)
async def verify_simulated_execution(request: Request, order_id: UUID) -> IntegrityReportResponse:
    try:
        issues = await SimulatedExecutionIntegrityService(uow_factory(request)).verify_order(
            order_id
        )
        return IntegrityReportResponse(
            order_id=order_id,
            valid=not issues,
            issues=[IntegrityIssueResponse.model_validate(item) for item in issues],
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
