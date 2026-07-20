"""Deterministic, framework-independent domain model for BT01 daily backtests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from alphadesk_domain.broker import AshareSimpleFeeModel, FixedBasisPointsSlippageModel
from alphadesk_domain.enums import MarketTimeframe, OrderSide, OrderType, TimeInForce
from alphadesk_domain.risk import RiskLimits
from alphadesk_domain.strategy import StrategyEnvironment, StrategyParameterValue
from alphadesk_domain.values import as_utc, decimal_value, non_empty, utc_now

ZERO = Decimal("0")
ONE = Decimal("1")
TRADING_SESSIONS_PER_YEAR = Decimal("252")
BACKTEST_ENGINE_VERSION = "bt01-v1"
ASHARE_TIMEZONE = ZoneInfo("Asia/Shanghai")
EIGHT_PLACES = Decimal("0.00000001")
TWELVE_PLACES = Decimal("0.000000000001")


class BacktestError(ValueError):
    """Controlled BT01 error safe for API/CLI presentation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BacktestRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BacktestPhase(StrEnum):
    SESSION_OPEN = "SESSION_OPEN"
    SESSION_CLOSE = "SESSION_CLOSE"
    SESSION_END = "SESSION_END"


class BacktestEventType(StrEnum):
    RUN_CREATED = "RUN_CREATED"
    RUN_STARTED = "RUN_STARTED"
    SESSION_OPEN = "SESSION_OPEN"
    SESSION_CLOSE = "SESSION_CLOSE"
    SESSION_END = "SESSION_END"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    RISK_DECIDED = "RISK_DECIDED"
    ORDER_CREATED = "ORDER_CREATED"
    EXECUTION_ATTEMPTED = "EXECUTION_ATTEMPTED"
    FILL_GENERATED = "FILL_GENERATED"
    WARNING = "WARNING"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"


def _non_negative(value: Decimal, name: str) -> Decimal:
    decimal_value(value, name)
    if value < ZERO:
        raise BacktestError("BACKTEST_INVALID_CONFIGURATION", f"{name} must be non-negative")
    return value


def _positive(value: Decimal, name: str) -> Decimal:
    decimal_value(value, name)
    if value <= ZERO:
        raise BacktestError("BACKTEST_INVALID_CONFIGURATION", f"{name} must be positive")
    return value


def _q8(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return value.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)


def _q12(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 50
        return value.quantize(TWELVE_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True, kw_only=True)
class BacktestRiskConfigurationSnapshot:
    """Immutable execution-affecting R01 settings captured for reproducibility."""

    reference: str
    limits_version_marker: str
    max_order_notional: Decimal | None
    max_instrument_weight: Decimal | None
    max_total_exposure: Decimal | None
    max_orders_per_window: int | None
    order_frequency_window_seconds: int
    allow_market_orders: bool
    require_reference_price_for_market_order: bool
    kill_switch_enabled: bool
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference", non_empty(self.reference, "risk reference"))
        object.__setattr__(
            self,
            "limits_version_marker",
            non_empty(self.limits_version_marker, "risk limits version marker"),
        )
        if self.schema_version != 1:
            raise BacktestError(
                "BACKTEST_INVALID_CONFIGURATION", "unsupported risk snapshot schema_version"
            )
        try:
            RiskLimits(
                max_order_notional=self.max_order_notional,
                max_instrument_weight=self.max_instrument_weight,
                max_total_exposure=self.max_total_exposure,
                max_orders_per_window=self.max_orders_per_window,
                order_frequency_window_seconds=self.order_frequency_window_seconds,
                allow_market_orders=self.allow_market_orders,
                require_reference_price_for_market_order=(
                    self.require_reference_price_for_market_order
                ),
                kill_switch_enabled=self.kill_switch_enabled,
            )
        except ValueError as exc:
            raise BacktestError("BACKTEST_INVALID_CONFIGURATION", str(exc)) from exc

    def to_limits(self) -> RiskLimits:
        return RiskLimits(
            max_order_notional=self.max_order_notional,
            max_instrument_weight=self.max_instrument_weight,
            max_total_exposure=self.max_total_exposure,
            max_orders_per_window=self.max_orders_per_window,
            order_frequency_window_seconds=self.order_frequency_window_seconds,
            allow_market_orders=self.allow_market_orders,
            require_reference_price_for_market_order=self.require_reference_price_for_market_order,
            kill_switch_enabled=self.kill_switch_enabled,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BacktestConfiguration:
    strategy_key: str
    strategy_version: str
    parameters: Mapping[str, StrategyParameterValue]
    instrument_ids: tuple[UUID, ...]
    timeframe: MarketTimeframe
    start_at: datetime
    end_at: datetime
    initial_cash: Decimal
    order_type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    fee_configuration: AshareSimpleFeeModel = field(default_factory=AshareSimpleFeeModel)
    slippage_configuration: FixedBasisPointsSlippageModel = field(
        default_factory=lambda: FixedBasisPointsSlippageModel(basis_points=ZERO)
    )
    risk_configuration_reference: str = "r01-default-v1"
    risk_configuration_snapshot: BacktestRiskConfigurationSnapshot | None = None
    maximum_volume_participation: Decimal | None = None
    benchmark_symbol: str | None = None
    data_source_code: str = "BAOSTOCK"
    environment: StrategyEnvironment = StrategyEnvironment.BACKTEST
    schema_version: int = 1
    engine_version: str = BACKTEST_ENGINE_VERSION

    def __post_init__(self) -> None:
        strategy_key = non_empty(self.strategy_key, "strategy_key")
        strategy_version = non_empty(self.strategy_version, "strategy_version")
        if self.environment is not StrategyEnvironment.BACKTEST:
            raise BacktestError("BACKTEST_INVALID_CONFIGURATION", "environment must be BACKTEST")
        if self.timeframe is not MarketTimeframe.DAY_1:
            raise BacktestError("BACKTEST_TIMEFRAME_NOT_SUPPORTED", "BT01 only supports DAY_1 bars")
        if self.time_in_force not in (TimeInForce.DAY, TimeInForce.GTC):
            raise BacktestError(
                "BACKTEST_INVALID_CONFIGURATION", "BT01 only supports DAY or GTC orders"
            )
        start_at = as_utc(self.start_at, "start_at")
        end_at = as_utc(self.end_at, "end_at")
        if start_at >= end_at:
            raise BacktestError(
                "BACKTEST_INVALID_TIME_RANGE", "start_at must be earlier than end_at"
            )
        _positive(self.initial_cash, "initial_cash")
        instrument_ids = tuple(sorted(set(self.instrument_ids), key=str))
        if not instrument_ids:
            raise BacktestError(
                "BACKTEST_INVALID_CONFIGURATION", "instrument_ids must not be empty"
            )
        if self.maximum_volume_participation is not None:
            decimal_value(self.maximum_volume_participation, "maximum_volume_participation")
            if not ZERO < self.maximum_volume_participation <= ONE:
                raise BacktestError(
                    "BACKTEST_INVALID_CONFIGURATION",
                    "maximum_volume_participation must be in (0, 1]",
                )
        if self.schema_version != 1:
            raise BacktestError(
                "BACKTEST_INVALID_CONFIGURATION", "unsupported configuration schema_version"
            )
        object.__setattr__(self, "strategy_key", strategy_key)
        object.__setattr__(self, "strategy_version", strategy_version)
        object.__setattr__(self, "parameters", dict(self.parameters))
        object.__setattr__(self, "instrument_ids", instrument_ids)
        object.__setattr__(self, "start_at", start_at)
        object.__setattr__(self, "end_at", end_at)
        object.__setattr__(
            self,
            "risk_configuration_reference",
            non_empty(self.risk_configuration_reference, "risk"),
        )
        if (
            self.risk_configuration_snapshot is not None
            and self.risk_configuration_snapshot.reference != self.risk_configuration_reference
        ):
            raise BacktestError(
                "BACKTEST_INVALID_CONFIGURATION",
                "risk configuration reference does not match its captured settings",
            )
        object.__setattr__(self, "engine_version", non_empty(self.engine_version, "engine_version"))
        object.__setattr__(
            self,
            "data_source_code",
            non_empty(self.data_source_code, "data_source_code").upper(),
        )
        if self.benchmark_symbol is not None:
            object.__setattr__(
                self, "benchmark_symbol", non_empty(self.benchmark_symbol, "benchmark")
            )


def _canonical_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return as_utc(value, "timestamp").isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID | StrEnum):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, str | int | bool):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def backtest_request_fingerprint(configuration: BacktestConfiguration) -> str:
    """Return a stable SHA-256 over every execution-affecting configuration field."""

    payload = _canonical_value(configuration)
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def backtest_risk_configuration_marker(snapshot: BacktestRiskConfigurationSnapshot) -> str:
    """Stable marker over the actual R01 limits used by one backtest."""

    payload = _canonical_value(snapshot)
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def backtest_configuration_to_dict(configuration: BacktestConfiguration) -> dict[str, Any]:
    """Serialize a validated configuration to its canonical persistence representation."""

    value = _canonical_value(configuration)
    if not isinstance(value, dict):
        raise TypeError("canonical backtest configuration must be an object")
    return value


def backtest_configuration_from_dict(value: Mapping[str, Any]) -> BacktestConfiguration:
    """Restore and revalidate a persisted configuration without accepting loose coercions."""

    fee = value.get("fee_configuration")
    slippage = value.get("slippage_configuration")
    if not isinstance(fee, Mapping) or not isinstance(slippage, Mapping):
        raise BacktestError("BACKTEST_INVALID_CONFIGURATION", "fee/slippage config is missing")
    parameters = value.get("parameters")
    instrument_ids = value.get("instrument_ids")
    if not isinstance(parameters, Mapping) or not isinstance(instrument_ids, list):
        raise BacktestError("BACKTEST_INVALID_CONFIGURATION", "parameters/instruments are invalid")
    raw_risk_snapshot = value.get("risk_configuration_snapshot")
    if raw_risk_snapshot is not None and not isinstance(raw_risk_snapshot, Mapping):
        raise BacktestError("BACKTEST_INVALID_CONFIGURATION", "risk snapshot is invalid")
    risk_snapshot = (
        None
        if raw_risk_snapshot is None
        else BacktestRiskConfigurationSnapshot(
            reference=str(raw_risk_snapshot["reference"]),
            limits_version_marker=str(raw_risk_snapshot["limits_version_marker"]),
            max_order_notional=(
                None
                if raw_risk_snapshot.get("max_order_notional") is None
                else Decimal(str(raw_risk_snapshot["max_order_notional"]))
            ),
            max_instrument_weight=(
                None
                if raw_risk_snapshot.get("max_instrument_weight") is None
                else Decimal(str(raw_risk_snapshot["max_instrument_weight"]))
            ),
            max_total_exposure=(
                None
                if raw_risk_snapshot.get("max_total_exposure") is None
                else Decimal(str(raw_risk_snapshot["max_total_exposure"]))
            ),
            max_orders_per_window=(
                None
                if raw_risk_snapshot.get("max_orders_per_window") is None
                else int(raw_risk_snapshot["max_orders_per_window"])
            ),
            order_frequency_window_seconds=int(raw_risk_snapshot["order_frequency_window_seconds"]),
            allow_market_orders=bool(raw_risk_snapshot["allow_market_orders"]),
            require_reference_price_for_market_order=bool(
                raw_risk_snapshot["require_reference_price_for_market_order"]
            ),
            kill_switch_enabled=bool(raw_risk_snapshot["kill_switch_enabled"]),
            schema_version=int(raw_risk_snapshot["schema_version"]),
        )
    )
    return BacktestConfiguration(
        strategy_key=str(value["strategy_key"]),
        strategy_version=str(value["strategy_version"]),
        parameters={str(key): item for key, item in parameters.items()},
        instrument_ids=tuple(UUID(str(item)) for item in instrument_ids),
        timeframe=MarketTimeframe(str(value["timeframe"])),
        start_at=datetime.fromisoformat(str(value["start_at"]).replace("Z", "+00:00")),
        end_at=datetime.fromisoformat(str(value["end_at"]).replace("Z", "+00:00")),
        initial_cash=Decimal(str(value["initial_cash"])),
        order_type=OrderType(str(value["order_type"])),
        time_in_force=TimeInForce(str(value["time_in_force"])),
        fee_configuration=AshareSimpleFeeModel(
            commission_rate=Decimal(str(fee["commission_rate"])),
            minimum_commission=Decimal(str(fee["minimum_commission"])),
            stamp_duty_rate=Decimal(str(fee["stamp_duty_rate"])),
            transfer_fee_rate=Decimal(str(fee["transfer_fee_rate"])),
            currency_quantum=Decimal(str(fee["currency_quantum"])),
            schema_version=int(fee["schema_version"]),
            version=str(fee["version"]),
        ),
        slippage_configuration=FixedBasisPointsSlippageModel(
            basis_points=Decimal(str(slippage["basis_points"])),
            maximum_slippage=(
                None
                if slippage.get("maximum_slippage") is None
                else Decimal(str(slippage["maximum_slippage"]))
            ),
            version=str(slippage["version"]),
        ),
        risk_configuration_reference=str(value["risk_configuration_reference"]),
        risk_configuration_snapshot=risk_snapshot,
        maximum_volume_participation=(
            None
            if value.get("maximum_volume_participation") is None
            else Decimal(str(value["maximum_volume_participation"]))
        ),
        benchmark_symbol=(
            None if value.get("benchmark_symbol") is None else str(value["benchmark_symbol"])
        ),
        data_source_code=str(value.get("data_source_code", "BAOSTOCK")),
        environment=StrategyEnvironment(str(value["environment"])),
        schema_version=int(value["schema_version"]),
        engine_version=str(value["engine_version"]),
    )


@dataclass(slots=True, kw_only=True)
class BacktestRun:
    idempotency_key: str
    request_fingerprint: str
    configuration: BacktestConfiguration
    correlation_id: UUID
    id: UUID = field(default_factory=uuid4)
    strategy_run_id: UUID | None = None
    account_id: UUID | None = None
    status: BacktestRunStatus = BacktestRunStatus.CREATED
    bars_processed: int = 0
    sessions_processed: int = 0
    signals_generated: int = 0
    risk_passed: int = 0
    risk_rejected: int = 0
    risk_reviewed: int = 0
    orders_created: int = 0
    fills_generated: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.idempotency_key = non_empty(self.idempotency_key, "idempotency_key")
        if len(self.idempotency_key) > 128:
            raise BacktestError(
                "BACKTEST_INVALID_CONFIGURATION", "idempotency_key exceeds 128 characters"
            )
        self.request_fingerprint = non_empty(self.request_fingerprint, "request_fingerprint")
        if self.request_fingerprint != backtest_request_fingerprint(self.configuration):
            raise BacktestError(
                "BACKTEST_INVALID_CONFIGURATION", "request fingerprint does not match configuration"
            )
        counters = (
            self.bars_processed,
            self.sessions_processed,
            self.signals_generated,
            self.risk_passed,
            self.risk_rejected,
            self.risk_reviewed,
            self.orders_created,
            self.fills_generated,
        )
        if any(value < 0 for value in counters):
            raise BacktestError(
                "BACKTEST_INVALID_CONFIGURATION", "run counters must be non-negative"
            )
        for name in ("started_at", "completed_at", "failed_at"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, as_utc(value, name))
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")

    def mark_running(self, occurred_at: datetime) -> None:
        if self.status is not BacktestRunStatus.CREATED:
            raise BacktestError("BACKTEST_INVALID_CONFIGURATION", "only CREATED runs can start")
        now = as_utc(occurred_at, "occurred_at")
        self.status = BacktestRunStatus.RUNNING
        self.started_at = now
        self.updated_at = now

    def mark_completed(self, occurred_at: datetime) -> None:
        if self.status is not BacktestRunStatus.RUNNING:
            raise BacktestError("BACKTEST_INVALID_CONFIGURATION", "only RUNNING runs can complete")
        now = as_utc(occurred_at, "occurred_at")
        self.status = BacktestRunStatus.COMPLETED
        self.completed_at = now
        self.updated_at = now

    def mark_failed(self, occurred_at: datetime, code: str, message: str) -> None:
        now = as_utc(occurred_at, "occurred_at")
        self.status = BacktestRunStatus.FAILED
        self.failed_at = now
        self.error_code = non_empty(code, "error_code")[:64]
        self.error_message = non_empty(message, "error_message")[:512]
        self.updated_at = now


@dataclass(frozen=True, slots=True, kw_only=True)
class BacktestSession:
    trading_date: date
    instrument_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        ids = tuple(sorted(set(self.instrument_ids), key=str))
        if not ids:
            raise BacktestError("BACKTEST_NO_MARKET_DATA", "session must contain instruments")
        object.__setattr__(self, "instrument_ids", ids)

    def time_for(self, phase: BacktestPhase) -> datetime:
        phase_time = {
            BacktestPhase.SESSION_OPEN: time(9, 30),
            BacktestPhase.SESSION_CLOSE: time(15, 0),
            BacktestPhase.SESSION_END: time(15, 1),
        }[phase]
        return datetime.combine(self.trading_date, phase_time, ASHARE_TIMEZONE).astimezone(UTC)


class BacktestClock:
    """Finite deterministic clock; it never reads wall-clock time."""

    __slots__ = ("_index", "_phases", "_sessions")

    def __init__(self, sessions: Sequence[BacktestSession]) -> None:
        ordered = tuple(sorted(sessions, key=lambda item: item.trading_date))
        if not ordered:
            raise BacktestError("BACKTEST_NO_MARKET_DATA", "no backtest sessions available")
        dates = [item.trading_date for item in ordered]
        if len(dates) != len(set(dates)):
            raise BacktestError(
                "BACKTEST_INVALID_CONFIGURATION", "session trading dates must be unique"
            )
        self._sessions = ordered
        self._phases = tuple(BacktestPhase)
        self._index = 0

    @property
    def current_session(self) -> BacktestSession:
        if self.is_complete:
            raise BacktestError("BACKTEST_INVALID_CONFIGURATION", "clock is complete")
        return self._sessions[self._index // len(self._phases)]

    @property
    def current_phase(self) -> BacktestPhase:
        if self.is_complete:
            raise BacktestError("BACKTEST_INVALID_CONFIGURATION", "clock is complete")
        return self._phases[self._index % len(self._phases)]

    @property
    def current_time(self) -> datetime:
        return self.current_session.time_for(self.current_phase)

    @property
    def is_complete(self) -> bool:
        return self._index >= len(self._sessions) * len(self._phases)

    def advance(self) -> None:
        if self.is_complete:
            raise BacktestError("BACKTEST_INVALID_CONFIGURATION", "clock is already complete")
        self._index += 1


@dataclass(frozen=True, slots=True, kw_only=True)
class BacktestEquityPoint:
    run_id: UUID
    timestamp: datetime
    cash: Decimal
    market_value: Decimal
    total_equity: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    daily_return: Decimal | None
    cumulative_return: Decimal
    drawdown: Decimal
    positions_count: int
    warnings: tuple[str, ...] = ()
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", as_utc(self.timestamp, "timestamp"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))
        for name in (
            "cash",
            "market_value",
            "total_equity",
            "gross_exposure",
            "net_exposure",
            "cumulative_return",
            "drawdown",
        ):
            decimal_value(getattr(self, name), name)
        if self.daily_return is not None:
            decimal_value(self.daily_return, "daily_return")
        if self.positions_count < 0:
            raise ValueError("positions_count must be non-negative")
        if self.total_equity != self.cash + self.market_value:
            raise ValueError("total_equity must equal cash plus market_value")
        if self.gross_exposure < ZERO or self.drawdown > ZERO:
            raise ValueError("gross_exposure must be non-negative and drawdown non-positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class BacktestTradeSummary:
    run_id: UUID
    instrument_id: UUID
    opened_at: datetime
    closed_at: datetime
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "opened_at", as_utc(self.opened_at, "opened_at"))
        object.__setattr__(self, "closed_at", as_utc(self.closed_at, "closed_at"))
        if self.opened_at >= self.closed_at:
            raise ValueError("opened_at must be earlier than closed_at")
        for name in ("quantity", "entry_price", "exit_price"):
            _positive(getattr(self, name), name)
        _non_negative(self.fees, "fees")
        decimal_value(self.gross_pnl, "gross_pnl")
        decimal_value(self.net_pnl, "net_pnl")
        if self.net_pnl != self.gross_pnl - self.fees:
            raise ValueError("net_pnl must equal gross_pnl minus fees")


@dataclass(frozen=True, slots=True, kw_only=True)
class BacktestFillMetricInput:
    side: OrderSide
    quantity: Decimal
    price: Decimal
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    other_fee: Decimal = ZERO

    def __post_init__(self) -> None:
        _positive(self.quantity, "quantity")
        _positive(self.price, "price")
        for name in ("commission", "stamp_duty", "transfer_fee", "other_fee"):
            _non_negative(getattr(self, name), name)


@dataclass(frozen=True, slots=True, kw_only=True)
class BacktestMetricSet:
    run_id: UUID
    initial_equity: Decimal
    final_equity: Decimal
    total_return: Decimal
    annualized_return: Decimal | None
    maximum_drawdown: Decimal
    annualized_volatility: Decimal | None
    sharpe_ratio: Decimal | None
    trading_sessions: int
    fill_count: int
    buy_fill_count: int
    sell_fill_count: int
    total_turnover: Decimal
    total_commission: Decimal
    total_stamp_duty: Decimal
    total_transfer_fee: Decimal
    total_other_fee: Decimal
    total_fees: Decimal
    realized_pnl: Decimal
    win_rate: Decimal | None
    loss_rate: Decimal | None
    profit_factor: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    average_exposure: Decimal
    maximum_exposure: Decimal
    warnings: tuple[str, ...] = ()
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True, kw_only=True)
class BacktestEvent:
    run_id: UUID
    event_type: BacktestEventType
    occurred_at: datetime
    sequence_number: int
    summary: str
    details: Mapping[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", as_utc(self.occurred_at, "occurred_at"))
        if self.sequence_number < 1:
            raise ValueError("sequence_number must be positive")
        object.__setattr__(self, "summary", non_empty(self.summary, "summary"))


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, ZERO) / Decimal(len(values))


def _sqrt(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 34
        return value.sqrt()


class BacktestPerformanceService:
    """Pure deterministic performance calculator using Decimal throughout."""

    def calculate(
        self,
        *,
        run_id: UUID,
        equity_points: Sequence[BacktestEquityPoint],
        fills: Sequence[BacktestFillMetricInput],
        trades: Sequence[BacktestTradeSummary],
        annual_risk_free_rate: Decimal = ZERO,
    ) -> BacktestMetricSet:
        if not equity_points:
            raise BacktestError("BACKTEST_METRICS_FAILED", "equity points are required")
        decimal_value(annual_risk_free_rate, "annual_risk_free_rate")
        points = tuple(sorted(equity_points, key=lambda item: item.timestamp))
        if any(item.run_id != run_id for item in points):
            raise BacktestError("BACKTEST_METRICS_FAILED", "equity point belongs to another run")
        initial_equity = points[0].total_equity
        final_equity = points[-1].total_equity
        _positive(initial_equity, "initial_equity")
        total_return = final_equity / initial_equity - ONE
        sessions = len(points)
        annualized_return: Decimal | None = None
        if sessions > 1 and final_equity > ZERO:
            with localcontext() as context:
                context.prec = 34
                annualized_return = (
                    (total_return + ONE).ln() * (TRADING_SESSIONS_PER_YEAR / Decimal(sessions - 1))
                ).exp() - ONE
        returns = [item.daily_return for item in points if item.daily_return is not None]
        volatility: Decimal | None = None
        sharpe: Decimal | None = None
        if len(returns) >= 2:
            return_values = [item for item in returns if item is not None]
            mean_return = _mean(return_values)
            variance = sum(((item - mean_return) ** 2 for item in return_values), ZERO) / Decimal(
                len(return_values) - 1
            )
            daily_stddev = _sqrt(variance)
            volatility = daily_stddev * _sqrt(TRADING_SESSIONS_PER_YEAR)
            if daily_stddev != ZERO:
                daily_risk_free = annual_risk_free_rate / TRADING_SESSIONS_PER_YEAR
                sharpe = (
                    (mean_return - daily_risk_free)
                    / daily_stddev
                    * _sqrt(TRADING_SESSIONS_PER_YEAR)
                )
        turnover = sum((fill.quantity * fill.price for fill in fills), ZERO)
        commission = sum((fill.commission for fill in fills), ZERO)
        stamp_duty = sum((fill.stamp_duty for fill in fills), ZERO)
        transfer_fee = sum((fill.transfer_fee for fill in fills), ZERO)
        other_fee = sum((fill.other_fee for fill in fills), ZERO)
        total_fees = commission + stamp_duty + transfer_fee + other_fee
        wins = [trade.net_pnl for trade in trades if trade.net_pnl > ZERO]
        losses = [trade.net_pnl for trade in trades if trade.net_pnl < ZERO]
        closed_count = len(wins) + len(losses)
        win_rate = Decimal(len(wins)) / Decimal(closed_count) if closed_count else None
        loss_rate = Decimal(len(losses)) / Decimal(closed_count) if closed_count else None
        gross_profit = sum(wins, ZERO)
        gross_loss = -sum(losses, ZERO)
        profit_factor = gross_profit / gross_loss if gross_loss else None
        average_win = _mean(wins) if wins else None
        average_loss = _mean(losses) if losses else None
        warnings: list[str] = []
        if not trades:
            warnings.append("NO_CLOSED_TRADES")
        if not losses:
            warnings.append("PROFIT_FACTOR_UNDEFINED_NO_LOSS_TRADES")
        if len(returns) < 2:
            warnings.append("VOLATILITY_UNDEFINED_INSUFFICIENT_RETURNS")
        elif volatility == ZERO:
            warnings.append("SHARPE_UNDEFINED_ZERO_VOLATILITY")
        exposures = [
            item.gross_exposure / item.total_equity if item.total_equity > ZERO else ZERO
            for item in points
        ]
        return BacktestMetricSet(
            run_id=run_id,
            initial_equity=_q8(initial_equity),
            final_equity=_q8(final_equity),
            total_return=_q8(total_return),
            annualized_return=None if annualized_return is None else _q8(annualized_return),
            maximum_drawdown=_q8(min((item.drawdown for item in points), default=ZERO)),
            annualized_volatility=None if volatility is None else _q8(volatility),
            sharpe_ratio=None if sharpe is None else _q12(sharpe),
            trading_sessions=sessions,
            fill_count=len(fills),
            buy_fill_count=sum(fill.side is OrderSide.BUY for fill in fills),
            sell_fill_count=sum(fill.side is OrderSide.SELL for fill in fills),
            total_turnover=_q8(turnover),
            total_commission=_q8(commission),
            total_stamp_duty=_q8(stamp_duty),
            total_transfer_fee=_q8(transfer_fee),
            total_other_fee=_q8(other_fee),
            total_fees=_q8(total_fees),
            realized_pnl=_q8(sum((trade.net_pnl for trade in trades), ZERO)),
            win_rate=None if win_rate is None else _q8(win_rate),
            loss_rate=None if loss_rate is None else _q8(loss_rate),
            profit_factor=None if profit_factor is None else _q12(profit_factor),
            average_win=None if average_win is None else _q8(average_win),
            average_loss=None if average_loss is None else _q8(average_loss),
            average_exposure=_q8(_mean(exposures)),
            maximum_exposure=_q8(max(exposures, default=ZERO)),
            warnings=tuple(warnings),
        )


def build_equity_points(
    *,
    run_id: UUID,
    initial_equity: Decimal,
    snapshots: Iterable[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int, tuple[str, ...]]],
) -> list[BacktestEquityPoint]:
    """Build daily returns and drawdown without any access to future snapshots."""

    _positive(initial_equity, "initial_equity")
    result: list[BacktestEquityPoint] = []
    peak = initial_equity
    previous = initial_equity
    for timestamp, cash, market_value, gross, net, positions, warnings in snapshots:
        equity = cash + market_value
        peak = max(peak, equity)
        daily_return = _q8(equity / previous - ONE) if result and previous != ZERO else None
        cumulative_return = _q8(equity / initial_equity - ONE)
        drawdown = _q8(equity / peak - ONE) if peak != ZERO else ZERO
        result.append(
            BacktestEquityPoint(
                run_id=run_id,
                timestamp=timestamp,
                cash=cash,
                market_value=market_value,
                total_equity=equity,
                gross_exposure=gross,
                net_exposure=net,
                daily_return=daily_return,
                cumulative_return=cumulative_return,
                drawdown=drawdown,
                positions_count=positions,
                warnings=warnings,
            )
        )
        previous = equity
    return result
