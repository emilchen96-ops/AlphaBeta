"""Public API contracts for the M05 manual-order fact pipeline."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


def _decimal_string(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    raise ValueError("decimal values must be JSON strings")


class OrderCreateBody(BaseModel):
    account_id: UUID
    instrument_id: UUID
    side: str
    order_type: str
    time_in_force: str = "DAY"
    requested_quantity: str
    limit_price: str | None = None
    expires_at: datetime | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=1024)

    _strict_quantity = field_validator("requested_quantity", mode="before")(_decimal_string)
    _strict_price = field_validator("limit_price", mode="before")(_decimal_string)

    @model_validator(mode="after")
    def validate_aware_expiry(self) -> Self:
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return self


class OrderActionBody(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_order_version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=1024)


class OrderCancelBody(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_order_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=1024)


class OrderResponse(BaseModel):
    id: str
    account_id: str
    account_name: str | None
    instrument_id: str
    symbol: str | None
    exchange: str | None
    instrument_name: str | None
    side: str
    order_type: str
    time_in_force: str
    requested_quantity: str
    limit_price: str | None
    estimated_notional: str | None
    status: str
    intent_source: str
    row_version: int
    confirmation_required: bool
    correlation_id: str
    expires_at: datetime | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    expired_at: datetime | None
    created_at: datetime
    updated_at: datetime
    capabilities: dict[str, bool]
    warnings: list[str]
    commands: list[dict[str, Any]]
    outbox: list[dict[str, Any]]
    actions: list[dict[str, Any]] = Field(default_factory=list)


class OrderPageResponse(BaseModel):
    items: list[OrderResponse]
    page: int
    page_size: int
    total: int


class TimelineItemResponse(BaseModel):
    kind: str
    label: str
    actor_type: str | None
    actor_id: str | None
    reason: str | None
    order_version: int | None
    occurred_at: datetime
    correlation_id: str
