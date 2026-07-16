"""Pure-Python strategy contracts and deterministic validation utilities."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable
from uuid import UUID

from alphadesk_domain.enums import MarketTimeframe, OrderSide, SignalType

type StrategyParameterValue = int | Decimal | bool | str
type JsonScalar = str | int | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class StrategyError(ValueError):
    """Controlled strategy-domain error safe for callers to report."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _aware_utc(value: datetime, field_name: str, code: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StrategyError(code, f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _decimal(value: Decimal, field_name: str, code: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise StrategyError(code, f"{field_name} must be Decimal")
    if not value.is_finite():
        raise StrategyError(code, f"{field_name} must be finite")
    return value


def _json_safe(value: object, path: str = "metadata") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _json_safe(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise StrategyError("STRATEGY_INVALID_SIGNAL", f"{path} keys must be strings")
            _json_safe(item, f"{path}.{key}")
        return
    raise StrategyError("STRATEGY_INVALID_SIGNAL", f"{path} contains a non-JSON-safe value")


class StrategyEnvironment(StrEnum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    REPLAY = "REPLAY"
    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyMetadata:
    strategy_key: str
    display_name: str
    description: str
    version: str
    supported_timeframes: tuple[MarketTimeframe, ...]
    parameter_schema_version: int = 1

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", self.strategy_key):
            raise StrategyError(
                "STRATEGY_INVALID_CONTEXT",
                "strategy_key must be a stable lowercase identifier",
            )
        if not self.display_name.strip() or not self.description.strip():
            raise StrategyError(
                "STRATEGY_INVALID_CONTEXT", "strategy metadata text must not be empty"
            )
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", self.version):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "version must use semantic x.y.z form")
        if not self.supported_timeframes:
            raise StrategyError(
                "STRATEGY_INVALID_CONTEXT", "supported_timeframes must not be empty"
            )
        if any(not isinstance(item, MarketTimeframe) for item in self.supported_timeframes):
            raise StrategyError(
                "STRATEGY_INVALID_CONTEXT", "supported_timeframes contains an invalid value"
            )
        if len(set(self.supported_timeframes)) != len(self.supported_timeframes):
            raise StrategyError(
                "STRATEGY_INVALID_CONTEXT", "supported_timeframes must not contain duplicates"
            )
        if self.parameter_schema_version < 1:
            raise StrategyError(
                "STRATEGY_INVALID_CONTEXT", "parameter_schema_version must be positive"
            )


class StrategyContext:
    """Read-only run context with explicitly mutable in-memory strategy state."""

    __slots__ = (
        "_current_time",
        "_environment",
        "_locked",
        "_parameters",
        "_run_id",
        "_state",
        "_strategy_key",
        "_strategy_version",
    )

    def __init__(
        self,
        *,
        strategy_key: str,
        strategy_version: str,
        run_id: UUID,
        current_time: datetime,
        parameters: Mapping[str, StrategyParameterValue],
        state: Mapping[str, object] | None = None,
        environment: StrategyEnvironment = StrategyEnvironment.RESEARCH,
    ) -> None:
        if not strategy_key.strip() or not strategy_version.strip():
            raise StrategyError(
                "STRATEGY_INVALID_CONTEXT", "strategy key and version must not be empty"
            )
        self._strategy_key = strategy_key
        self._strategy_version = strategy_version
        self._run_id = run_id
        self._current_time = _aware_utc(current_time, "current_time", "STRATEGY_INVALID_CONTEXT")
        self._parameters = MappingProxyType(dict(parameters))
        self._state = dict(state or {})
        if not isinstance(environment, StrategyEnvironment):
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "environment is invalid")
        self._environment = environment
        self._locked = True

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_locked", False):
            raise AttributeError("StrategyContext is read-only; use set_state for runtime state")
        object.__setattr__(self, name, value)

    @property
    def strategy_key(self) -> str:
        return self._strategy_key

    @property
    def strategy_version(self) -> str:
        return self._strategy_version

    @property
    def run_id(self) -> UUID:
        return self._run_id

    @property
    def current_time(self) -> datetime:
        return self._current_time

    @property
    def parameters(self) -> Mapping[str, StrategyParameterValue]:
        return self._parameters

    @property
    def state(self) -> Mapping[str, object]:
        return MappingProxyType(self._state)

    @property
    def environment(self) -> StrategyEnvironment:
        return self._environment

    def get_parameter(self, name: str) -> StrategyParameterValue:
        try:
            return self._parameters[name]
        except KeyError as exc:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", f"parameter '{name}' is not available"
            ) from exc

    def get_state(self, key: str, default: object = None) -> object:
        return self._state.get(key, default)

    def set_state(self, key: str, value: object) -> None:
        if not key.strip():
            raise StrategyError("STRATEGY_INVALID_CONTEXT", "state key must not be empty")
        self._state[key] = value


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyBar:
    instrument_id: UUID
    symbol: str
    exchange: str
    timeframe: MarketTimeframe
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.exchange.strip():
            raise StrategyError("STRATEGY_INVALID_BAR", "symbol and exchange must not be empty")
        if not isinstance(self.timeframe, MarketTimeframe):
            raise StrategyError("STRATEGY_INVALID_BAR", "timeframe is invalid")
        object.__setattr__(
            self,
            "timestamp",
            _aware_utc(self.timestamp, "timestamp", "STRATEGY_INVALID_BAR"),
        )
        for name in ("open", "high", "low", "close", "volume"):
            _decimal(getattr(self, name), name, "STRATEGY_INVALID_BAR")
        if self.amount is not None:
            _decimal(self.amount, "amount", "STRATEGY_INVALID_BAR")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise StrategyError("STRATEGY_INVALID_BAR", "OHLC prices must be positive")
        if self.high < max(self.open, self.close, self.low):
            raise StrategyError("STRATEGY_INVALID_BAR", "high is below another OHLC value")
        if self.low > min(self.open, self.close, self.high):
            raise StrategyError("STRATEGY_INVALID_BAR", "low is above another OHLC value")
        if self.volume < 0:
            raise StrategyError("STRATEGY_INVALID_BAR", "volume must be non-negative")
        if self.amount is not None and self.amount < 0:
            raise StrategyError("STRATEGY_INVALID_BAR", "amount must be non-negative")


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalDraft:
    strategy_key: str
    strategy_version: str
    instrument_id: UUID
    signal_type: SignalType
    side: OrderSide
    generated_at: datetime
    bar_timestamp: datetime
    quantity: Decimal | None = None
    target_weight: Decimal | None = None
    reference_price: Decimal | None = None
    confidence: Decimal | None = None
    reason: str = ""
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.strategy_key.strip() or not self.strategy_version.strip():
            raise StrategyError(
                "STRATEGY_INVALID_SIGNAL", "strategy key and version must not be empty"
            )
        if not isinstance(self.signal_type, SignalType) or not isinstance(self.side, OrderSide):
            raise StrategyError("STRATEGY_INVALID_SIGNAL", "signal type or side is invalid")
        object.__setattr__(
            self,
            "generated_at",
            _aware_utc(self.generated_at, "generated_at", "STRATEGY_INVALID_SIGNAL"),
        )
        object.__setattr__(
            self,
            "bar_timestamp",
            _aware_utc(self.bar_timestamp, "bar_timestamp", "STRATEGY_INVALID_SIGNAL"),
        )
        if self.quantity is not None and self.target_weight is not None:
            raise StrategyError(
                "STRATEGY_INVALID_SIGNAL", "quantity and target_weight are mutually exclusive"
            )
        if self.quantity is not None:
            _decimal(self.quantity, "quantity", "STRATEGY_INVALID_SIGNAL")
            if self.quantity <= 0:
                raise StrategyError("STRATEGY_INVALID_SIGNAL", "quantity must be positive")
        if self.target_weight is not None:
            _decimal(self.target_weight, "target_weight", "STRATEGY_INVALID_SIGNAL")
            if not Decimal("0") <= self.target_weight <= Decimal("1"):
                raise StrategyError(
                    "STRATEGY_INVALID_SIGNAL", "target_weight must be between zero and one"
                )
        if self.reference_price is not None:
            _decimal(self.reference_price, "reference_price", "STRATEGY_INVALID_SIGNAL")
            if self.reference_price <= 0:
                raise StrategyError("STRATEGY_INVALID_SIGNAL", "reference_price must be positive")
        if self.confidence is not None:
            _decimal(self.confidence, "confidence", "STRATEGY_INVALID_SIGNAL")
            if not Decimal("0") <= self.confidence <= Decimal("1"):
                raise StrategyError(
                    "STRATEGY_INVALID_SIGNAL", "confidence must be between zero and one"
                )
        if not self.reason.strip():
            raise StrategyError("STRATEGY_INVALID_SIGNAL", "reason must not be empty")
        if self.schema_version != 1:
            raise StrategyError("STRATEGY_INVALID_SIGNAL", "schema_version must be one")
        metadata = dict(self.metadata)
        _json_safe(metadata)
        object.__setattr__(self, "metadata", MappingProxyType(metadata))


class StrategyParameterType(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    STRING = "string"
    ENUM = "enum"


@dataclass(frozen=True, slots=True, kw_only=True)
class StrategyParameterDefinition:
    name: str
    parameter_type: StrategyParameterType
    required: bool
    description: str
    default: StrategyParameterValue | None = None
    min_value: int | Decimal | None = None
    max_value: int | Decimal | None = None
    choices: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.parameter_type, StrategyParameterType):
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", f"parameter '{self.name}' has an invalid type"
            )
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.name):
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", f"parameter '{self.name}' has an invalid name"
            )
        if not self.description.strip():
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", f"parameter '{self.name}' needs a description"
            )
        if self.required and self.default is not None:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER",
                f"required parameter '{self.name}' must not define a default",
            )
        if self.parameter_type is StrategyParameterType.ENUM and not self.choices:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", f"enum parameter '{self.name}' needs choices"
            )
        if self.parameter_type is not StrategyParameterType.ENUM and self.choices is not None:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER",
                f"non-enum parameter '{self.name}' must not define choices",
            )


def _validate_parameter_value(
    definition: StrategyParameterDefinition, value: StrategyParameterValue
) -> StrategyParameterValue:
    name = definition.name
    expected = definition.parameter_type
    valid = (
        (expected is StrategyParameterType.INTEGER and type(value) is int)
        or (expected is StrategyParameterType.DECIMAL and isinstance(value, Decimal))
        or (expected is StrategyParameterType.BOOLEAN and type(value) is bool)
        or (
            expected in (StrategyParameterType.STRING, StrategyParameterType.ENUM)
            and isinstance(value, str)
        )
    )
    if not valid:
        raise StrategyError("STRATEGY_INVALID_PARAMETER", f"parameter '{name}' has invalid type")
    if isinstance(value, Decimal) and not value.is_finite():
        raise StrategyError("STRATEGY_INVALID_PARAMETER", f"parameter '{name}' must be finite")
    if expected is StrategyParameterType.ENUM and value not in (definition.choices or ()):
        raise StrategyError(
            "STRATEGY_INVALID_PARAMETER", f"parameter '{name}' is not an allowed choice"
        )
    if type(value) is int or isinstance(value, Decimal):
        if definition.min_value is not None and value < definition.min_value:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", f"parameter '{name}' is below its minimum"
            )
        if definition.max_value is not None and value > definition.max_value:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", f"parameter '{name}' is above its maximum"
            )
    return value


def validate_strategy_parameters(
    parameter_definitions: Sequence[StrategyParameterDefinition],
    supplied_parameters: Mapping[str, StrategyParameterValue],
) -> Mapping[str, StrategyParameterValue]:
    definitions = {item.name: item for item in parameter_definitions}
    if len(definitions) != len(parameter_definitions):
        raise StrategyError(
            "STRATEGY_INVALID_PARAMETER", "parameter definitions contain duplicate names"
        )
    unknown = sorted(set(supplied_parameters) - set(definitions))
    if unknown:
        raise StrategyError("STRATEGY_UNKNOWN_PARAMETER", f"unknown parameter '{unknown[0]}'")
    validated: dict[str, StrategyParameterValue] = {}
    for name in sorted(definitions):
        definition = definitions[name]
        if name in supplied_parameters:
            value = supplied_parameters[name]
        elif definition.default is not None:
            value = definition.default
        elif definition.required:
            raise StrategyError(
                "STRATEGY_INVALID_PARAMETER", f"required parameter '{name}' is missing"
            )
        else:
            continue
        validated[name] = _validate_parameter_value(definition, value)
    return MappingProxyType(validated)


@runtime_checkable
class Strategy(Protocol):
    metadata: StrategyMetadata

    def initialize(self, context: StrategyContext) -> None: ...

    def on_bar(self, context: StrategyContext, bar: StrategyBar) -> list[SignalDraft]: ...

    def finalize(self, context: StrategyContext) -> None: ...


type StrategyFactory = Callable[[Mapping[str, StrategyParameterValue]], Strategy]


@dataclass(frozen=True, slots=True)
class _StrategyRegistration:
    metadata: StrategyMetadata
    parameter_definitions: tuple[StrategyParameterDefinition, ...]
    factory: StrategyFactory


class StrategyRegistry:
    def __init__(self, *, allow_unregister: bool = False) -> None:
        self._registrations: dict[str, _StrategyRegistration] = {}
        self._allow_unregister = allow_unregister

    def register(
        self,
        metadata: StrategyMetadata,
        parameter_definitions: Sequence[StrategyParameterDefinition],
        factory: StrategyFactory,
    ) -> None:
        if metadata.strategy_key in self._registrations:
            raise StrategyError(
                "STRATEGY_ALREADY_REGISTERED",
                f"strategy '{metadata.strategy_key}' is already registered",
            )
        self._registrations[metadata.strategy_key] = _StrategyRegistration(
            metadata, tuple(parameter_definitions), factory
        )

    def unregister(self, strategy_key: str) -> None:
        if not self._allow_unregister:
            raise StrategyError(
                "STRATEGY_EXECUTION_ERROR", "unregister is only allowed in test/development"
            )
        if strategy_key not in self._registrations:
            raise StrategyError(
                "STRATEGY_NOT_FOUND", f"strategy '{strategy_key}' is not registered"
            )
        del self._registrations[strategy_key]

    def get(self, strategy_key: str) -> StrategyMetadata:
        try:
            return self._registrations[strategy_key].metadata
        except KeyError as exc:
            raise StrategyError(
                "STRATEGY_NOT_FOUND", f"strategy '{strategy_key}' is not registered"
            ) from exc

    def list_metadata(self) -> tuple[StrategyMetadata, ...]:
        return tuple(self._registrations[key].metadata for key in sorted(self._registrations))

    def create_instance(
        self,
        strategy_key: str,
        supplied_parameters: Mapping[str, StrategyParameterValue] | None = None,
    ) -> Strategy:
        try:
            registration = self._registrations[strategy_key]
        except KeyError as exc:
            raise StrategyError(
                "STRATEGY_NOT_FOUND", f"strategy '{strategy_key}' is not registered"
            ) from exc
        parameters = validate_strategy_parameters(
            registration.parameter_definitions, supplied_parameters or {}
        )
        try:
            instance = registration.factory(parameters)
        except StrategyError:
            raise
        except (TypeError, ValueError) as exc:
            raise StrategyError(
                "STRATEGY_EXECUTION_ERROR", f"strategy '{strategy_key}' could not be created"
            ) from exc
        if not isinstance(instance, Strategy) or instance.metadata != registration.metadata:
            raise StrategyError(
                "STRATEGY_EXECUTION_ERROR", f"strategy '{strategy_key}' violates its registration"
            )
        return instance
