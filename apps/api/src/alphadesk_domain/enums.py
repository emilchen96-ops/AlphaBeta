"""Framework-independent AlphaDesk domain enumerations."""

from enum import StrEnum


class AccountType(StrEnum):
    SIMULATED = "SIMULATED"
    CASH = "CASH"
    MARGIN = "MARGIN"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    READ_ONLY = "READ_ONLY"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class StrategyStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class SignalType(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    REBALANCE = "REBALANCE"
    ADVICE = "ADVICE"


class SignalStatus(StrEnum):
    CREATED = "CREATED"
    EVALUATED = "EVALUATED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    RISK_CHECKING = "RISK_CHECKING"
    RISK_REJECTED = "RISK_REJECTED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    EXECUTOR_ACCEPTED = "EXECUTOR_ACCEPTED"
    EXECUTOR_REJECTED = "EXECUTOR_REJECTED"
    BROKER_SUBMITTED = "BROKER_SUBMITTED"
    BROKER_ACCEPTED = "BROKER_ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class RiskLayer(StrEnum):
    BACKEND = "BACKEND"
    EXECUTOR = "EXECUTOR"


class RiskDecisionType(StrEnum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"


class CommandType(StrEnum):
    SUBMIT = "SUBMIT"
    CANCEL = "CANCEL"


class CommandStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class ExecutorDeviceStatus(StrEnum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ExecutorPermission(StrEnum):
    READ_ONLY = "READ_ONLY"
    SIMULATED = "SIMULATED"
    CONTROLLED_LIVE = "CONTROLLED_LIVE"


class MarketDataSourceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEGRADED = "DEGRADED"


class MarketTimeframe(StrEnum):
    MINUTE_1 = "MINUTE_1"
    MINUTE_5 = "MINUTE_5"
    MINUTE_15 = "MINUTE_15"
    MINUTE_30 = "MINUTE_30"
    MINUTE_60 = "MINUTE_60"
    DAY_1 = "DAY_1"
    WEEK_1 = "WEEK_1"
    MONTH_1 = "MONTH_1"


class AdjustmentType(StrEnum):
    NONE = "NONE"
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"


class MarketSyncStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIALLY_SUCCEEDED = "PARTIALLY_SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MarketDataQualityStatus(StrEnum):
    NORMAL = "NORMAL"
    DELAYED = "DELAYED"
    INCOMPLETE = "INCOMPLETE"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class SyncTriggerType(StrEnum):
    MANUAL = "MANUAL"
    CLI = "CLI"
    SCHEDULED = "SCHEDULED"
    SYSTEM = "SYSTEM"
