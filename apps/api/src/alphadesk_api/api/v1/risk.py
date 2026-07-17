"""Read-only risk decision queries."""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from alphadesk_api.api.v1.market_common import to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.risk import RiskDecisionQueryService
from alphadesk_api.schemas.risk import RiskDecisionPageResponse, RiskDecisionResponse

router = APIRouter(prefix="/risk-decisions", tags=["risk-decisions"])


@router.get("", response_model=RiskDecisionPageResponse)
async def list_risk_decisions(
    request: Request,
    account_id: UUID | None = None,
    instrument_id: UUID | None = None,
    source_type: str | None = None,
    source_id: UUID | None = None,
    decision: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> RiskDecisionPageResponse:
    try:
        value = await RiskDecisionQueryService(uow_factory(request)).list(
            account_id=account_id,
            instrument_id=instrument_id,
            source_type=source_type,
            source_id=source_id,
            decision=decision,
            page=page,
            page_size=page_size,
        )
        return RiskDecisionPageResponse.model_validate(value)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{decision_id}", response_model=RiskDecisionResponse)
async def get_risk_decision(request: Request, decision_id: UUID) -> RiskDecisionResponse:
    try:
        value = await RiskDecisionQueryService(uow_factory(request)).detail(decision_id)
        return RiskDecisionResponse.model_validate(value)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
