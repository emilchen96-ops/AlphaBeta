"""Framework-independent SC01 scanner contracts and deterministic A-share scanners."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from hashlib import sha256
from itertools import pairwise
from typing import Protocol
from uuid import UUID, uuid4

from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.strategy import StrategyBar
from alphadesk_domain.values import as_utc, non_empty, utc_now


class ScannerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ScannerParameterType(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"


class ScanRunStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RESOLVING = "RESOLVING"
    CHECKING_DATA = "CHECKING_DATA"
    BACKFILLING = "BACKFILLING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class ScanUniverseType(StrEnum):
    ALL_ACTIVE_A_SHARES = "ALL_ACTIVE_A_SHARES"
    CUSTOM_INSTRUMENTS = "CUSTOM_INSTRUMENTS"


class ScanMemberStatus(StrEnum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    DATA_MISSING = "DATA_MISSING"
    BACKFILL_REQUESTED = "BACKFILL_REQUESTED"
    READY = "READY"
    SCANNED = "SCANNED"
    MATCHED = "MATCHED"
    FAILED = "FAILED"


type ScannerParameterValue = str | int | bool | Decimal | None
type StoredScannerParameter = str | int | bool | None
type ScannerMetricValue = str | int | bool | Decimal | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScannerParameterDefinition:
    name: str
    parameter_type: ScannerParameterType
    description: str
    display_name: str | None = None
    unit: str | None = None
    default: ScannerParameterValue = None
    required: bool = False
    nullable: bool = False
    min_value: Decimal | int | None = None
    max_value: Decimal | int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", non_empty(self.name, "name"))
        object.__setattr__(self, "description", non_empty(self.description, "description"))
        if self.display_name is not None:
            object.__setattr__(self, "display_name", non_empty(self.display_name, "display_name"))


@dataclass(frozen=True, slots=True, kw_only=True)
class ScannerMetadata:
    scanner_key: str
    display_name: str
    description: str
    version: str
    supported_timeframes: tuple[MarketTimeframe, ...]
    parameter_definitions: tuple[ScannerParameterDefinition, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "scanner_key", non_empty(self.scanner_key, "scanner_key"))
        object.__setattr__(self, "display_name", non_empty(self.display_name, "display_name"))
        object.__setattr__(self, "description", non_empty(self.description, "description"))
        object.__setattr__(self, "version", non_empty(self.version, "version"))
        if not self.supported_timeframes:
            raise ValueError("supported_timeframes must not be empty")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScannerContext:
    as_of: datetime
    timeframe: MarketTimeframe
    parameters: Mapping[str, ScannerParameterValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", as_utc(self.as_of, "as_of"))
        if self.timeframe is not MarketTimeframe.DAY_1:
            raise ScannerError("SCANNER_TIMEFRAME_NOT_SUPPORTED", "only DAY_1 is supported")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScanCandidate:
    instrument_id: UUID
    score: Decimal
    matched_at: datetime
    reference_price: Decimal
    reason_code: str
    reason: str
    metrics: Mapping[str, ScannerMetricValue]

    def __post_init__(self) -> None:
        if not self.score.is_finite() or self.score < 0:
            raise ValueError("score must be a finite non-negative Decimal")
        if not self.reference_price.is_finite() or self.reference_price <= 0:
            raise ValueError("reference_price must be a positive Decimal")
        object.__setattr__(self, "matched_at", as_utc(self.matched_at, "matched_at"))
        object.__setattr__(self, "reason_code", non_empty(self.reason_code, "reason_code"))
        object.__setattr__(self, "reason", non_empty(self.reason, "reason"))


class Scanner(Protocol):
    @property
    def metadata(self) -> ScannerMetadata: ...

    def validate_parameters(
        self, parameters: Mapping[str, ScannerParameterValue]
    ) -> dict[str, ScannerParameterValue]: ...

    def scan(
        self,
        context: ScannerContext,
        instrument: Instrument,
        bars: Sequence[StrategyBar],
    ) -> ScanCandidate | None: ...


class BaseScanner:
    metadata: ScannerMetadata

    def validate_parameters(
        self, parameters: Mapping[str, ScannerParameterValue]
    ) -> dict[str, ScannerParameterValue]:
        definitions = {item.name: item for item in self.metadata.parameter_definitions}
        unknown = sorted(set(parameters) - set(definitions))
        if unknown:
            raise ScannerError(
                "SCANNER_UNKNOWN_PARAMETER", f"unknown scanner parameter: {unknown[0]}"
            )
        validated: dict[str, ScannerParameterValue] = {}
        for name, definition in definitions.items():
            raw = parameters.get(name, definition.default)
            if raw is None:
                if definition.required and not definition.nullable:
                    raise ScannerError(
                        "SCANNER_INVALID_PARAMETER", f"parameter '{name}' is required"
                    )
                validated[name] = None
                continue
            value = self._coerce(definition, raw)
            if definition.min_value is not None and value < definition.min_value:
                raise ScannerError(
                    "SCANNER_INVALID_PARAMETER", f"parameter '{name}' is below its minimum"
                )
            if definition.max_value is not None and value > definition.max_value:
                raise ScannerError(
                    "SCANNER_INVALID_PARAMETER", f"parameter '{name}' exceeds its maximum"
                )
            validated[name] = value
        return validated

    @staticmethod
    def _coerce(
        definition: ScannerParameterDefinition, raw: ScannerParameterValue
    ) -> int | bool | Decimal:
        name = definition.name
        if definition.parameter_type is ScannerParameterType.BOOLEAN:
            if not isinstance(raw, bool):
                raise ScannerError(
                    "SCANNER_INVALID_PARAMETER", f"parameter '{name}' must be boolean"
                )
            return raw
        if definition.parameter_type is ScannerParameterType.INTEGER:
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise ScannerError(
                    "SCANNER_INVALID_PARAMETER", f"parameter '{name}' must be integer"
                )
            return raw
        if isinstance(raw, float | bool):
            raise ScannerError(
                "SCANNER_INVALID_PARAMETER", f"parameter '{name}' must be a decimal string"
            )
        try:
            value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise ScannerError(
                "SCANNER_INVALID_PARAMETER", f"parameter '{name}' is not a valid decimal"
            ) from exc
        if not value.is_finite():
            raise ScannerError("SCANNER_INVALID_PARAMETER", f"parameter '{name}' must be finite")
        return value


def _eligible_bars(
    context: ScannerContext, instrument: Instrument, bars: Sequence[StrategyBar]
) -> list[StrategyBar]:
    ordered = list(bars)
    if any(left.timestamp >= right.timestamp for left, right in pairwise(ordered)):
        raise ScannerError("SCANNER_INVALID_BARS", "bars must be strictly ascending")
    if any(bar.instrument_id != instrument.id for bar in ordered):
        raise ScannerError("SCANNER_INVALID_BARS", "bar instrument does not match scanner input")
    if any(bar.timeframe is not context.timeframe for bar in ordered):
        raise ScannerError("SCANNER_INVALID_BARS", "bar timeframe does not match scanner input")
    return [bar for bar in ordered if bar.timestamp <= context.as_of]


def _decimal_metric(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.normalize()


class VolumeAnomalyScanner(BaseScanner):
    metadata = ScannerMetadata(
        scanner_key="volume_anomaly",
        display_name="成交量异常放大",
        description="以当前日线之前的历史均量识别可配置的成交量异常。",
        version="1.0.0",
        supported_timeframes=(MarketTimeframe.DAY_1,),
        parameter_definitions=(
            ScannerParameterDefinition(
                name="volume_window",
                parameter_type=ScannerParameterType.INTEGER,
                description="历史均量窗口, 不包含当前K线",
                display_name="平均成交量计算周期",
                unit="交易日",
                default=20,
                min_value=1,
                max_value=500,
            ),
            ScannerParameterDefinition(
                name="minimum_volume_ratio",
                parameter_type=ScannerParameterType.DECIMAL,
                description="最小成交量倍数",
                display_name="最低成交量倍数",
                unit="倍",
                default=Decimal("2"),
                min_value=Decimal("0"),
            ),
            ScannerParameterDefinition(
                name="minimum_amount",
                parameter_type=ScannerParameterType.DECIMAL,
                description="可选最小成交额",
                display_name="最低成交额",
                unit="元",
                nullable=True,
                min_value=Decimal("0"),
            ),
            ScannerParameterDefinition(
                name="minimum_price",
                parameter_type=ScannerParameterType.DECIMAL,
                description="可选最小收盘价",
                display_name="最低股价",
                unit="元",
                nullable=True,
                min_value=Decimal("0"),
            ),
            ScannerParameterDefinition(
                name="minimum_daily_return",
                parameter_type=ScannerParameterType.DECIMAL,
                description="可选最小日收益率",
                display_name="最低当日涨跌幅",
                unit="%",
                nullable=True,
            ),
            ScannerParameterDefinition(
                name="maximum_daily_return",
                parameter_type=ScannerParameterType.DECIMAL,
                description="可选最大日收益率",
                display_name="最高当日涨跌幅",
                unit="%",
                nullable=True,
            ),
        ),
    )

    def scan(
        self,
        context: ScannerContext,
        instrument: Instrument,
        bars: Sequence[StrategyBar],
    ) -> ScanCandidate | None:
        parameters = self.validate_parameters(context.parameters)
        window = int(parameters["volume_window"] or 0)
        eligible = _eligible_bars(context, instrument, bars)
        if len(eligible) < window + 1:
            return None
        current = eligible[-1]
        history = eligible[-window - 1 : -1]
        average_volume = sum((bar.volume for bar in history), Decimal("0")) / Decimal(window)
        if average_volume <= 0:
            return None
        ratio = current.volume / average_volume
        if ratio < _required_decimal(parameters, "minimum_volume_ratio"):
            return None
        if parameters["minimum_amount"] is not None and (
            current.amount is None
            or current.amount < _required_decimal(parameters, "minimum_amount")
        ):
            return None
        if parameters["minimum_price"] is not None and current.close < _required_decimal(
            parameters, "minimum_price"
        ):
            return None
        previous_close = history[-1].close
        daily_return = current.close / previous_close - Decimal("1")
        minimum_return = parameters["minimum_daily_return"]
        maximum_return = parameters["maximum_daily_return"]
        if minimum_return is not None and daily_return < _required_decimal(
            parameters, "minimum_daily_return"
        ):
            return None
        if maximum_return is not None and daily_return > _required_decimal(
            parameters, "maximum_daily_return"
        ):
            return None
        return ScanCandidate(
            instrument_id=instrument.id,
            score=ratio,
            matched_at=current.timestamp,
            reference_price=current.close,
            reason_code="VOLUME_ANOMALY",
            reason="当前成交量达到此前历史均量的可配置倍数。",
            metrics={
                "current_volume": _decimal_metric(current.volume),
                "average_volume": _decimal_metric(average_volume),
                "volume_ratio": _decimal_metric(ratio),
                "current_amount": _decimal_metric(current.amount),
                "current_close": _decimal_metric(current.close),
                "daily_return": _decimal_metric(daily_return),
                "window": window,
            },
        )


class LimitUpPullbackScanner(BaseScanner):
    metadata = ScannerMetadata(
        scanner_key="limit_up_pullback",
        display_name="涨停后回落起涨区",
        description="使用可配置近似规则识别涨停后回落至前一日收盘附近的标的。",
        version="1.0.0",
        supported_timeframes=(MarketTimeframe.DAY_1,),
        parameter_definitions=(
            ScannerParameterDefinition(
                name="lookback_days",
                parameter_type=ScannerParameterType.INTEGER,
                description="向前查找涨停近似K线的交易日数量",
                display_name="回溯交易日数",
                unit="交易日",
                default=20,
                min_value=2,
                max_value=500,
            ),
            ScannerParameterDefinition(
                name="limit_up_threshold",
                parameter_type=ScannerParameterType.DECIMAL,
                description="涨停近似收益率阈值",
                display_name="涨停判定阈值",
                unit="%",
                default=Decimal("0.095"),
                min_value=Decimal("0"),
                max_value=Decimal("1"),
            ),
            ScannerParameterDefinition(
                name="baseline_tolerance",
                parameter_type=ScannerParameterType.DECIMAL,
                description="当前价格与起涨基准价的最大距离",
                display_name="基准价容差",
                unit="%",
                default=Decimal("0.05"),
                min_value=Decimal("0"),
                max_value=Decimal("1"),
            ),
            ScannerParameterDefinition(
                name="minimum_days_after_limit_up",
                parameter_type=ScannerParameterType.INTEGER,
                description="涨停近似日至当前的最小交易日间隔",
                display_name="涨停后最短间隔",
                unit="交易日",
                default=2,
                min_value=1,
                max_value=500,
            ),
            ScannerParameterDefinition(
                name="maximum_days_after_limit_up",
                parameter_type=ScannerParameterType.INTEGER,
                description="可选最大交易日间隔",
                display_name="涨停后最长间隔",
                unit="交易日",
                nullable=True,
                min_value=1,
                max_value=500,
            ),
            ScannerParameterDefinition(
                name="require_current_above_baseline",
                parameter_type=ScannerParameterType.BOOLEAN,
                description="要求当前价格不低于起涨基准价",
                display_name="当前价格不低于起涨基准价",
                default=True,
            ),
            ScannerParameterDefinition(
                name="minimum_current_volume_ratio",
                parameter_type=ScannerParameterType.DECIMAL,
                description="可选当前成交量相对历史均量下限",
                display_name="当前成交量最低比例",
                unit="倍",
                nullable=True,
                min_value=Decimal("0"),
            ),
        ),
    )

    def scan(
        self,
        context: ScannerContext,
        instrument: Instrument,
        bars: Sequence[StrategyBar],
    ) -> ScanCandidate | None:
        parameters = self.validate_parameters(context.parameters)
        eligible = _eligible_bars(context, instrument, bars)
        if len(eligible) < 3:
            return None
        current_index = len(eligible) - 1
        current = eligible[current_index]
        lookback = int(parameters["lookback_days"] or 0)
        minimum_days = int(parameters["minimum_days_after_limit_up"] or 0)
        maximum_days_value = parameters["maximum_days_after_limit_up"]
        maximum_days = None if maximum_days_value is None else int(maximum_days_value)
        threshold = _required_decimal(parameters, "limit_up_threshold")
        tolerance = _required_decimal(parameters, "baseline_tolerance")
        start_index = max(1, current_index - lookback)
        selected: tuple[StrategyBar, Decimal, Decimal, Decimal, int] | None = None
        for index in range(current_index - 1, start_index - 1, -1):
            days_since = current_index - index
            if days_since < minimum_days or (
                maximum_days is not None and days_since > maximum_days
            ):
                continue
            previous_close = eligible[index - 1].close
            if previous_close <= 0:
                continue
            limit_bar = eligible[index]
            limit_return = limit_bar.close / previous_close - Decimal("1")
            if limit_return < threshold:
                continue
            distance = abs(current.close - previous_close) / previous_close
            if distance > tolerance:
                continue
            if (
                bool(parameters["require_current_above_baseline"])
                and current.close < previous_close
            ):
                continue
            selected = (limit_bar, limit_return, previous_close, distance, days_since)
            break
        if selected is None:
            return None
        volume_ratio: Decimal | None = None
        minimum_volume_ratio = parameters["minimum_current_volume_ratio"]
        if minimum_volume_ratio is not None:
            history = eligible[max(0, current_index - lookback) : current_index]
            if not history:
                return None
            average = sum((bar.volume for bar in history), Decimal("0")) / Decimal(len(history))
            if average <= 0:
                return None
            volume_ratio = current.volume / average
            if volume_ratio < _required_decimal(parameters, "minimum_current_volume_ratio"):
                return None
        limit_bar, limit_return, baseline, distance, days_since = selected
        return ScanCandidate(
            instrument_id=instrument.id,
            score=Decimal("1") - distance,
            matched_at=current.timestamp,
            reference_price=current.close,
            reason_code="LIMIT_UP_PULLBACK_APPROXIMATION",
            reason=("使用可配置近似规则识别涨停后回落起涨区。该规则并非交易所权威涨停判定。"),
            metrics={
                "limit_up_date": limit_bar.timestamp.isoformat(),
                "limit_up_return": _decimal_metric(limit_return),
                "limit_up_close": _decimal_metric(limit_bar.close),
                "baseline_price": _decimal_metric(baseline),
                "current_close": _decimal_metric(current.close),
                "distance_to_baseline": _decimal_metric(distance),
                "days_since_limit_up": days_since,
                "current_volume_ratio": _decimal_metric(volume_ratio),
            },
        )


def _required_decimal(parameters: Mapping[str, ScannerParameterValue], name: str) -> Decimal:
    value = parameters[name]
    if not isinstance(value, Decimal):
        raise ScannerError("SCANNER_INVALID_PARAMETER", f"parameter '{name}' must be decimal")
    return value


class ScannerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], Scanner]] = {}

    def register(self, scanner_key: str, factory: Callable[[], Scanner]) -> None:
        key = non_empty(scanner_key, "scanner_key")
        if key in self._factories:
            raise ScannerError("SCANNER_ALREADY_REGISTERED", f"scanner '{key}' already exists")
        scanner = factory()
        if scanner.metadata.scanner_key != key:
            raise ScannerError(
                "SCANNER_INVALID_REGISTRATION", "scanner key does not match metadata"
            )
        self._factories[key] = factory

    def create(self, scanner_key: str) -> Scanner:
        try:
            return self._factories[scanner_key]()
        except KeyError as exc:
            raise ScannerError(
                "SCANNER_NOT_FOUND", f"scanner '{scanner_key}' does not exist"
            ) from exc

    def list_metadata(self) -> list[ScannerMetadata]:
        return [self._factories[key]().metadata for key in sorted(self._factories)]


def register_builtin_scanners(registry: ScannerRegistry) -> None:
    registry.register("limit_up_pullback", LimitUpPullbackScanner)
    registry.register("volume_anomaly", VolumeAnomalyScanner)


def stored_scanner_parameters(
    parameters: Mapping[str, ScannerParameterValue],
) -> dict[str, StoredScannerParameter]:
    values: dict[str, StoredScannerParameter] = {}
    for name in sorted(parameters):
        value = parameters[name]
        values[name] = format(value.normalize(), "f") if isinstance(value, Decimal) else value
    return values


def stored_scanner_metrics(
    metrics: Mapping[str, ScannerMetricValue],
) -> dict[str, str | int | bool | None]:
    values: dict[str, str | int | bool | None] = {}
    for name in sorted(metrics):
        value = metrics[name]
        values[name] = format(value.normalize(), "f") if isinstance(value, Decimal) else value
    return values


def scanner_request_fingerprint(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def scanner_required_history_bars(
    scanner_key: str, parameters: Mapping[str, ScannerParameterValue]
) -> int:
    """Return the minimum deterministic daily-bar count needed by one rule."""

    if scanner_key == "volume_anomaly":
        return int(parameters.get("volume_window") or 20) + 1
    if scanner_key == "limit_up_pullback":
        return int(parameters.get("lookback_days") or 20) + 1
    raise ScannerError("SCANNER_NOT_FOUND", f"scanner '{scanner_key}' does not exist")


def is_st_instrument(instrument: Instrument) -> bool:
    """Centralized ST classification using formal metadata first and name fallback."""

    metadata_value = instrument.metadata.get("is_st")
    if isinstance(metadata_value, bool):
        return metadata_value
    normalized = instrument.name.strip().upper().replace("\uff33\uff34", "ST")
    return normalized.startswith(("ST", "*ST", "S*ST"))


def is_delisting_instrument(instrument: Instrument) -> bool:
    """Identify delisting-consolidation shares from formal metadata or name."""

    metadata_value = instrument.metadata.get("is_delisting")
    if isinstance(metadata_value, bool):
        return metadata_value
    status = str(instrument.metadata.get("security_status", "")).strip().upper()
    if status in {"DELISTING", "DELISTING_CONSOLIDATION", "TERMINATING"}:
        return True
    return "退市" in instrument.name or instrument.name.strip().upper().startswith("退")


@dataclass(slots=True, kw_only=True)
class ScanRun:
    scanner_key: str
    scanner_version: str
    parameters: dict[str, StoredScannerParameter]
    universe_type: str
    instrument_ids: tuple[UUID, ...]
    timeframe: MarketTimeframe
    as_of: datetime
    status: ScanRunStatus
    idempotency_key: str
    request_fingerprint: str
    correlation_id: UUID
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW
    universe_filters: dict[str, object] = field(default_factory=dict)
    source_code: str = "MINIQMT"
    total_instruments: int = 0
    excluded_instruments: int = 0
    data_ready_instruments: int = 0
    backfill_requested: int = 0
    backfill_failed: int = 0
    insufficient_history: int = 0
    failed_instruments: int = 0
    progress_percent: int = 0
    cancel_requested: bool = False
    backfill_requested_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    instruments_scanned: int = 0
    matches_found: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.scanner_key = non_empty(self.scanner_key, "scanner_key")
        self.scanner_version = non_empty(self.scanner_version, "scanner_version")
        self.universe_type = non_empty(self.universe_type, "universe_type")
        self.idempotency_key = non_empty(self.idempotency_key, "idempotency_key")
        if len(self.idempotency_key) > 128:
            raise ValueError("idempotency_key must not exceed 128 characters")
        self.request_fingerprint = non_empty(self.request_fingerprint, "request_fingerprint")
        if len(self.request_fingerprint) != 64:
            raise ValueError("request_fingerprint must be SHA-256 hex")
        self.instrument_ids = tuple(sorted(set(self.instrument_ids), key=str))
        if (
            self.universe_type == ScanUniverseType.CUSTOM_INSTRUMENTS.value
            and not self.instrument_ids
        ):
            raise ValueError("instrument_ids must not be empty")
        if self.timeframe is not MarketTimeframe.DAY_1:
            raise ValueError("only DAY_1 scans are supported")
        self.as_of = as_utc(self.as_of, "as_of")
        counters = (
            self.total_instruments,
            self.excluded_instruments,
            self.data_ready_instruments,
            self.backfill_requested,
            self.backfill_failed,
            self.insufficient_history,
            self.instruments_scanned,
            self.matches_found,
            self.failed_instruments,
        )
        if any(value < 0 for value in counters):
            raise ValueError("scan counters must be non-negative")
        if not 0 <= self.progress_percent <= 100:
            raise ValueError("progress_percent must be between zero and one hundred")
        for name in ("started_at", "completed_at", "failed_at"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, as_utc(value, name))
        if self.backfill_requested_at is not None:
            self.backfill_requested_at = as_utc(self.backfill_requested_at, "backfill_requested_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")

    def mark_running(self, occurred_at: datetime) -> None:
        if self.status not in {
            ScanRunStatus.CREATED,
            ScanRunStatus.QUEUED,
            ScanRunStatus.RESOLVING,
            ScanRunStatus.CHECKING_DATA,
            ScanRunStatus.BACKFILLING,
        }:
            raise ValueError("scan run cannot start from its current status")
        now = as_utc(occurred_at, "occurred_at")
        self.status = ScanRunStatus.RUNNING
        self.started_at = self.started_at or now
        self.updated_at = now

    def mark_phase(
        self, status: ScanRunStatus, occurred_at: datetime, *, progress_percent: int
    ) -> None:
        if status not in {
            ScanRunStatus.QUEUED,
            ScanRunStatus.RESOLVING,
            ScanRunStatus.CHECKING_DATA,
            ScanRunStatus.BACKFILLING,
            ScanRunStatus.RUNNING,
        }:
            raise ValueError("invalid in-progress scan phase")
        if not 0 <= progress_percent <= 99:
            raise ValueError("in-progress percent must be between zero and ninety-nine")
        now = as_utc(occurred_at, "occurred_at")
        self.status = status
        self.started_at = self.started_at or (now if status is not ScanRunStatus.QUEUED else None)
        self.progress_percent = progress_percent
        self.updated_at = now

    def mark_completed(self, occurred_at: datetime, instruments: int, matches: int) -> None:
        if self.status is not ScanRunStatus.RUNNING:
            raise ValueError("only RUNNING scan runs can complete")
        if instruments < 0 or matches < 0 or matches > instruments:
            raise ValueError("invalid scan counters")
        now = as_utc(occurred_at, "occurred_at")
        self.status = ScanRunStatus.COMPLETED
        self.instruments_scanned = instruments
        self.matches_found = matches
        self.progress_percent = 100
        self.completed_at = now
        self.updated_at = now

    def mark_partial(self, occurred_at: datetime, instruments: int, matches: int) -> None:
        self.mark_completed(occurred_at, instruments, matches)
        self.status = ScanRunStatus.PARTIAL

    def request_cancel(self, occurred_at: datetime) -> None:
        if self.status in {
            ScanRunStatus.COMPLETED,
            ScanRunStatus.PARTIAL,
            ScanRunStatus.FAILED,
            ScanRunStatus.CANCELED,
        }:
            raise ValueError("completed scan run cannot be canceled")
        now = as_utc(occurred_at, "occurred_at")
        self.cancel_requested = True
        self.updated_at = now

    def mark_canceled(self, occurred_at: datetime) -> None:
        now = as_utc(occurred_at, "occurred_at")
        self.status = ScanRunStatus.CANCELED
        self.completed_at = now
        self.updated_at = now

    def mark_failed(self, occurred_at: datetime, code: str, message: str) -> None:
        now = as_utc(occurred_at, "occurred_at")
        self.status = ScanRunStatus.FAILED
        self.failed_at = now
        self.error_code = non_empty(code, "error_code")[:64]
        self.error_message = non_empty(message, "error_message")[:512]
        self.updated_at = now


@dataclass(slots=True, kw_only=True)
class ScanRunMember:
    scan_run_id: UUID
    instrument_id: UUID
    symbol: str
    exchange: str
    instrument_name: str
    status: ScanMemberStatus
    reason_code: str | None = None
    reason: str | None = None
    bars_available: int = 0
    required_bars: int = 0
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.symbol = non_empty(self.symbol, "symbol")
        self.exchange = non_empty(self.exchange, "exchange")
        self.instrument_name = non_empty(self.instrument_name, "instrument_name")
        if self.bars_available < 0 or self.required_bars < 0:
            raise ValueError("bar counters must be non-negative")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScanResult:
    scan_run_id: UUID
    instrument_id: UUID
    rank: int
    score: Decimal
    matched_at: datetime
    reference_price: Decimal
    reason_code: str
    reason: str
    metrics: dict[str, str | int | bool | None]
    id: UUID = field(default_factory=uuid4)
    schema_version: int = 1
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("rank must start at one")
        if not self.score.is_finite() or self.score < 0:
            raise ValueError("score must be finite and non-negative")
        if not self.reference_price.is_finite() or self.reference_price <= 0:
            raise ValueError("reference_price must be positive")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        object.__setattr__(self, "matched_at", as_utc(self.matched_at, "matched_at"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))
        object.__setattr__(self, "reason_code", non_empty(self.reason_code, "reason_code"))
        object.__setattr__(self, "reason", non_empty(self.reason, "reason"))
