"""B01-B persisted simulated-execution facts and integrity contracts."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from alphadesk_domain.broker import BrokerExecutionMode, BrokerExecutionStatus
from alphadesk_domain.enums import OrderStatus
from alphadesk_domain.values import as_utc, decimal_value, non_empty, utc_now

JsonObject = dict[str, Any]
ZERO = Decimal("0")


@dataclass(slots=True, kw_only=True)
class BrokerExecutionAttempt:
    """Append-only audit fact for one deterministic simulated Broker call."""

    idempotency_key: str
    request_fingerprint: str
    broker_key: str
    broker_version: str
    execution_mode: BrokerExecutionMode
    order_id: UUID
    command_id: UUID
    account_id: UUID
    instrument_id: UUID
    attempt_number: int
    input_order_status: OrderStatus
    result_status: BrokerExecutionStatus
    requested_quantity: Decimal
    previously_filled_quantity: Decimal
    attempted_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    message: str
    market_snapshot: JsonObject
    account_snapshot: JsonObject
    fee_model_version: str
    slippage_model_version: str
    correlation_id: UUID
    started_at: datetime
    completed_at: datetime
    id: UUID = field(default_factory=uuid4)
    average_fill_price: Decimal | None = None
    rejection_code: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        for name in (
            "idempotency_key",
            "request_fingerprint",
            "broker_key",
            "broker_version",
            "message",
            "fee_model_version",
            "slippage_model_version",
        ):
            setattr(self, name, non_empty(getattr(self, name), name))
        if self.execution_mode is not BrokerExecutionMode.SIMULATED:
            raise ValueError("B01-B execution_mode must be SIMULATED")
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be positive")
        for name in (
            "requested_quantity",
            "previously_filled_quantity",
            "attempted_quantity",
            "filled_quantity",
            "remaining_quantity",
        ):
            decimal_value(getattr(self, name), name)
            if getattr(self, name) < ZERO:
                raise ValueError(f"{name} must be non-negative")
        if self.requested_quantity <= ZERO or self.attempted_quantity <= ZERO:
            raise ValueError("requested and attempted quantities must be positive")
        if self.previously_filled_quantity + self.attempted_quantity != self.requested_quantity:
            raise ValueError("attempted quantity must equal the order remainder")
        if self.filled_quantity > self.attempted_quantity:
            raise ValueError("filled quantity exceeds attempted quantity")
        if (
            self.previously_filled_quantity + self.filled_quantity + self.remaining_quantity
            != self.requested_quantity
        ):
            raise ValueError("execution-attempt quantities do not balance")
        if self.average_fill_price is not None:
            decimal_value(self.average_fill_price, "average_fill_price")
            if self.average_fill_price <= ZERO:
                raise ValueError("average_fill_price must be positive")
        if (self.filled_quantity == ZERO) != (self.average_fill_price is None):
            raise ValueError("average_fill_price must match filled_quantity")
        self.started_at = as_utc(self.started_at, "started_at")
        self.completed_at = as_utc(self.completed_at, "completed_at")
        self.created_at = as_utc(self.created_at, "created_at")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
