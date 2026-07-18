"""B01-C HTTP contracts for local simulated execution and read-only Fill facts."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alphadesk_domain.broker import BrokerExecutionStatus, TradingStatus
from alphadesk_domain.enums import OrderSide, OrderStatus


def _decimal_string(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    raise ValueError("decimal values must be JSON strings")


class SimulatedExecutionBody(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    trading_status: TradingStatus = TradingStatus.TRADING
    open: str | None = None
    high: str | None = None
    low: str | None = None
    close: str | None = None
    last_price: str | None = None
    bid_price: str | None = None
    ask_price: str | None = None
    available_volume: str | None = None
    price_limit_up: str | None = None
    price_limit_down: str | None = None
    source: str = Field(min_length=1, max_length=128)
    is_stale: bool = False

    _strict_decimal = field_validator(
        "open",
        "high",
        "low",
        "close",
        "last_price",
        "bid_price",
        "ask_price",
        "available_volume",
        "price_limit_up",
        "price_limit_down",
        mode="before",
    )(_decimal_string)

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return self


class ExecutionAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_number: int
    result_status: BrokerExecutionStatus
    input_order_status: OrderStatus
    requested_quantity: Decimal
    previously_filled_quantity: Decimal
    attempted_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_fill_price: Decimal | None
    rejection_code: str | None
    message: str
    market_snapshot: dict[str, Any]
    account_snapshot: dict[str, Any] | None = None
    fee_model_version: str
    slippage_model_version: str
    correlation_id: UUID
    started_at: datetime
    completed_at: datetime


class SimulatedExecutionResultResponse(BaseModel):
    execution_attempt_id: UUID
    order_id: UUID
    order_status: OrderStatus
    result_status: BrokerExecutionStatus
    requested_quantity: Decimal
    previously_filled_quantity: Decimal
    attempted_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_fill_price: Decimal | None
    fill_ids: list[UUID]
    total_fee: Decimal
    rejection_code: str | None
    message: str
    warnings: list[str]
    correlation_id: UUID
    idempotent: bool


class ExecutionAttemptPageResponse(BaseModel):
    items: list[ExecutionAttemptResponse]
    page: int
    page_size: int
    total: int


class FillResponse(BaseModel):
    fill_id: UUID
    execution_attempt_id: UUID | None
    order_id: UUID
    account: dict[str, Any]
    instrument: dict[str, Any]
    side: OrderSide
    quantity: Decimal
    price: Decimal
    gross_amount: Decimal
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    other_fee: Decimal
    total_fee: Decimal
    net_cash_effect: Decimal
    executed_at: datetime
    execution_reference: str | None
    correlation_id: UUID


class FillPageResponse(BaseModel):
    items: list[FillResponse]
    page: int
    page_size: int
    total: int


class IntegrityIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: UUID
    code: str
    message: str
    execution_attempt_id: UUID | None
    fill_id: UUID | None


class IntegrityReportResponse(BaseModel):
    order_id: UUID
    valid: bool
    issues: list[IntegrityIssueResponse]


class ExecutionDetailResponse(BaseModel):
    attempt: ExecutionAttemptResponse
    order_status: OrderStatus
    order_transitions: list[dict[str, Any]]
    fills: list[FillResponse]
    total_fee: Decimal
    integrity_issues: list[IntegrityIssueResponse]
