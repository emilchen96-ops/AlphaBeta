"""R01 risk decision, active-limit and research-assessment APIs."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Query, Request

from alphadesk_api.api.v1.market_common import (
    request_correlation_id,
    to_app_error,
    uow_factory,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.risk import (
    ConfiguredRiskLimitsProvider,
    RiskDecisionQueryService,
    SignalRiskAssessmentService,
)
from alphadesk_api.schemas.risk import (
    ActiveRiskLimitsResponse,
    RiskDecisionPageResponse,
    RiskDecisionResponse,
    SignalRiskAssessmentBody,
)

router = APIRouter(tags=["risk"])


def _decimal(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ApplicationError("RISK_INVALID_INPUT", f"{field} is invalid") from exc
    if not result.is_finite() or result <= 0:
        raise ApplicationError("RISK_INVALID_INPUT", f"{field} must be positive and finite")
    return result


@router.get("/risk-decisions", response_model=RiskDecisionPageResponse)
async def list_risk_decisions(
    request: Request,
    account_id: UUID | None = None,
    instrument_id: UUID | None = None,
    source_type: str | None = None,
    source_id: UUID | None = None,
    overall_decision: str | None = None,
    order_id: UUID | None = None,
    has_order: bool | None = None,
    evaluated_from: datetime | None = None,
    evaluated_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> RiskDecisionPageResponse:
    try:
        value = await RiskDecisionQueryService(uow_factory(request)).list(
            account_id=account_id,
            instrument_id=instrument_id,
            source_type=source_type,
            source_id=source_id,
            decision=overall_decision,
            order_id=order_id,
            has_order=has_order,
            evaluated_from=evaluated_from,
            evaluated_to=evaluated_to,
            page=page,
            page_size=page_size,
        )
        return RiskDecisionPageResponse.model_validate(value)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/risk-decisions/{decision_id}", response_model=RiskDecisionResponse)
async def get_risk_decision(request: Request, decision_id: UUID) -> RiskDecisionResponse:
    try:
        value = await RiskDecisionQueryService(uow_factory(request)).detail(decision_id)
        return RiskDecisionResponse.model_validate(value)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/risk-limits/active", response_model=ActiveRiskLimitsResponse)
async def active_risk_limits(request: Request) -> ActiveRiskLimitsResponse:
    provider = ConfiguredRiskLimitsProvider(request.app.state.settings)
    limits = provider.get_limits(UUID(int=0))
    return ActiveRiskLimitsResponse(
        max_order_notional=None
        if limits.max_order_notional is None
        else str(limits.max_order_notional),
        max_instrument_weight=None
        if limits.max_instrument_weight is None
        else str(limits.max_instrument_weight),
        max_total_exposure=None
        if limits.max_total_exposure is None
        else str(limits.max_total_exposure),
        max_orders_per_window=limits.max_orders_per_window,
        order_frequency_window_seconds=limits.order_frequency_window_seconds,
        allow_market_orders=limits.allow_market_orders,
        require_reference_price_for_market_order=(limits.require_reference_price_for_market_order),
        kill_switch_enabled=limits.kill_switch_enabled,
        configuration_source="服务端权威配置",
        effective_at=getattr(request.app.state, "started_at", datetime.now(UTC)),
        warnings=["当前页面只读 / 修改限制需通过本地服务端配置并重新加载服务。"],
    )


@router.post("/signals/{signal_id}/risk-assessments", response_model=RiskDecisionResponse)
async def assess_signal_risk(
    request: Request, signal_id: UUID, body: SignalRiskAssessmentBody
) -> RiskDecisionResponse:
    try:
        outcome = await SignalRiskAssessmentService(
            uow_factory(request), ConfiguredRiskLimitsProvider(request.app.state.settings)
        ).assess(
            signal_id,
            body.account_id,
            body.idempotency_key,
            request_correlation_id(request),
            quantity=_decimal(body.quantity, "quantity"),
            reference_price=_decimal(body.reference_price, "reference_price"),
        )
        value = await RiskDecisionQueryService(uow_factory(request)).detail(outcome.decision.id)
        return RiskDecisionResponse.model_validate(value)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
