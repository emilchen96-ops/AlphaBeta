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


class SettlementPolicy(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    T_PLUS_ONE = "T_PLUS_ONE"


class LedgerTransactionType(StrEnum):
    INITIAL_DEPOSIT = "INITIAL_DEPOSIT"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY_FILL = "BUY_FILL"
    SELL_FILL = "SELL_FILL"
    CASH_ADJUSTMENT = "CASH_ADJUSTMENT"
    POSITION_ADJUSTMENT = "POSITION_ADJUSTMENT"
    REVERSAL = "REVERSAL"


class LedgerTransactionStatus(StrEnum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class CashLedgerEntryType(StrEnum):
    INITIAL_DEPOSIT = "INITIAL_DEPOSIT"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY_SETTLEMENT = "BUY_SETTLEMENT"
    SELL_SETTLEMENT = "SELL_SETTLEMENT"
    COMMISSION = "COMMISSION"
    TAX = "TAX"
    OTHER_FEE = "OTHER_FEE"
    FREEZE = "FREEZE"
    RELEASE = "RELEASE"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"


class PositionLedgerEntryType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    FREEZE = "FREEZE"
    RELEASE = "RELEASE"
    SETTLEMENT = "SETTLEMENT"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"


class AccountValuationStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"
    FAILED = "FAILED"


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


class OrderIntentSource(StrEnum):
    MANUAL = "MANUAL"
    STRATEGY = "STRATEGY"
    SCANNER = "SCANNER"
    AI = "AI"
    SYSTEM = "SYSTEM"


class OrderActionType(StrEnum):
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"


class OrderActorType(StrEnum):
    LOCAL_USER = "LOCAL_USER"
    SYSTEM = "SYSTEM"
    RISK_ENGINE = "RISK_ENGINE"
    EXECUTOR = "EXECUTOR"
    BROKER = "BROKER"
    RECONCILIATION = "RECONCILIATION"


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
    SUBMIT_ORDER = "SUBMIT_ORDER"
    CANCEL = "CANCEL"


class CommandStatus(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    SUPPRESSED = "SUPPRESSED"
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


class MarketProviderTier(StrEnum):
    DEMO = "DEMO"
    FREE_BEST_EFFORT = "FREE_BEST_EFFORT"


class MarketProviderUsage(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    NON_TRADING_GRADE = "NON_TRADING_GRADE"


class RealtimeRunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIALLY_SUCCEEDED = "PARTIALLY_SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED_NOT_LEADER = "SKIPPED_NOT_LEADER"
    DISABLED = "DISABLED"


class ProviderCapabilityStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class QuoteUpdateType(StrEnum):
    SNAPSHOT = "SNAPSHOT"
    UPDATE = "UPDATE"


class SubscriptionReason(StrEnum):
    WATCHLIST = "WATCHLIST"
    POSITION = "POSITION"
    CLIENT = "CLIENT"


class QuoteFreshnessStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"


class SyncTriggerType(StrEnum):
    MANUAL = "MANUAL"
    CLI = "CLI"
    SCHEDULED = "SCHEDULED"
    SYSTEM = "SYSTEM"
