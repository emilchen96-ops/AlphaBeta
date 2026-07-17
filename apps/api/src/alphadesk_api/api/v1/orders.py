"""M05 manual-order APIs; facts remain local and are never dispatched here."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.orders import (
    CancelOrderRequest,
    ConfirmOrderRequest,
    CreateOrderRequest,
    OrderCancellationService,
    OrderConfirmationService,
    OrderQueryService,
)
from alphadesk_api.application.risk import ConfiguredRiskLimitsProvider, RiskGatedOrderService
from alphadesk_api.schemas.orders import (
    OrderActionBody,
    OrderCancelBody,
    OrderCreateBody,
    OrderPageResponse,
    OrderResponse,
    TimelineItemResponse,
)
from alphadesk_domain.enums import RiskDecisionType

router = APIRouter(prefix="/orders", tags=["manual-orders"])


def _decimal(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ApplicationError(f"ORDER_INVALID_{field.upper()}", f"{field} is invalid") from exc
    if not result.is_finite():
        raise ApplicationError(f"ORDER_INVALID_{field.upper()}", f"{field} must be finite")
    return result


async def _detail(request: Request, order_id: UUID) -> OrderResponse:
    value = await OrderQueryService(uow_factory(request)).detail(order_id)
    return OrderResponse.model_validate(value)


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(request: Request, body: OrderCreateBody) -> OrderResponse:
    try:
        quantity = _decimal(body.requested_quantity, "quantity")
        assert quantity is not None
        outcome = await RiskGatedOrderService(
            uow_factory(request), ConfiguredRiskLimitsProvider(request.app.state.settings)
        ).create(
            CreateOrderRequest(
                account_id=body.account_id,
                instrument_id=body.instrument_id,
                side=body.side,
                order_type=body.order_type,
                time_in_force=body.time_in_force,
                quantity=quantity,
                limit_price=_decimal(body.limit_price, "price"),
                expires_at=body.expires_at,
                idempotency_key=body.idempotency_key,
                note=body.note,
                correlation_id=request_correlation_id(request),
                occurred_at=datetime.now(UTC),
            )
        )
        if outcome.decision.overall_decision is RiskDecisionType.REJECT:
            raise ApplicationError(
                "RISK_ORDER_REJECTED",
                "order intent was rejected by risk control",
                details={"risk_decision_id": str(outcome.decision.id)},
            )
        if outcome.decision.overall_decision is RiskDecisionType.REQUIRE_CONFIRMATION:
            raise ApplicationError(
                "RISK_ORDER_REVIEW_REQUIRED",
                "risk decision requires review and no order was created",
                details={"risk_decision_id": str(outcome.decision.id)},
            )
        assert outcome.order is not None
        detail = (await _detail(request, outcome.order.id)).model_dump()
        detail["risk_decision_id"] = str(outcome.decision.id)
        detail["risk_decision"] = "PASS"
        return OrderResponse.model_validate(detail)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("", response_model=OrderPageResponse)
async def list_orders(
    request: Request,
    account_id: UUID | None = None,
    instrument_id: UUID | None = None,
    order_status: Annotated[str | None, Query(alias="status")] = None,
    side: str | None = None,
    order_type: str | None = None,
    intent_source: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> OrderPageResponse:
    try:
        result = await OrderQueryService(uow_factory(request)).list(
            account_id=account_id,
            instrument_id=instrument_id,
            status=order_status,
            side=side,
            order_type=order_type,
            intent_source=intent_source,
            created_from=created_from,
            created_to=created_to,
            page=page,
            page_size=page_size,
        )
        return OrderPageResponse(
            items=[OrderResponse.model_validate(item) for item in result["items"]],
            page=int(result["page"]),
            page_size=int(result["page_size"]),
            total=int(result["total"]),
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(request: Request, order_id: UUID) -> OrderResponse:
    try:
        return await _detail(request, order_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{order_id}/timeline", response_model=list[TimelineItemResponse])
async def order_timeline(request: Request, order_id: UUID) -> list[TimelineItemResponse]:
    try:
        items = await OrderQueryService(uow_factory(request)).timeline(order_id)
        return [TimelineItemResponse.model_validate(item) for item in items]
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/{order_id}/confirm", response_model=OrderResponse)
async def confirm_order(request: Request, order_id: UUID, body: OrderActionBody) -> OrderResponse:
    try:
        order = await OrderConfirmationService(uow_factory(request)).confirm(
            ConfirmOrderRequest(
                order_id=order_id,
                idempotency_key=body.idempotency_key,
                expected_order_version=body.expected_order_version,
                note=body.note,
                correlation_id=request_correlation_id(request),
                occurred_at=datetime.now(UTC),
            )
        )
        return await _detail(request, order.id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(request: Request, order_id: UUID, body: OrderCancelBody) -> OrderResponse:
    try:
        order = await OrderCancellationService(uow_factory(request)).cancel(
            CancelOrderRequest(
                order_id=order_id,
                idempotency_key=body.idempotency_key,
                expected_order_version=body.expected_order_version,
                reason=body.reason,
                correlation_id=request_correlation_id(request),
                occurred_at=datetime.now(UTC),
            )
        )
        return await _detail(request, order.id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
