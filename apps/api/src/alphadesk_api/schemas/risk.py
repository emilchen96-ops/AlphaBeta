"""Read-only R01-B risk decision API schemas."""

from typing import Any

from pydantic import BaseModel


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


class RiskDecisionPageResponse(BaseModel):
    items: list[RiskDecisionResponse]
    page: int
    page_size: int
    total: int
