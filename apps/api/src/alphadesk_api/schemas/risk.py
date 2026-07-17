"""Read-only R01 risk API contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RiskDecisionResponse(BaseModel):
    model_config = {"extra": "allow"}

    id: str
    idempotency_key: str
    request_fingerprint: str
    request_id: str
    source_type: str
    account_id: str
    instrument_id: str
    overall_decision: str
    order_id: str | None
    warnings: list[str]
    rule_results: list[dict[str, Any]]


class ActiveRiskLimitsResponse(BaseModel):
    max_order_notional: str | None
    max_instrument_weight: str | None
    max_total_exposure: str | None
    max_orders_per_window: int | None
    order_frequency_window_seconds: int
    allow_market_orders: bool
    require_reference_price_for_market_order: bool
    kill_switch_enabled: bool
    configuration_source: str
    effective_at: datetime
    warnings: list[str]


class SignalRiskAssessmentBody(BaseModel):
    account_id: UUID
    quantity: str | None = None
    reference_price: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("quantity", "reference_price", mode="before")
    @classmethod
    def decimal_strings_only(cls, value: Any) -> Any:
        if value is None or isinstance(value, str):
            return value
        raise ValueError("decimal values must be JSON strings")


class RiskDecisionPageResponse(BaseModel):
    items: list[RiskDecisionResponse]
    page: int
    page_size: int
    total: int
