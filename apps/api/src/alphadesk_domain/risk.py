"""Pure-Python, deterministic lightweight risk evaluation for R01-A."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from uuid import UUID

from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    OrderSide,
    OrderType,
    RiskDecisionType,
)

ZERO = Decimal("0")
ONE = Decimal("1")


class RiskError(ValueError):
    """Controlled domain error carrying a safe machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RiskRequestSource(StrEnum):
    MANUAL_ORDER = "MANUAL_ORDER"
    STRATEGY_SIGNAL = "STRATEGY_SIGNAL"
    SYSTEM = "SYSTEM"


class RiskSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


type RiskScalar = str | int | bool | Decimal | None


def _utc(value: datetime, field_name: str, code: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RiskError(code, f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _decimal(value: Decimal, field_name: str, code: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise RiskError(code, f"{field_name} must be Decimal")
    if not value.is_finite():
        raise RiskError(code, f"{field_name} must be finite")
    return value


def _immutable_metadata(value: Mapping[str, RiskScalar]) -> Mapping[str, RiskScalar]:
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, (str, int, bool, Decimal, type(None))):
            raise RiskError("RISK_INVALID_REQUEST", "risk metadata must contain scalar values")
        if isinstance(item, Decimal) and not item.is_finite():
            raise RiskError("RISK_INVALID_REQUEST", "risk metadata Decimal values must be finite")
    return MappingProxyType(dict(sorted(value.items())))


def _serialized(value: RiskScalar) -> str | int | bool | None:
    if isinstance(value, Decimal):
        return str(value)
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskRequest:
    request_id: UUID
    correlation_id: UUID
    source_type: RiskRequestSource
    account_id: UUID
    instrument_id: UUID
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    requested_at: datetime
    source_id: UUID | None = None
    limit_price: Decimal | None = None
    reference_price: Decimal | None = None
    strategy_key: str | None = None
    signal_id: UUID | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        code = "RISK_INVALID_REQUEST"
        quantity = _decimal(self.quantity, "quantity", code)
        if quantity <= ZERO:
            raise RiskError(code, "quantity must be positive")
        if self.limit_price is not None:
            _decimal(self.limit_price, "limit_price", code)
        if self.reference_price is not None:
            reference = _decimal(self.reference_price, "reference_price", code)
            if reference <= ZERO:
                raise RiskError(code, "reference_price must be positive")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise RiskError(code, "LIMIT request requires limit_price")
        if self.order_type is OrderType.MARKET and self.limit_price is not None:
            raise RiskError(code, "MARKET request must not carry limit_price")
        if self.schema_version != 1:
            raise RiskError(code, "unsupported risk request schema version")
        object.__setattr__(self, "requested_at", _utc(self.requested_at, "requested_at", code))


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskPositionSnapshot:
    instrument_id: UUID
    quantity: Decimal
    sellable_quantity: Decimal
    market_value: Decimal
    reference_price: Decimal | None = None

    def __post_init__(self) -> None:
        code = "RISK_INVALID_ACCOUNT_SNAPSHOT"
        for name in ("quantity", "sellable_quantity", "market_value"):
            value = _decimal(getattr(self, name), name, code)
            if value < ZERO:
                raise RiskError(code, f"{name} must be non-negative")
        if self.sellable_quantity > self.quantity:
            raise RiskError(code, "sellable_quantity must not exceed quantity")
        if self.reference_price is not None:
            price = _decimal(self.reference_price, "reference_price", code)
            if price <= ZERO:
                raise RiskError(code, "reference_price must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskAccountSnapshot:
    account_id: UUID
    account_type: AccountType
    account_status: AccountStatus
    cash_available: Decimal
    cash_total: Decimal
    market_value: Decimal
    total_equity: Decimal
    positions: tuple[RiskPositionSnapshot, ...]
    open_order_count: int
    recent_order_timestamps: tuple[datetime, ...]
    kill_switch_enabled: bool
    snapshot_at: datetime

    def __post_init__(self) -> None:
        code = "RISK_INVALID_ACCOUNT_SNAPSHOT"
        for name in ("cash_available", "cash_total", "market_value"):
            value = _decimal(getattr(self, name), name, code)
            if value < ZERO:
                raise RiskError(code, f"{name} must be non-negative")
        _decimal(self.total_equity, "total_equity", code)
        if self.cash_available > self.cash_total:
            raise RiskError(code, "cash_available must not exceed cash_total")
        if self.open_order_count < 0:
            raise RiskError(code, "open_order_count must be non-negative")
        identifiers = [position.instrument_id for position in self.positions]
        if len(identifiers) != len(set(identifiers)):
            raise RiskError(code, "position instrument identifiers must be unique")
        object.__setattr__(self, "positions", tuple(self.positions))
        timestamps = tuple(
            sorted(
                _utc(value, "recent_order_timestamps", code)
                for value in self.recent_order_timestamps
            )
        )
        object.__setattr__(self, "recent_order_timestamps", timestamps)
        object.__setattr__(self, "snapshot_at", _utc(self.snapshot_at, "snapshot_at", code))

    def position_for(self, instrument_id: UUID) -> RiskPositionSnapshot | None:
        return next(
            (position for position in self.positions if position.instrument_id == instrument_id),
            None,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskInstrumentSnapshot:
    instrument_id: UUID
    symbol: str
    exchange: str
    active: bool
    lot_size: Decimal
    price_tick: Decimal
    snapshot_at: datetime
    reference_price: Decimal | None = None

    def __post_init__(self) -> None:
        code = "RISK_INVALID_INSTRUMENT_SNAPSHOT"
        if not self.symbol.strip() or not self.exchange.strip():
            raise RiskError(code, "symbol and exchange must not be empty")
        for name in ("lot_size", "price_tick"):
            value = _decimal(getattr(self, name), name, code)
            if value <= ZERO:
                raise RiskError(code, f"{name} must be positive")
        if self.reference_price is not None:
            price = _decimal(self.reference_price, "reference_price", code)
            if price <= ZERO:
                raise RiskError(code, "reference_price must be positive")
        object.__setattr__(self, "snapshot_at", _utc(self.snapshot_at, "snapshot_at", code))


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskLimits:
    max_order_notional: Decimal | None = None
    max_instrument_weight: Decimal | None = None
    max_total_exposure: Decimal | None = None
    max_orders_per_window: int | None = None
    order_frequency_window_seconds: int = 60
    allow_market_orders: bool = False
    require_reference_price_for_market_order: bool = True
    kill_switch_enabled: bool = False

    def __post_init__(self) -> None:
        code = "RISK_INVALID_LIMITS"
        if self.max_order_notional is not None:
            value = _decimal(self.max_order_notional, "max_order_notional", code)
            if value <= ZERO:
                raise RiskError(code, "max_order_notional must be positive")
        for name in ("max_instrument_weight", "max_total_exposure"):
            value = getattr(self, name)
            if value is not None:
                ratio = _decimal(value, name, code)
                if not ZERO <= ratio <= ONE:
                    raise RiskError(code, f"{name} must be between zero and one")
        if self.max_orders_per_window is not None and self.max_orders_per_window <= 0:
            raise RiskError(code, "max_orders_per_window must be positive")
        if self.order_frequency_window_seconds <= 0:
            raise RiskError(code, "order_frequency_window_seconds must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskRuleResult:
    rule_key: str
    decision: RiskDecisionType
    reason_code: str
    message: str
    severity: RiskSeverity
    evaluated_at: datetime
    observed_value: RiskScalar = None
    limit_value: RiskScalar = None
    metadata: Mapping[str, RiskScalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rule_key.strip() or not self.reason_code.strip() or not self.message.strip():
            raise RiskError("RISK_INVALID_REQUEST", "risk rule result text must not be empty")
        object.__setattr__(
            self,
            "evaluated_at",
            _utc(self.evaluated_at, "evaluated_at", "RISK_INVALID_REQUEST"),
        )
        object.__setattr__(self, "metadata", _immutable_metadata(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_key": self.rule_key,
            "decision": self.decision.value,
            "reason_code": self.reason_code,
            "message": self.message,
            "severity": self.severity.value,
            "observed_value": _serialized(self.observed_value),
            "limit_value": _serialized(self.limit_value),
            "metadata": {key: _serialized(value) for key, value in self.metadata.items()},
            "evaluated_at": self.evaluated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskEvaluationResult:
    request_id: UUID
    overall_decision: RiskDecisionType
    rule_results: tuple[RiskRuleResult, ...]
    evaluated_at: datetime
    estimated_notional: Decimal | None = None
    projected_instrument_weight: Decimal | None = None
    projected_total_exposure: Decimal | None = None
    warnings: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise RiskError("RISK_INVALID_REQUEST", "unsupported risk result schema version")
        object.__setattr__(
            self,
            "evaluated_at",
            _utc(self.evaluated_at, "evaluated_at", "RISK_INVALID_REQUEST"),
        )
        object.__setattr__(self, "rule_results", tuple(self.rule_results))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        for name in (
            "estimated_notional",
            "projected_instrument_weight",
            "projected_total_exposure",
        ):
            value = getattr(self, name)
            if value is not None:
                _decimal(value, name, "RISK_INVALID_REQUEST")


@runtime_checkable
class RiskRule(Protocol):
    rule_key: str
    priority: int

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult: ...


def _result(
    rule: RiskRule,
    request: RiskRequest,
    decision: RiskDecisionType = RiskDecisionType.ALLOW,
    reason_code: str = "RISK_RULE_PASSED",
    message: str = "risk rule passed",
    *,
    observed: RiskScalar = None,
    limit: RiskScalar = None,
    metadata: Mapping[str, RiskScalar] | None = None,
) -> RiskRuleResult:
    severity = (
        RiskSeverity.CRITICAL
        if decision is RiskDecisionType.REJECT
        else RiskSeverity.WARNING
        if decision is RiskDecisionType.REQUIRE_CONFIRMATION
        else RiskSeverity.INFO
    )
    return RiskRuleResult(
        rule_key=rule.rule_key,
        decision=decision,
        reason_code=reason_code,
        message=message,
        severity=severity,
        observed_value=observed,
        limit_value=limit,
        metadata=metadata or {},
        evaluated_at=request.requested_at,
    )


def _selected_price(request: RiskRequest, instrument: RiskInstrumentSnapshot) -> Decimal | None:
    if request.order_type is OrderType.LIMIT:
        return request.limit_price
    return request.reference_price or instrument.reference_price


def _estimated_notional(request: RiskRequest, instrument: RiskInstrumentSnapshot) -> Decimal | None:
    price = _selected_price(request, instrument)
    return None if price is None or price <= ZERO else request.quantity * price


class AccountEligibilityRule:
    rule_key = "account_eligibility"
    priority = 10

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if account.account_id != request.account_id:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_ACCOUNT_NOT_ELIGIBLE",
                "account snapshot does not match request",
            )
        if account.account_type is not AccountType.SIMULATED:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_ACCOUNT_NOT_ELIGIBLE",
                "only simulated accounts are eligible",
                observed=account.account_type.value,
                limit=AccountType.SIMULATED.value,
            )
        if account.account_status is not AccountStatus.ACTIVE:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_ACCOUNT_NOT_ELIGIBLE",
                "account must be active",
                observed=account.account_status.value,
                limit=AccountStatus.ACTIVE.value,
            )
        return _result(self, request)


class InstrumentEligibilityRule:
    rule_key = "instrument_eligibility"
    priority = 20

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if instrument.instrument_id != request.instrument_id or not instrument.active:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_INSTRUMENT_NOT_ELIGIBLE",
                "instrument is missing, mismatched, or inactive",
            )
        if instrument.lot_size <= ZERO or instrument.price_tick <= ZERO:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_INSTRUMENT_NOT_ELIGIBLE",
                "instrument trading units are invalid",
            )
        return _result(self, request)


class KillSwitchRule:
    rule_key = "kill_switch"
    priority = 30

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if account.kill_switch_enabled:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_KILL_SWITCH_ENABLED",
                "account kill switch is enabled",
                metadata={"scope": "ACCOUNT"},
            )
        if limits.kill_switch_enabled:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_KILL_SWITCH_ENABLED",
                "configured kill switch is enabled",
                metadata={"scope": "LIMITS"},
            )
        return _result(self, request)


class OrderStructureRule:
    rule_key = "order_structure"
    priority = 40

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if request.quantity <= ZERO or request.quantity % instrument.lot_size != ZERO:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_ORDER_STRUCTURE_INVALID",
                "quantity must be positive and aligned to lot_size",
                observed=request.quantity,
                limit=instrument.lot_size,
            )
        if request.order_type is OrderType.LIMIT:
            price = request.limit_price
            if price is None or price <= ZERO or price % instrument.price_tick != ZERO:
                return _result(
                    self,
                    request,
                    RiskDecisionType.REJECT,
                    "RISK_ORDER_STRUCTURE_INVALID",
                    "limit price must be positive and aligned to price_tick",
                    observed=price,
                    limit=instrument.price_tick,
                )
        elif not limits.allow_market_orders:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_ORDER_STRUCTURE_INVALID",
                "market orders are disabled",
            )
        return _result(self, request)


class EstimatedNotionalRule:
    rule_key = "estimated_notional"
    priority = 50

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        price = _selected_price(request, instrument)
        if price is None:
            decision = (
                RiskDecisionType.REJECT
                if limits.require_reference_price_for_market_order
                else RiskDecisionType.REQUIRE_CONFIRMATION
            )
            return _result(
                self,
                request,
                decision,
                "RISK_REFERENCE_PRICE_REQUIRED",
                "reference price is unavailable for notional estimation",
            )
        if price <= ZERO:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_REFERENCE_PRICE_REQUIRED",
                "estimation price must be positive",
                observed=price,
            )
        notional = request.quantity * price
        return _result(self, request, observed=notional, metadata={"selected_price": price})


class AvailableCashRule:
    rule_key = "available_cash"
    priority = 60

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if request.side is OrderSide.SELL:
            return _result(self, request)
        notional = _estimated_notional(request, instrument)
        if notional is None:
            return _result(
                self,
                request,
                RiskDecisionType.REQUIRE_CONFIRMATION,
                "RISK_REFERENCE_PRICE_REQUIRED",
                "cash check requires an estimated notional",
            )
        if notional > account.cash_available:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_INSUFFICIENT_CASH",
                "available cash is below estimated notional",
                observed=notional,
                limit=account.cash_available,
            )
        return _result(self, request, observed=notional, limit=account.cash_available)


class SellablePositionRule:
    rule_key = "sellable_position"
    priority = 70

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if request.side is OrderSide.BUY:
            return _result(self, request)
        position = account.position_for(request.instrument_id)
        sellable = ZERO if position is None else position.sellable_quantity
        if request.quantity > sellable:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_INSUFFICIENT_POSITION",
                "sellable position is insufficient; naked short selling is not supported",
                observed=request.quantity,
                limit=sellable,
            )
        return _result(self, request, observed=request.quantity, limit=sellable)


class MaxOrderNotionalRule:
    rule_key = "max_order_notional"
    priority = 80

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if limits.max_order_notional is None:
            return _result(self, request)
        notional = _estimated_notional(request, instrument)
        if notional is None:
            return _result(
                self,
                request,
                RiskDecisionType.REQUIRE_CONFIRMATION,
                "RISK_REFERENCE_PRICE_REQUIRED",
                "order notional limit requires an estimation price",
            )
        if notional > limits.max_order_notional:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_MAX_ORDER_NOTIONAL_EXCEEDED",
                "estimated notional exceeds order limit",
                observed=notional,
                limit=limits.max_order_notional,
            )
        return _result(self, request, observed=notional, limit=limits.max_order_notional)


def _projected_market_value(
    request: RiskRequest, account: RiskAccountSnapshot, instrument: RiskInstrumentSnapshot
) -> Decimal | None:
    notional = _estimated_notional(request, instrument)
    if notional is None:
        return None
    position = account.position_for(request.instrument_id)
    current = ZERO if position is None else position.market_value
    if request.side is OrderSide.BUY:
        return current + notional
    return max(ZERO, current - notional)


class MaxInstrumentWeightRule:
    rule_key = "max_instrument_weight"
    priority = 90

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if limits.max_instrument_weight is None:
            return _result(self, request)
        if account.total_equity <= ZERO:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_EQUITY_NOT_POSITIVE",
                "positive total equity is required for weight calculation",
                observed=account.total_equity,
            )
        projected = _projected_market_value(request, account, instrument)
        if projected is None:
            return _result(
                self,
                request,
                RiskDecisionType.REQUIRE_CONFIRMATION,
                "RISK_REFERENCE_PRICE_REQUIRED",
                "instrument weight requires an estimation price",
            )
        weight = projected / account.total_equity
        if weight > limits.max_instrument_weight:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_MAX_INSTRUMENT_WEIGHT_EXCEEDED",
                "projected instrument weight exceeds limit",
                observed=weight,
                limit=limits.max_instrument_weight,
            )
        return _result(self, request, observed=weight, limit=limits.max_instrument_weight)


class MaxTotalExposureRule:
    rule_key = "max_total_exposure"
    priority = 100

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if limits.max_total_exposure is None:
            return _result(self, request)
        if account.total_equity <= ZERO:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_EQUITY_NOT_POSITIVE",
                "positive total equity is required for exposure calculation",
                observed=account.total_equity,
            )
        notional = _estimated_notional(request, instrument)
        if notional is None:
            return _result(
                self,
                request,
                RiskDecisionType.REQUIRE_CONFIRMATION,
                "RISK_REFERENCE_PRICE_REQUIRED",
                "total exposure requires an estimation price",
            )
        projected = (
            account.market_value + notional
            if request.side is OrderSide.BUY
            else max(ZERO, account.market_value - notional)
        )
        exposure = projected / account.total_equity
        if exposure > limits.max_total_exposure:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_MAX_TOTAL_EXPOSURE_EXCEEDED",
                "projected total exposure exceeds limit",
                observed=exposure,
                limit=limits.max_total_exposure,
            )
        return _result(self, request, observed=exposure, limit=limits.max_total_exposure)


class OrderFrequencyRule:
    rule_key = "order_frequency"
    priority = 110

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        if limits.max_orders_per_window is None:
            return _result(self, request)
        lower = request.requested_at - timedelta(seconds=limits.order_frequency_window_seconds)
        count = sum(
            lower < timestamp <= request.requested_at
            for timestamp in account.recent_order_timestamps
        )
        if count >= limits.max_orders_per_window:
            return _result(
                self,
                request,
                RiskDecisionType.REJECT,
                "RISK_ORDER_FREQUENCY_EXCEEDED",
                "order frequency has reached its configured limit",
                observed=count,
                limit=limits.max_orders_per_window,
                metadata={"window_seconds": limits.order_frequency_window_seconds},
            )
        return _result(self, request, observed=count, limit=limits.max_orders_per_window)


CORE_RISK_RULES: tuple[RiskRule, ...] = (
    AccountEligibilityRule(),
    InstrumentEligibilityRule(),
    KillSwitchRule(),
    OrderStructureRule(),
    EstimatedNotionalRule(),
    AvailableCashRule(),
    SellablePositionRule(),
    MaxOrderNotionalRule(),
    MaxInstrumentWeightRule(),
    MaxTotalExposureRule(),
    OrderFrequencyRule(),
)


def _overall(results: Sequence[RiskRuleResult]) -> RiskDecisionType:
    if any(result.decision is RiskDecisionType.REJECT for result in results):
        return RiskDecisionType.REJECT
    if any(result.decision is RiskDecisionType.REQUIRE_CONFIRMATION for result in results):
        return RiskDecisionType.REQUIRE_CONFIRMATION
    return RiskDecisionType.ALLOW


class RuleBasedRiskEvaluator:
    """Stable sequential evaluator. Exceptions are converted to controlled review results."""

    def __init__(self, rules: Sequence[RiskRule] = CORE_RISK_RULES) -> None:
        self._rules: dict[str, RiskRule] = {}
        for rule in rules:
            self.register(rule)

    def register(self, rule: RiskRule) -> None:
        if rule.rule_key in self._rules:
            raise RiskError("RISK_RULE_ALREADY_REGISTERED", "risk rule key is already registered")
        self._rules[rule.rule_key] = rule

    @property
    def rules(self) -> tuple[RiskRule, ...]:
        return tuple(sorted(self._rules.values(), key=lambda rule: (rule.priority, rule.rule_key)))

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskEvaluationResult:
        results: list[RiskRuleResult] = []
        for rule in self.rules:
            try:
                results.append(rule.evaluate(request, account, instrument, limits))
            except Exception:
                results.append(
                    _result(
                        rule,
                        request,
                        RiskDecisionType.REQUIRE_CONFIRMATION,
                        "RISK_RULE_EXECUTION_FAILED",
                        "risk rule execution failed; manual review is required",
                    )
                )
        notional = _estimated_notional(request, instrument)
        projected_instrument = _projected_market_value(request, account, instrument)
        instrument_weight = (
            None
            if projected_instrument is None or account.total_equity <= ZERO
            else projected_instrument / account.total_equity
        )
        projected_exposure = None
        if notional is not None and account.total_equity > ZERO:
            exposure_value = (
                account.market_value + notional
                if request.side is OrderSide.BUY
                else max(ZERO, account.market_value - notional)
            )
            projected_exposure = exposure_value / account.total_equity
        return RiskEvaluationResult(
            request_id=request.request_id,
            overall_decision=_overall(results),
            rule_results=tuple(results),
            evaluated_at=request.requested_at,
            estimated_notional=notional,
            projected_instrument_weight=instrument_weight,
            projected_total_exposure=projected_exposure,
        )


class PassThroughRiskEvaluator:
    """Explicit non-production compatibility evaluator with a visible bypass warning."""

    def __init__(self, environment: str) -> None:
        if environment.lower() not in {"test", "development"}:
            raise RiskError(
                "RISK_PASSTHROUGH_NOT_ALLOWED",
                "pass-through risk is restricted to test and development",
            )

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskEvaluationResult:
        return RiskEvaluationResult(
            request_id=request.request_id,
            overall_decision=RiskDecisionType.ALLOW,
            rule_results=(),
            evaluated_at=request.requested_at,
            warnings=("RISK_RULES_BYPASSED",),
        )
