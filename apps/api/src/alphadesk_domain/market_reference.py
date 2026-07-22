"""D02 market-reference facts and deterministic A-share price semantics."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from alphadesk_domain.market import MarketBar
from alphadesk_domain.values import as_utc, decimal_value, non_empty, utc_now

SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketReferenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CalendarSessionType(StrEnum):
    NORMAL = "NORMAL"
    HOLIDAY = "HOLIDAY"
    WEEKEND = "WEEKEND"
    SPECIAL_CLOSED = "SPECIAL_CLOSED"
    UNKNOWN = "UNKNOWN"


class PriceAdjustmentMode(StrEnum):
    RAW = "RAW"
    QFQ = "QFQ"


class FactorConvention(StrEnum):
    NONE = "NONE"
    TUSHARE_CUMULATIVE = "TUSHARE_CUMULATIVE"


class InstrumentTradingState(StrEnum):
    TRADING = "TRADING"
    SUSPENDED = "SUSPENDED"
    RESUMED = "RESUMED"
    UNKNOWN = "UNKNOWN"


class InstrumentLifecycleType(StrEnum):
    LISTED = "LISTED"
    DELISTED = "DELISTED"
    SUSPENDED_LONG_TERM = "SUSPENDED_LONG_TERM"
    RESUMED = "RESUMED"
    STATUS_CHANGED = "STATUS_CHANGED"


@dataclass(slots=True, kw_only=True)
class TradingCalendarSession:
    exchange: str
    session_date: date
    is_open: bool
    session_type: CalendarSessionType
    source: str
    fetched_at: datetime
    id: UUID = field(default_factory=uuid4)
    previous_open_date: date | None = None
    next_open_date: date | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.exchange = non_empty(self.exchange, "exchange").upper()
        if self.exchange not in {"SHSE", "SZSE"}:
            raise MarketReferenceError("MARKET_CALENDAR_NOT_AVAILABLE", "unsupported exchange")
        self.source = non_empty(self.source, "source").upper()
        self.fetched_at = as_utc(self.fetched_at, "fetched_at")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")
        if self.is_open and self.session_type is not CalendarSessionType.NORMAL:
            raise MarketReferenceError(
                "MARKET_CALENDAR_SESSION_NOT_FOUND", "open sessions must be NORMAL"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class AdjustmentFactor:
    instrument_id: UUID
    trade_date: date
    factor: Decimal
    factor_convention: FactorConvention
    source: str
    fetched_at: datetime
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        decimal_value(self.factor, "factor")
        if self.factor <= 0:
            raise MarketReferenceError(
                "MARKET_ADJUSTMENT_FACTOR_NOT_AVAILABLE", "factor must be positive"
            )
        object.__setattr__(self, "source", non_empty(self.source, "source").upper())
        object.__setattr__(self, "fetched_at", as_utc(self.fetched_at, "fetched_at"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentTradingStatus:
    instrument_id: UUID
    session_date: date
    status: InstrumentTradingState
    source: str
    fetched_at: datetime
    id: UUID = field(default_factory=uuid4)
    suspension_type: str | None = None
    reason: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", non_empty(self.source, "source").upper())
        object.__setattr__(self, "fetched_at", as_utc(self.fetched_at, "fetched_at"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentLifecycleEvent:
    instrument_id: UUID
    event_date: date
    event_type: InstrumentLifecycleType
    source: str
    fetched_at: datetime
    id: UUID = field(default_factory=uuid4)
    reason: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", non_empty(self.source, "source").upper())
        object.__setattr__(self, "fetched_at", as_utc(self.fetched_at, "fetched_at"))
        object.__setattr__(self, "created_at", as_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True, kw_only=True)
class AdjustedBar:
    raw_bar: MarketBar
    adjustment_mode: PriceAdjustmentMode
    factor: Decimal
    reference_factor: Decimal

    @property
    def raw_bar_id(self) -> int | None:
        return self.raw_bar.id

    def as_market_bar(self) -> MarketBar:
        if self.adjustment_mode is PriceAdjustmentMode.RAW:
            return self.raw_bar
        ratio = self.factor / self.reference_factor
        return replace(
            self.raw_bar,
            open=self.raw_bar.open * ratio,
            high=self.raw_bar.high * ratio,
            low=self.raw_bar.low * ratio,
            close=self.raw_bar.close * ratio,
            vwap=None if self.raw_bar.vwap is None else self.raw_bar.vwap * ratio,
        )


class TradingCalendarProvider(Protocol):
    async def fetch_calendar(
        self, exchange: str, start: date, end: date
    ) -> list[TradingCalendarSession]: ...


class AdjustmentFactorProvider(Protocol):
    async def fetch_adjustments(
        self, instrument_ids: list[UUID], start: date, end: date
    ) -> list[AdjustmentFactor]: ...


class SuspensionProvider(Protocol):
    async def fetch_suspensions(
        self, instrument_ids: list[UUID], start: date, end: date
    ) -> list[InstrumentTradingStatus]: ...


class InstrumentLifecycleProvider(Protocol):
    async def fetch_lifecycle(
        self, instrument_ids: list[UUID]
    ) -> list[InstrumentLifecycleEvent]: ...


class TradingCalendarService:
    def __init__(self, sessions: list[TradingCalendarSession]) -> None:
        self._sessions = {(item.exchange, item.session_date): item for item in sessions}

    def session(self, exchange: str, value: date) -> TradingCalendarSession:
        try:
            return self._sessions[(exchange.upper(), value)]
        except KeyError as exc:
            raise MarketReferenceError(
                "MARKET_CALENDAR_SESSION_NOT_FOUND", "calendar session is not available"
            ) from exc

    def is_open(self, exchange: str, value: date) -> bool:
        return self.session(exchange, value).is_open

    def sessions_between(
        self, exchange: str, start: date, end: date
    ) -> tuple[TradingCalendarSession, ...]:
        values = [
            item
            for (item_exchange, item_date), item in self._sessions.items()
            if item_exchange == exchange.upper() and start <= item_date <= end
        ]
        if not values:
            raise MarketReferenceError(
                "MARKET_CALENDAR_NOT_AVAILABLE", "calendar range is not available"
            )
        return tuple(sorted(values, key=lambda item: item.session_date))

    def previous_open_date(self, exchange: str, value: date) -> date:
        candidates = [
            item.session_date
            for item in self._sessions.values()
            if item.exchange == exchange.upper() and item.is_open and item.session_date < value
        ]
        if not candidates:
            raise MarketReferenceError(
                "MARKET_CALENDAR_SESSION_NOT_FOUND", "previous open session is not available"
            )
        return max(candidates)

    def next_open_date(self, exchange: str, value: date) -> date:
        candidates = [
            item.session_date
            for item in self._sessions.values()
            if item.exchange == exchange.upper() and item.is_open and item.session_date > value
        ]
        if not candidates:
            raise MarketReferenceError(
                "MARKET_CALENDAR_SESSION_NOT_FOUND", "next open session is not available"
            )
        return min(candidates)

    def latest_completed_session(self, exchange: str, now: datetime) -> date:
        local = now.astimezone(SHANGHAI)
        cutoff = (
            local.date()
            if local.time() >= time(15, 1)
            else local.date().fromordinal(local.date().toordinal() - 1)
        )
        candidates = [
            item.session_date
            for item in self._sessions.values()
            if item.exchange == exchange.upper() and item.is_open and item.session_date <= cutoff
        ]
        if not candidates:
            raise MarketReferenceError(
                "MARKET_CALENDAR_NOT_AVAILABLE", "completed session is not available"
            )
        return max(candidates)

    def common_a_share_sessions(self, start: date, end: date) -> tuple[date, ...]:
        sh = {
            item.session_date for item in self.sessions_between("SHSE", start, end) if item.is_open
        }
        sz = {
            item.session_date for item in self.sessions_between("SZSE", start, end) if item.is_open
        }
        return tuple(sorted(sh & sz))


class AdjustedMarketBarService:
    def adjust(
        self,
        bars: list[MarketBar],
        factors: list[AdjustmentFactor],
        mode: PriceAdjustmentMode,
        *,
        reference_date: date | None = None,
    ) -> tuple[AdjustedBar, ...]:
        if mode is PriceAdjustmentMode.RAW:
            return tuple(
                AdjustedBar(
                    raw_bar=bar,
                    adjustment_mode=mode,
                    factor=Decimal("1"),
                    reference_factor=Decimal("1"),
                )
                for bar in bars
            )
        if mode is not PriceAdjustmentMode.QFQ:
            raise MarketReferenceError(
                "MARKET_ADJUSTMENT_MODE_NOT_SUPPORTED", "only RAW and QFQ are supported"
            )
        by_date = {item.trade_date: item for item in factors}
        dates = [bar.bar_time.date() for bar in bars]
        if not dates:
            return ()
        reference = reference_date or max(dates)
        try:
            reference_factor = by_date[reference].factor
        except KeyError as exc:
            raise MarketReferenceError(
                "MARKET_ADJUSTMENT_FACTOR_NOT_AVAILABLE", "reference factor is unavailable"
            ) from exc
        values: list[AdjustedBar] = []
        for bar in bars:
            try:
                factor = by_date[bar.bar_time.date()].factor
            except KeyError as exc:
                raise MarketReferenceError(
                    "MARKET_ADJUSTMENT_FACTOR_NOT_AVAILABLE", "bar factor is unavailable"
                ) from exc
            values.append(
                AdjustedBar(
                    raw_bar=bar,
                    adjustment_mode=mode,
                    factor=factor,
                    reference_factor=reference_factor,
                )
            )
        return tuple(values)


class TradingStatusService:
    def __init__(self, statuses: list[InstrumentTradingStatus]) -> None:
        self._statuses = {(item.instrument_id, item.session_date): item for item in statuses}

    def status_on(self, instrument_id: UUID, value: date) -> InstrumentTradingState:
        item = self._statuses.get((instrument_id, value))
        return InstrumentTradingState.UNKNOWN if item is None else item.status

    def is_tradable(self, instrument_id: UUID, value: date) -> bool | None:
        status = self.status_on(instrument_id, value)
        if status is InstrumentTradingState.UNKNOWN:
            return None
        return status in {InstrumentTradingState.TRADING, InstrumentTradingState.RESUMED}

    def suspended_sessions(self, instrument_id: UUID, start: date, end: date) -> tuple[date, ...]:
        return tuple(
            sorted(
                item.session_date
                for item in self._statuses.values()
                if item.instrument_id == instrument_id
                and start <= item.session_date <= end
                and item.status is InstrumentTradingState.SUSPENDED
            )
        )
