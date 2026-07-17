"""Pure deterministic broker contracts and simulated execution for B01-A."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    OrderSide,
    OrderType,
    TimeInForce,
)
from alphadesk_domain.values import as_utc, decimal_value, non_empty

ZERO = Decimal("0")
ONE = Decimal("1")
BASIS_POINT_DENOMINATOR = Decimal("10000")
DEFAULT_CURRENCY_QUANTUM = Decimal("0.01")


class BrokerExecutionMode(StrEnum):
    SIMULATED = "SIMULATED"


class TradingStatus(StrEnum):
    TRADING = "TRADING"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class BrokerExecutionStatus(StrEnum):
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    NO_FILL = "NO_FILL"


class BrokerErrorCode(StrEnum):
    INVALID_REQUEST = "BROKER_INVALID_REQUEST"
    ACCOUNT_NOT_SUPPORTED = "BROKER_ACCOUNT_NOT_SUPPORTED"
    ACCOUNT_NOT_ACTIVE = "BROKER_ACCOUNT_NOT_ACTIVE"
    INSTRUMENT_MISMATCH = "BROKER_INSTRUMENT_MISMATCH"
    MARKET_NOT_TRADING = "BROKER_MARKET_NOT_TRADING"
    MARKET_DATA_STALE = "BROKER_MARKET_DATA_STALE"
    ORDER_EXPIRED = "BROKER_ORDER_EXPIRED"
    MARKET_PRICE_UNAVAILABLE = "BROKER_MARKET_PRICE_UNAVAILABLE"
    LIMIT_NOT_MARKETABLE = "BROKER_LIMIT_NOT_MARKETABLE"
    INSUFFICIENT_CASH = "BROKER_INSUFFICIENT_CASH"
    INSUFFICIENT_POSITION = "BROKER_INSUFFICIENT_POSITION"
    PRICE_LIMIT_VIOLATION = "BROKER_PRICE_LIMIT_VIOLATION"
    NO_AVAILABLE_VOLUME = "BROKER_NO_AVAILABLE_VOLUME"
    INVALID_FEE_CONFIGURATION = "BROKER_INVALID_FEE_CONFIGURATION"
    INVALID_SLIPPAGE_CONFIGURATION = "BROKER_INVALID_SLIPPAGE_CONFIGURATION"
    EXECUTION_FAILED = "BROKER_EXECUTION_FAILED"


class BrokerDomainError(ValueError):
    """Controlled configuration or contract error with a stable safe code."""

    def __init__(self, code: BrokerErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _positive(value: Decimal, name: str) -> Decimal:
    decimal_value(value, name)
    if value <= ZERO:
        raise BrokerDomainError(BrokerErrorCode.INVALID_REQUEST, f"{name} must be positive")
    return value


def _non_negative(value: Decimal, name: str) -> Decimal:
    decimal_value(value, name)
    if value < ZERO:
        raise BrokerDomainError(BrokerErrorCode.INVALID_REQUEST, f"{name} must be non-negative")
    return value


def _optional_positive(value: Decimal | None, name: str) -> Decimal | None:
    if value is not None:
        _positive(value, name)
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class BrokerMetadata:
    broker_key: str
    display_name: str
    version: str
    execution_mode: BrokerExecutionMode
    supported_order_types: tuple[OrderType, ...]
    supported_time_in_force: tuple[TimeInForce, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "broker_key", non_empty(self.broker_key, "broker_key"))
        object.__setattr__(self, "display_name", non_empty(self.display_name, "display_name"))
        object.__setattr__(self, "version", non_empty(self.version, "version"))
        if self.schema_version < 1:
            raise BrokerDomainError(
                BrokerErrorCode.INVALID_REQUEST, "schema_version must be at least one"
            )
        if not self.supported_order_types or not self.supported_time_in_force:
            raise BrokerDomainError(
                BrokerErrorCode.INVALID_REQUEST, "broker capabilities must not be empty"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class BrokerOrderRequest:
    command_id: UUID
    order_id: UUID
    account_id: UUID
    instrument_id: UUID
    symbol: str
    exchange: str
    side: OrderSide
    order_type: OrderType
    time_in_force: TimeInForce
    quantity: Decimal
    submitted_at: datetime
    correlation_id: UUID
    limit_price: Decimal | None = None
    expires_at: datetime | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", non_empty(self.symbol, "symbol"))
        object.__setattr__(self, "exchange", non_empty(self.exchange, "exchange"))
        _positive(self.quantity, "quantity")
        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise BrokerDomainError(
                    BrokerErrorCode.INVALID_REQUEST, "LIMIT order requires limit_price"
                )
            _positive(self.limit_price, "limit_price")
        elif self.limit_price is not None:
            raise BrokerDomainError(
                BrokerErrorCode.INVALID_REQUEST, "MARKET order must not carry limit_price"
            )
        submitted_at = as_utc(self.submitted_at, "submitted_at")
        object.__setattr__(self, "submitted_at", submitted_at)
        if self.expires_at is not None:
            expires_at = as_utc(self.expires_at, "expires_at")
            if expires_at <= submitted_at:
                raise BrokerDomainError(
                    BrokerErrorCode.INVALID_REQUEST, "expires_at must be later than submitted_at"
                )
            object.__setattr__(self, "expires_at", expires_at)
        if self.schema_version != 1:
            raise BrokerDomainError(
                BrokerErrorCode.INVALID_REQUEST, "unsupported broker request schema_version"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionMarketSnapshot:
    instrument_id: UUID
    timestamp: datetime
    trading_status: TradingStatus
    source: str
    is_stale: bool
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    last_price: Decimal | None = None
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    available_volume: Decimal | None = None
    price_limit_up: Decimal | None = None
    price_limit_down: Decimal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", as_utc(self.timestamp, "timestamp"))
        object.__setattr__(self, "source", non_empty(self.source, "source"))
        for name in (
            "open",
            "high",
            "low",
            "close",
            "last_price",
            "bid_price",
            "ask_price",
            "price_limit_up",
            "price_limit_down",
        ):
            _optional_positive(getattr(self, name), name)
        if self.available_volume is not None:
            _non_negative(self.available_volume, "available_volume")
        ohlc = (self.open, self.high, self.low, self.close)
        if any(value is not None for value in ohlc):
            if any(value is None for value in ohlc):
                raise BrokerDomainError(
                    BrokerErrorCode.INVALID_REQUEST, "OHLC values must be supplied together"
                )
            assert self.open is not None
            assert self.high is not None
            assert self.low is not None
            assert self.close is not None
            if self.low > self.high or not (
                self.low <= self.open <= self.high and self.low <= self.close <= self.high
            ):
                raise BrokerDomainError(
                    BrokerErrorCode.INVALID_REQUEST, "invalid OHLC relationship"
                )
        if (
            self.price_limit_up is not None
            and self.price_limit_down is not None
            and self.price_limit_down > self.price_limit_up
        ):
            raise BrokerDomainError(BrokerErrorCode.INVALID_REQUEST, "price limits are inverted")


@dataclass(frozen=True, slots=True, kw_only=True)
class BrokerAccountSnapshot:
    account_id: UUID
    account_type: AccountType
    account_status: AccountStatus
    cash_available: Decimal
    position_quantity: Decimal
    sellable_quantity: Decimal
    snapshot_at: datetime

    def __post_init__(self) -> None:
        for name in ("cash_available", "position_quantity", "sellable_quantity"):
            _non_negative(getattr(self, name), name)
        if self.sellable_quantity > self.position_quantity:
            raise BrokerDomainError(
                BrokerErrorCode.INVALID_REQUEST,
                "sellable_quantity must not exceed position_quantity",
            )
        object.__setattr__(self, "snapshot_at", as_utc(self.snapshot_at, "snapshot_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class FeeBreakdown:
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    other_fee: Decimal = ZERO

    def __post_init__(self) -> None:
        for name in ("commission", "stamp_duty", "transfer_fee", "other_fee"):
            _non_negative(getattr(self, name), name)

    @property
    def total_fee(self) -> Decimal:
        return self.commission + self.stamp_duty + self.transfer_fee + self.other_fee


class FeeModel(Protocol):
    @property
    def version(self) -> str: ...

    def calculate(self, *, side: OrderSide, quantity: Decimal, price: Decimal) -> FeeBreakdown: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class AshareSimpleFeeModel:
    commission_rate: Decimal = Decimal("0.0003")
    minimum_commission: Decimal = Decimal("5")
    stamp_duty_rate: Decimal = Decimal("0.0005")
    transfer_fee_rate: Decimal = Decimal("0.00001")
    currency_quantum: Decimal = DEFAULT_CURRENCY_QUANTUM
    schema_version: int = 1
    version: str = "ashare-simple-fee-v1"

    def __post_init__(self) -> None:
        try:
            for name in (
                "commission_rate",
                "minimum_commission",
                "stamp_duty_rate",
                "transfer_fee_rate",
            ):
                decimal_value(getattr(self, name), name)
                if getattr(self, name) < ZERO:
                    raise ValueError(f"{name} must be non-negative")
            _positive(self.currency_quantum, "currency_quantum")
        except (TypeError, ValueError) as exc:
            raise BrokerDomainError(BrokerErrorCode.INVALID_FEE_CONFIGURATION, str(exc)) from exc
        if self.schema_version != 1:
            raise BrokerDomainError(
                BrokerErrorCode.INVALID_FEE_CONFIGURATION,
                "unsupported fee model schema_version",
            )
        object.__setattr__(self, "version", non_empty(self.version, "version"))

    def _money(self, value: Decimal) -> Decimal:
        return value.quantize(self.currency_quantum, rounding=ROUND_HALF_UP)

    def calculate(self, *, side: OrderSide, quantity: Decimal, price: Decimal) -> FeeBreakdown:
        _positive(quantity, "quantity")
        _positive(price, "price")
        gross_amount = quantity * price
        commission = self._money(max(gross_amount * self.commission_rate, self.minimum_commission))
        stamp_duty = (
            self._money(gross_amount * self.stamp_duty_rate)
            if side is OrderSide.SELL
            else ZERO.quantize(self.currency_quantum)
        )
        transfer_fee = self._money(gross_amount * self.transfer_fee_rate)
        return FeeBreakdown(
            commission=commission,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
            other_fee=ZERO.quantize(self.currency_quantum),
        )


class SlippageModel(Protocol):
    @property
    def version(self) -> str: ...

    def apply(
        self,
        *,
        side: OrderSide,
        reference_price: Decimal,
        price_limit_up: Decimal | None,
        price_limit_down: Decimal | None,
    ) -> Decimal: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class NoSlippageModel:
    version: str = "no-slippage-v1"

    def apply(
        self,
        *,
        side: OrderSide,
        reference_price: Decimal,
        price_limit_up: Decimal | None,
        price_limit_down: Decimal | None,
    ) -> Decimal:
        del side, price_limit_up, price_limit_down
        return _positive(reference_price, "reference_price")


@dataclass(frozen=True, slots=True, kw_only=True)
class FixedBasisPointsSlippageModel:
    basis_points: Decimal
    maximum_slippage: Decimal | None = None
    version: str = "fixed-bps-slippage-v1"

    def __post_init__(self) -> None:
        try:
            decimal_value(self.basis_points, "basis_points")
            if self.basis_points < ZERO:
                raise ValueError("basis_points must be non-negative")
            if self.maximum_slippage is not None:
                decimal_value(self.maximum_slippage, "maximum_slippage")
                if self.maximum_slippage < ZERO:
                    raise ValueError("maximum_slippage must be non-negative")
        except (TypeError, ValueError) as exc:
            raise BrokerDomainError(
                BrokerErrorCode.INVALID_SLIPPAGE_CONFIGURATION, str(exc)
            ) from exc
        object.__setattr__(self, "version", non_empty(self.version, "version"))

    def apply(
        self,
        *,
        side: OrderSide,
        reference_price: Decimal,
        price_limit_up: Decimal | None,
        price_limit_down: Decimal | None,
    ) -> Decimal:
        _positive(reference_price, "reference_price")
        delta = reference_price * self.basis_points / BASIS_POINT_DENOMINATOR
        if self.maximum_slippage is not None:
            delta = min(delta, self.maximum_slippage)
        adjusted = reference_price + delta if side is OrderSide.BUY else reference_price - delta
        if side is OrderSide.BUY and price_limit_up is not None:
            adjusted = min(adjusted, price_limit_up)
        if side is OrderSide.SELL and price_limit_down is not None:
            adjusted = max(adjusted, price_limit_down)
        if adjusted <= ZERO:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED,
                "slippage produced a non-positive execution price",
            )
        return adjusted


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedExecutionPrice:
    price: Decimal
    source: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionPriceResolver:
    def resolve(
        self, request: BrokerOrderRequest, market: ExecutionMarketSnapshot
    ) -> ResolvedExecutionPrice | None:
        candidates = (
            (
                ("ask_price", market.ask_price),
                ("last_price", market.last_price),
                ("close", market.close),
            )
            if request.side is OrderSide.BUY
            else (
                ("bid_price", market.bid_price),
                ("last_price", market.last_price),
                ("close", market.close),
            )
        )
        for source, price in candidates:
            if price is not None:
                return ResolvedExecutionPrice(price=price, source=source)
        return None

    def is_marketable(self, request: BrokerOrderRequest, reference_price: Decimal) -> bool:
        if request.order_type is OrderType.MARKET:
            return True
        assert request.limit_price is not None
        if request.side is OrderSide.BUY:
            return reference_price <= request.limit_price
        return reference_price >= request.limit_price


@dataclass(frozen=True, slots=True, kw_only=True)
class FillDraft:
    fill_id: UUID
    command_id: UUID
    order_id: UUID
    account_id: UUID
    instrument_id: UUID
    side: OrderSide
    quantity: Decimal
    price: Decimal
    reference_price: Decimal
    reference_price_source: str
    gross_amount: Decimal
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    other_fee: Decimal
    total_fee: Decimal
    net_cash_effect: Decimal
    executed_at: datetime
    execution_reference: str
    sequence_number: int = 1
    schema_version: int = 1

    def __post_init__(self) -> None:
        _positive(self.quantity, "quantity")
        _positive(self.price, "price")
        _positive(self.reference_price, "reference_price")
        for name in (
            "gross_amount",
            "commission",
            "stamp_duty",
            "transfer_fee",
            "other_fee",
            "total_fee",
        ):
            _non_negative(getattr(self, name), name)
        decimal_value(self.net_cash_effect, "net_cash_effect")
        if self.gross_amount != self.quantity * self.price:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "gross_amount does not balance"
            )
        expected_fee = self.commission + self.stamp_duty + self.transfer_fee + self.other_fee
        if self.total_fee != expected_fee:
            raise BrokerDomainError(BrokerErrorCode.EXECUTION_FAILED, "total_fee does not balance")
        expected_cash = (
            -(self.gross_amount + self.total_fee)
            if self.side is OrderSide.BUY
            else self.gross_amount - self.total_fee
        )
        if self.net_cash_effect != expected_cash:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "net_cash_effect does not balance"
            )
        if self.side is OrderSide.BUY and self.net_cash_effect >= ZERO:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "BUY net_cash_effect must be negative"
            )
        if self.side is OrderSide.SELL and self.net_cash_effect <= ZERO:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "SELL net_cash_effect must be positive"
            )
        if self.sequence_number != 1 or self.schema_version != 1:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "unsupported fill draft sequence or schema"
            )
        object.__setattr__(self, "executed_at", as_utc(self.executed_at, "executed_at"))
        object.__setattr__(
            self,
            "execution_reference",
            non_empty(self.execution_reference, "execution_reference"),
        )
        object.__setattr__(
            self,
            "reference_price_source",
            non_empty(self.reference_price_source, "reference_price_source"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BrokerExecutionResult:
    command_id: UUID
    order_id: UUID
    status: BrokerExecutionStatus
    requested_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    average_fill_price: Decimal | None
    fills: tuple[FillDraft, ...]
    rejection_code: str | None
    message: str
    warnings: tuple[str, ...]
    evaluated_at: datetime
    schema_version: int = 1

    def __post_init__(self) -> None:
        _positive(self.requested_quantity, "requested_quantity")
        _non_negative(self.filled_quantity, "filled_quantity")
        _non_negative(self.remaining_quantity, "remaining_quantity")
        if self.filled_quantity + self.remaining_quantity != self.requested_quantity:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "execution quantities do not balance"
            )
        fill_quantity = sum((fill.quantity for fill in self.fills), ZERO)
        if fill_quantity != self.filled_quantity:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "fill quantities do not match result"
            )
        if self.status is BrokerExecutionStatus.REJECTED and self.fills:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "rejected result cannot contain fills"
            )
        if self.status is BrokerExecutionStatus.FILLED and self.remaining_quantity != ZERO:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "filled result must have zero remaining"
            )
        if self.status is BrokerExecutionStatus.PARTIALLY_FILLED and (
            self.filled_quantity <= ZERO or self.remaining_quantity <= ZERO
        ):
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED,
                "partially filled result requires filled and remaining quantities",
            )
        if self.filled_quantity == ZERO and self.average_fill_price is not None:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "empty result cannot have average price"
            )
        if self.filled_quantity > ZERO:
            if self.average_fill_price is None:
                raise BrokerDomainError(
                    BrokerErrorCode.EXECUTION_FAILED, "filled result requires average price"
                )
            _positive(self.average_fill_price, "average_fill_price")
            weighted_price = sum((fill.quantity * fill.price for fill in self.fills), ZERO)
            if weighted_price / self.filled_quantity != self.average_fill_price:
                raise BrokerDomainError(
                    BrokerErrorCode.EXECUTION_FAILED, "average fill price does not balance"
                )
        object.__setattr__(self, "message", non_empty(self.message, "message"))
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at, "evaluated_at"))
        if self.schema_version != 1:
            raise BrokerDomainError(
                BrokerErrorCode.EXECUTION_FAILED, "unsupported execution result schema"
            )


class BrokerAdapter(Protocol):
    metadata: BrokerMetadata

    def submit(
        self,
        request: BrokerOrderRequest,
        market: ExecutionMarketSnapshot,
        account: BrokerAccountSnapshot,
    ) -> BrokerExecutionResult: ...


def _canonical_value(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return as_utc(value, "fingerprint_time").isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    return value


def execution_fingerprint(
    *,
    broker_key: str,
    request: BrokerOrderRequest,
    market: ExecutionMarketSnapshot,
    fee_model_version: str,
    slippage_model_version: str,
) -> str:
    payload = {
        "schema_version": request.schema_version,
        "broker_key": non_empty(broker_key, "broker_key"),
        "command_id": request.command_id,
        "order_id": request.order_id,
        "account_id": request.account_id,
        "instrument_id": request.instrument_id,
        "symbol": request.symbol,
        "exchange": request.exchange,
        "side": request.side,
        "order_type": request.order_type,
        "time_in_force": request.time_in_force,
        "quantity": request.quantity,
        "limit_price": request.limit_price,
        "submitted_at": request.submitted_at,
        "expires_at": request.expires_at,
        "market": asdict(market),
        "fee_model_version": non_empty(fee_model_version, "fee_model_version"),
        "slippage_model_version": non_empty(slippage_model_version, "slippage_model_version"),
    }
    encoded = json.dumps(
        _canonical_value(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatedBrokerAdapter:
    fee_model: FeeModel = field(default_factory=AshareSimpleFeeModel)
    slippage_model: SlippageModel = field(default_factory=NoSlippageModel)
    price_resolver: ExecutionPriceResolver = field(default_factory=ExecutionPriceResolver)
    metadata: BrokerMetadata = field(
        default=BrokerMetadata(
            broker_key="simulated",
            display_name="AlphaDesk Simulated Broker",
            version="1.0.0",
            execution_mode=BrokerExecutionMode.SIMULATED,
            supported_order_types=(OrderType.MARKET, OrderType.LIMIT),
            supported_time_in_force=(
                TimeInForce.DAY,
                TimeInForce.GTC,
                TimeInForce.IOC,
                TimeInForce.FOK,
            ),
        )
    )

    def _empty_result(
        self,
        *,
        request: BrokerOrderRequest,
        status: BrokerExecutionStatus,
        code: BrokerErrorCode,
        message: str,
        evaluated_at: datetime,
    ) -> BrokerExecutionResult:
        return BrokerExecutionResult(
            command_id=request.command_id,
            order_id=request.order_id,
            status=status,
            requested_quantity=request.quantity,
            filled_quantity=ZERO,
            remaining_quantity=request.quantity,
            average_fill_price=None,
            fills=(),
            rejection_code=code.value,
            message=message,
            warnings=(),
            evaluated_at=evaluated_at,
        )

    def submit(
        self,
        request: BrokerOrderRequest,
        market: ExecutionMarketSnapshot,
        account: BrokerAccountSnapshot,
    ) -> BrokerExecutionResult:
        evaluated_at = market.timestamp
        if request.order_type not in self.metadata.supported_order_types or (
            request.time_in_force not in self.metadata.supported_time_in_force
        ):
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.INVALID_REQUEST,
                message="broker does not support the requested order contract",
                evaluated_at=evaluated_at,
            )
        if (
            account.account_id != request.account_id
            or account.account_type is not AccountType.SIMULATED
        ):
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.ACCOUNT_NOT_SUPPORTED,
                message="only the matching simulated account is supported",
                evaluated_at=evaluated_at,
            )
        if account.account_status is not AccountStatus.ACTIVE:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.ACCOUNT_NOT_ACTIVE,
                message="account is not active",
                evaluated_at=evaluated_at,
            )
        if market.instrument_id != request.instrument_id:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.INSTRUMENT_MISMATCH,
                message="market snapshot does not match the requested instrument",
                evaluated_at=evaluated_at,
            )
        if market.trading_status is not TradingStatus.TRADING:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.MARKET_NOT_TRADING,
                message="market is not trading",
                evaluated_at=evaluated_at,
            )
        if market.is_stale:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.MARKET_DATA_STALE,
                message="market snapshot is stale",
                evaluated_at=evaluated_at,
            )
        if request.expires_at is not None and evaluated_at >= request.expires_at:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.EXPIRED,
                code=BrokerErrorCode.ORDER_EXPIRED,
                message="broker request has expired",
                evaluated_at=evaluated_at,
            )
        resolved = self.price_resolver.resolve(request, market)
        if resolved is None:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.MARKET_PRICE_UNAVAILABLE,
                message="no executable market price is available",
                evaluated_at=evaluated_at,
            )
        if not self.price_resolver.is_marketable(request, resolved.price):
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.NO_FILL,
                code=BrokerErrorCode.LIMIT_NOT_MARKETABLE,
                message="limit price is not marketable at the supplied snapshot",
                evaluated_at=evaluated_at,
            )
        execution_price = self.slippage_model.apply(
            side=request.side,
            reference_price=resolved.price,
            price_limit_up=market.price_limit_up,
            price_limit_down=market.price_limit_down,
        )
        if request.order_type is OrderType.LIMIT:
            assert request.limit_price is not None
            execution_price = (
                min(execution_price, request.limit_price)
                if request.side is OrderSide.BUY
                else max(execution_price, request.limit_price)
            )
        if (market.price_limit_up is not None and execution_price > market.price_limit_up) or (
            market.price_limit_down is not None and execution_price < market.price_limit_down
        ):
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.PRICE_LIMIT_VIOLATION,
                message="execution price violates the supplied price limits",
                evaluated_at=evaluated_at,
            )
        if market.available_volume is not None and market.available_volume == ZERO:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.NO_FILL,
                code=BrokerErrorCode.NO_AVAILABLE_VOLUME,
                message="market snapshot has no available volume",
                evaluated_at=evaluated_at,
            )
        if (
            request.time_in_force is TimeInForce.FOK
            and market.available_volume is not None
            and market.available_volume < request.quantity
        ):
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.NO_FILL,
                code=BrokerErrorCode.NO_AVAILABLE_VOLUME,
                message="available volume cannot satisfy the FOK quantity",
                evaluated_at=evaluated_at,
            )
        filled_quantity = (
            request.quantity
            if market.available_volume is None
            else min(request.quantity, market.available_volume)
        )
        fees = self.fee_model.calculate(
            side=request.side, quantity=filled_quantity, price=execution_price
        )
        gross_amount = filled_quantity * execution_price
        required_cash = gross_amount + fees.total_fee
        if request.side is OrderSide.BUY and account.cash_available < required_cash:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.INSUFFICIENT_CASH,
                message="available cash does not cover the fill and fees",
                evaluated_at=evaluated_at,
            )
        if request.side is OrderSide.SELL and account.sellable_quantity < request.quantity:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.INSUFFICIENT_POSITION,
                message="sell quantity exceeds the current sellable quantity",
                evaluated_at=evaluated_at,
            )
        if request.side is OrderSide.SELL and gross_amount <= fees.total_fee:
            return self._empty_result(
                request=request,
                status=BrokerExecutionStatus.REJECTED,
                code=BrokerErrorCode.EXECUTION_FAILED,
                message="sell proceeds do not exceed the calculated fees",
                evaluated_at=evaluated_at,
            )
        fingerprint = execution_fingerprint(
            broker_key=self.metadata.broker_key,
            request=request,
            market=market,
            fee_model_version=self.fee_model.version,
            slippage_model_version=self.slippage_model.version,
        )
        execution_reference = f"SIM-{fingerprint[:24]}"
        fill = FillDraft(
            fill_id=uuid5(NAMESPACE_URL, f"alphadesk:{fingerprint}:fill:1"),
            command_id=request.command_id,
            order_id=request.order_id,
            account_id=request.account_id,
            instrument_id=request.instrument_id,
            side=request.side,
            quantity=filled_quantity,
            price=execution_price,
            reference_price=resolved.price,
            reference_price_source=resolved.source,
            gross_amount=gross_amount,
            commission=fees.commission,
            stamp_duty=fees.stamp_duty,
            transfer_fee=fees.transfer_fee,
            other_fee=fees.other_fee,
            total_fee=fees.total_fee,
            net_cash_effect=(
                -required_cash if request.side is OrderSide.BUY else gross_amount - fees.total_fee
            ),
            executed_at=evaluated_at,
            execution_reference=execution_reference,
        )
        remaining = request.quantity - filled_quantity
        status = (
            BrokerExecutionStatus.FILLED
            if remaining == ZERO
            else BrokerExecutionStatus.PARTIALLY_FILLED
        )
        return BrokerExecutionResult(
            command_id=request.command_id,
            order_id=request.order_id,
            status=status,
            requested_quantity=request.quantity,
            filled_quantity=filled_quantity,
            remaining_quantity=remaining,
            average_fill_price=execution_price,
            fills=(fill,),
            rejection_code=None,
            message=(
                f"simulated fill calculated from {resolved.source}"
                if status is BrokerExecutionStatus.FILLED
                else f"simulated partial fill calculated from {resolved.source}"
            ),
            warnings=(),
            evaluated_at=evaluated_at,
        )
