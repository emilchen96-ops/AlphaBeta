"""Pure Python domain entities for the M02 persistence foundation."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    AccountValuationStatus,
    CommandStatus,
    CommandType,
    ExecutorDeviceStatus,
    ExecutorPermission,
    OrderSide,
    OrderStatus,
    OrderType,
    OutboxStatus,
    RiskDecisionType,
    RiskLayer,
    SettlementPolicy,
    SignalStatus,
    SignalType,
    StrategyStatus,
    TimeInForce,
)
from alphadesk_domain.values import as_utc, decimal_value, non_empty, utc_now

JsonObject = dict[str, Any]


@dataclass(slots=True, kw_only=True)
class Instrument:
    symbol: str
    exchange: str
    market: str
    name: str
    asset_type: str
    currency: str
    lot_size: Decimal
    price_tick: Decimal
    timezone: str
    id: UUID = field(default_factory=uuid4)
    is_active: bool = True
    listed_at: date | None = None
    delisted_at: date | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.symbol = non_empty(self.symbol, "symbol")
        self.exchange = non_empty(self.exchange, "exchange")
        decimal_value(self.lot_size, "lot_size")
        decimal_value(self.price_tick, "price_tick")
        if self.lot_size <= 0 or self.price_tick <= 0:
            raise ValueError("lot_size and price_tick must be positive")
        if (
            self.listed_at is not None
            and self.delisted_at is not None
            and self.delisted_at < self.listed_at
        ):
            raise ValueError("delisted_at must not precede listed_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class Watchlist:
    name: str
    id: UUID = field(default_factory=uuid4)
    description: str | None = None
    realtime_enabled: bool = False
    items: tuple["WatchlistItem", ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.name = non_empty(self.name, "name")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class WatchlistItem:
    watchlist_id: UUID
    instrument_id: UUID
    id: UUID = field(default_factory=uuid4)
    sort_order: int = 0
    note: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.sort_order < 0:
            raise ValueError("sort_order must be non-negative")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class TradingAccount:
    account_code: str
    name: str
    account_type: AccountType
    status: AccountStatus
    broker_type: str
    base_currency: str
    id: UUID = field(default_factory=uuid4)
    settlement_policy: SettlementPolicy = SettlementPolicy.IMMEDIATE
    creation_idempotency_key: str | None = None
    external_account_reference: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.account_code = non_empty(self.account_code, "account_code")
        self.name = non_empty(self.name, "name")
        self.base_currency = non_empty(self.base_currency, "base_currency").upper()
        if self.creation_idempotency_key is not None:
            self.creation_idempotency_key = non_empty(
                self.creation_idempotency_key, "creation_idempotency_key"
            )
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class Position:
    account_id: UUID
    instrument_id: UUID
    total_quantity: Decimal
    available_quantity: Decimal
    frozen_quantity: Decimal
    unsettled_quantity: Decimal
    cost_basis: Decimal
    average_cost: Decimal
    market_value: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    last_price: Decimal | None
    last_price_at: datetime | None
    valuation_status: AccountValuationStatus
    as_of: datetime
    id: UUID = field(default_factory=uuid4)
    row_version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        quantities = (
            self.total_quantity,
            self.available_quantity,
            self.frozen_quantity,
            self.unsettled_quantity,
        )
        for name, value in zip(
            (
                "total_quantity",
                "available_quantity",
                "frozen_quantity",
                "unsettled_quantity",
            ),
            quantities,
            strict=True,
        ):
            decimal_value(value, name)
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("cost_basis", "average_cost", "realized_pnl"):
            value = decimal_value(getattr(self, name), name)
            if name != "realized_pnl" and value < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in ("market_value", "unrealized_pnl", "last_price"):
            value = getattr(self, name)
            if value is not None:
                decimal_value(value, name)
        if self.last_price is not None and self.last_price <= 0:
            raise ValueError("last_price must be positive")
        if (
            self.available_quantity + self.frozen_quantity + self.unsettled_quantity
            != self.total_quantity
        ):
            raise ValueError("position quantity components must equal total quantity")
        if self.total_quantity == 0 and (self.cost_basis != 0 or self.average_cost != 0):
            raise ValueError("closed position cost basis and average cost must be zero")
        if self.row_version < 1:
            raise ValueError("row_version must be at least one")
        self.as_of = as_utc(self.as_of, "as_of")
        if self.last_price_at is not None:
            self.last_price_at = as_utc(self.last_price_at, "last_price_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class Strategy:
    strategy_code: str
    name: str
    status: StrategyStatus
    id: UUID = field(default_factory=uuid4)
    description: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.strategy_code = non_empty(self.strategy_code, "strategy_code")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class StrategyVersion:
    strategy_id: UUID
    version_number: int
    source_hash: str
    code_reference: str
    id: UUID = field(default_factory=uuid4)
    parameter_schema: JsonObject = field(default_factory=dict)
    default_parameters: JsonObject = field(default_factory=dict)
    is_active: bool = False
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.version_number < 1:
            raise ValueError("version_number must be at least one")
        self.source_hash = non_empty(self.source_hash, "source_hash")
        self.code_reference = non_empty(self.code_reference, "code_reference")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class Signal:
    strategy_id: UUID | None
    strategy_version_id: UUID | None
    account_id: UUID | None
    instrument_id: UUID
    signal_type: SignalType
    side: OrderSide
    generated_at: datetime
    valid_until: datetime
    status: SignalStatus
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    target_quantity: Decimal | None = None
    target_weight: Decimal | None = None
    reference_price: Decimal | None = None
    reason: str | None = None
    causation_id: UUID | None = None
    payload: JsonObject = field(default_factory=dict)
    strategy_run_id: UUID | None = None
    sequence_number: int | None = None
    strategy_key: str | None = None
    strategy_version: str | None = None
    bar_timestamp: datetime | None = None
    confidence: Decimal | None = None
    metadata: JsonObject = field(default_factory=dict)
    schema_version: int = 1
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.target_quantity is not None and self.target_weight is not None:
            raise ValueError("target_quantity and target_weight are mutually exclusive")
        if self.target_quantity is not None:
            decimal_value(self.target_quantity, "target_quantity")
            if self.target_quantity <= 0:
                raise ValueError("target_quantity must be positive")
        if self.target_weight is not None:
            decimal_value(self.target_weight, "target_weight")
            if not Decimal("0") <= self.target_weight <= Decimal("1"):
                raise ValueError("target_weight must be between zero and one")
        if self.reference_price is not None:
            decimal_value(self.reference_price, "reference_price")
            if self.reference_price <= 0:
                raise ValueError("reference_price must be positive")
        if self.confidence is not None:
            decimal_value(self.confidence, "confidence")
            if not Decimal("0") <= self.confidence <= Decimal("1"):
                raise ValueError("confidence must be between zero and one")
        if self.sequence_number is not None and self.sequence_number < 1:
            raise ValueError("sequence_number must be positive")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        self.generated_at = as_utc(self.generated_at, "generated_at")
        if self.bar_timestamp is not None:
            self.bar_timestamp = as_utc(self.bar_timestamp, "bar_timestamp")
        self.valid_until = as_utc(self.valid_until, "valid_until")
        if self.valid_until <= self.generated_at:
            raise ValueError("valid_until must be later than generated_at")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class RiskDecision:
    idempotency_key: str
    request_fingerprint: str
    request_id: UUID
    source_type: str
    account_id: UUID
    instrument_id: UUID
    overall_decision: RiskDecisionType
    correlation_id: UUID
    evaluated_at: datetime
    id: UUID = field(default_factory=uuid4)
    source_id: UUID | None = None
    signal_id: UUID | None = None
    order_id: UUID | None = None
    estimated_notional: Decimal | None = None
    projected_instrument_weight: Decimal | None = None
    projected_total_exposure: Decimal | None = None
    limits_snapshot: JsonObject = field(default_factory=dict)
    account_snapshot: JsonObject = field(default_factory=dict)
    instrument_snapshot: JsonObject = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    layer: RiskLayer = RiskLayer.BACKEND
    schema_version: int = 1
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.idempotency_key = non_empty(self.idempotency_key, "idempotency_key")
        self.request_fingerprint = non_empty(self.request_fingerprint, "request_fingerprint")
        self.source_type = non_empty(self.source_type, "source_type")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        for name in (
            "estimated_notional",
            "projected_instrument_weight",
            "projected_total_exposure",
        ):
            value = getattr(self, name)
            if value is not None:
                decimal_value(value, name)
        self.evaluated_at = as_utc(self.evaluated_at, "evaluated_at")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class RiskRuleEvaluation:
    risk_decision_id: UUID
    seq: int
    rule_key: str
    decision: RiskDecisionType
    reason_code: str
    message: str
    severity: str
    evaluated_at: datetime
    id: UUID = field(default_factory=uuid4)
    observed_value: str | int | bool | None = None
    limit_value: str | int | bool | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.seq < 1:
            raise ValueError("risk rule sequence must be positive")
        for name in ("rule_key", "reason_code", "message", "severity"):
            setattr(self, name, non_empty(getattr(self, name), name))
        self.evaluated_at = as_utc(self.evaluated_at, "evaluated_at")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class Order:
    account_id: UUID
    instrument_id: UUID
    side: OrderSide
    order_type: OrderType
    time_in_force: TimeInForce
    requested_quantity: Decimal
    status: OrderStatus
    idempotency_key: str
    broker_type: str
    correlation_id: UUID
    intent_source: str = "MANUAL"
    request_fingerprint: str = ""
    row_version: int = 1
    confirmation_required: bool = True
    id: UUID = field(default_factory=uuid4)
    strategy_id: UUID | None = None
    strategy_version_id: UUID | None = None
    signal_id: UUID | None = None
    filled_quantity: Decimal = Decimal("0")
    limit_price: Decimal | None = None
    average_fill_price: Decimal | None = None
    broker_order_id: str | None = None
    expires_at: datetime | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    expired_at: datetime | None = None
    created_by_actor_type: str = "LOCAL_USER"
    created_by_actor_id: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        decimal_value(self.requested_quantity, "requested_quantity")
        decimal_value(self.filled_quantity, "filled_quantity")
        if self.requested_quantity <= 0:
            raise ValueError("requested_quantity must be positive")
        if self.filled_quantity < 0 or self.filled_quantity > self.requested_quantity:
            raise ValueError("filled_quantity is outside the requested range")
        if self.limit_price is not None:
            decimal_value(self.limit_price, "limit_price")
            if self.limit_price <= 0:
                raise ValueError("limit_price must be positive")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT order requires limit_price")
        if self.average_fill_price is not None:
            decimal_value(self.average_fill_price, "average_fill_price")
        self.idempotency_key = non_empty(self.idempotency_key, "idempotency_key")
        # Legacy M02 fixtures predate request fingerprints; M05 services always
        # supply a SHA-256 value, while old persisted records remain readable.
        self.request_fingerprint = self.request_fingerprint or f"legacy:{self.idempotency_key}"
        if self.row_version < 1:
            raise ValueError("row_version must be at least one")
        for name in (
            "expires_at",
            "submitted_at",
            "completed_at",
            "confirmed_at",
            "cancelled_at",
            "expired_at",
        ):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, as_utc(value, name))
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class OrderStateTransition:
    order_id: UUID
    to_status: OrderStatus
    actor_type: str
    correlation_id: UUID
    occurred_at: datetime
    id: int | None = None
    from_status: OrderStatus | None = None
    actor_id: str | None = None
    reason_code: str | None = None
    reason: str | None = None
    order_version: int = 1
    action_id: UUID | None = None
    command_id: UUID | None = None
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.occurred_at = as_utc(self.occurred_at, "occurred_at")
        if self.order_version < 1:
            raise ValueError("order_version must be at least one")


@dataclass(slots=True, kw_only=True)
class OrderAction:
    order_id: UUID
    action_type: str
    idempotency_key: str
    request_fingerprint: str
    actor_type: str
    expected_order_version: int
    applied_order_version: int
    correlation_id: UUID
    occurred_at: datetime
    id: UUID = field(default_factory=uuid4)
    actor_id: str | None = None
    applied_transition_id: int | None = None
    note: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.idempotency_key = non_empty(self.idempotency_key, "idempotency_key")
        self.request_fingerprint = non_empty(self.request_fingerprint, "request_fingerprint")
        if (
            self.expected_order_version < 1
            or self.applied_order_version < self.expected_order_version
        ):
            raise ValueError("invalid order action version")
        self.occurred_at = as_utc(self.occurred_at, "occurred_at")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class OrderCommand:
    command_id: UUID
    order_id: UUID
    command_type: CommandType
    status: CommandStatus
    sequence_number: int
    payload_hash: str
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    target_device_id: UUID | None = None
    payload: JsonObject = field(default_factory=dict)
    signature_reference: str | None = None
    acknowledged_at: datetime | None = None
    consumed_at: datetime | None = None
    consumed_by: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.sequence_number < 0:
            raise ValueError("sequence_number must be non-negative")
        self.created_at = as_utc(self.created_at, "created_at")
        self.expires_at = as_utc(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.acknowledged_at is not None:
            self.acknowledged_at = as_utc(self.acknowledged_at, "acknowledged_at")
        if self.consumed_at is not None:
            self.consumed_at = as_utc(self.consumed_at, "consumed_at")
        if (self.consumed_at is None) != (self.consumed_by is None):
            raise ValueError("consumed_at and consumed_by must be supplied together")
        if (self.status is CommandStatus.CONSUMED) != (self.consumed_at is not None):
            raise ValueError("CONSUMED status must match consumption fields")
        if self.consumed_by is not None:
            self.consumed_by = non_empty(self.consumed_by, "consumed_by")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class Fill:
    order_id: UUID
    account_id: UUID
    instrument_id: UUID
    broker_type: str
    quantity: Decimal
    price: Decimal
    gross_amount: Decimal
    commission: Decimal
    tax: Decimal
    other_fee: Decimal
    net_amount: Decimal
    executed_at: datetime
    received_at: datetime
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    broker_fill_id: str | None = None
    execution_attempt_id: UUID | None = None
    command_id: UUID | None = None
    sequence_number: int | None = None
    execution_reference: str | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        amount_fields = (
            "quantity",
            "price",
            "gross_amount",
            "commission",
            "tax",
            "other_fee",
            "net_amount",
        )
        for name in amount_fields:
            decimal_value(getattr(self, name), name)
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("fill quantity and price must be positive")
        if any(value < 0 for value in (self.commission, self.tax, self.other_fee)):
            raise ValueError("fill fees must be non-negative")
        if self.sequence_number is not None and self.sequence_number < 1:
            raise ValueError("fill sequence_number must be positive")
        execution_links = (
            self.execution_attempt_id,
            self.command_id,
            self.sequence_number,
            self.execution_reference,
        )
        if any(item is not None for item in execution_links) and any(
            item is None for item in execution_links
        ):
            raise ValueError("fill execution link fields must be supplied together")
        if self.execution_reference is not None:
            self.execution_reference = non_empty(self.execution_reference, "execution_reference")
        self.executed_at = as_utc(self.executed_at, "executed_at")
        self.received_at = as_utc(self.received_at, "received_at")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class DomainEvent:
    event_id: UUID
    event_type: str
    entity_type: str
    entity_id: UUID
    source: str
    event_time: datetime
    received_time: datetime
    correlation_id: UUID
    schema_version: int
    payload: JsonObject
    sequence: int | None = None
    processed_time: datetime | None = None
    causation_id: UUID | None = None
    metadata: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.schema_version < 1:
            raise ValueError("schema_version must be at least one")
        self.event_time = as_utc(self.event_time, "event_time")
        self.received_time = as_utc(self.received_time, "received_time")
        if self.processed_time is not None:
            self.processed_time = as_utc(self.processed_time, "processed_time")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class AuditLog:
    actor_type: str
    action: str
    resource_type: str
    outcome: str
    correlation_id: UUID
    occurred_at: datetime
    id: int | None = None
    actor_id: str | None = None
    resource_id: UUID | None = None
    details: JsonObject = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.occurred_at = as_utc(self.occurred_at, "occurred_at")
        self.created_at = as_utc(self.created_at, "created_at")


@dataclass(slots=True, kw_only=True)
class OutboxMessage:
    event_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    topic: str
    payload: JsonObject
    status: OutboxStatus
    available_at: datetime
    id: UUID = field(default_factory=uuid4)
    headers: JsonObject = field(default_factory=dict)
    attempts: int = 0
    published_at: datetime | None = None
    suppressed_at: datetime | None = None
    suppression_reason: str | None = None
    last_error: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.attempts < 0:
            raise ValueError("attempts must be non-negative")
        self.available_at = as_utc(self.available_at, "available_at")
        if self.published_at is not None:
            self.published_at = as_utc(self.published_at, "published_at")
        if self.suppressed_at is not None:
            self.suppressed_at = as_utc(self.suppressed_at, "suppressed_at")
        if (self.suppressed_at is None) != (self.suppression_reason is None):
            raise ValueError("suppressed_at and suppression_reason must be supplied together")
        if (self.status is OutboxStatus.SUPPRESSED) != (self.suppressed_at is not None):
            raise ValueError("SUPPRESSED status must match suppression fields")
        if self.suppression_reason is not None:
            self.suppression_reason = non_empty(self.suppression_reason, "suppression_reason")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class ExecutorDevice:
    device_code: str
    name: str
    status: ExecutorDeviceStatus
    public_key_fingerprint: str
    id: UUID = field(default_factory=uuid4)
    capabilities: JsonObject = field(default_factory=dict)
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.device_code = non_empty(self.device_code, "device_code")
        self.public_key_fingerprint = non_empty(
            self.public_key_fingerprint, "public_key_fingerprint"
        )
        for name in ("last_seen_at", "revoked_at"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, as_utc(value, name))
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(slots=True, kw_only=True)
class ExecutorDeviceAccount:
    device_id: UUID
    account_id: UUID
    permission: ExecutorPermission
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.created_at = as_utc(self.created_at, "created_at")
