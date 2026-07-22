"""HTTP contracts for D02 reference market data."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from alphadesk_domain.market_reference import (
    CalendarSessionType,
    FactorConvention,
    InstrumentLifecycleType,
    InstrumentTradingState,
)


class ReferenceSyncRequest(BaseModel):
    start: date | None = None
    end: date | None = None
    universe: str = Field(default="research", max_length=64)
    instrument_ids: list[UUID] = Field(default_factory=list, max_length=500)
    provider: str = Field(default="fixture", max_length=32)
    dry_run: bool = True
    max_instruments: int = Field(default=30, ge=1, le=500)


class ReferenceSyncResponse(BaseModel):
    kind: str
    provider: str
    requested: int
    received: int
    persisted: int
    dry_run: bool
    warnings: tuple[str, ...]


class CalendarSessionResponse(BaseModel):
    id: UUID
    exchange: str
    session_date: date
    is_open: bool
    previous_open_date: date | None
    next_open_date: date | None
    session_type: CalendarSessionType
    source: str
    fetched_at: datetime


class AdjustmentFactorResponse(BaseModel):
    id: UUID
    instrument_id: UUID
    trade_date: date
    factor: Decimal
    factor_convention: FactorConvention
    source: str
    fetched_at: datetime


class TradingStatusResponse(BaseModel):
    id: UUID
    instrument_id: UUID
    session_date: date
    status: InstrumentTradingState
    suspension_type: str | None
    reason: str | None
    source: str
    fetched_at: datetime


class LifecycleEventResponse(BaseModel):
    id: UUID
    instrument_id: UUID
    event_date: date
    event_type: InstrumentLifecycleType
    reason: str | None
    source: str
    fetched_at: datetime
    metadata: dict[str, object]


class MarketReferenceStatusResponse(BaseModel):
    calendar_provider: str
    adjustment_provider: str
    suspension_provider: str
    provider_configured: bool
    calendar_sessions: int
    open_sessions: int
    calendar_start: date | None
    calendar_end: date | None
    latest_completed_session: date | None
    adjustment_factors: int
    adjustment_instruments: int
    latest_factor_date: date | None
    qfq_ready_instruments: int
    trading_statuses: int
    suspended_sessions: int
    latest_status_date: date | None
    lifecycle_events: int
    lifecycle_instruments: int
    raw_price_ready: bool
    adjusted_price_ready: bool
    calendar_ready: bool
    suspension_ready: bool
    scanner_ready: bool
    strategy_ready: bool
    backtest_ready: bool
    replay_ready: bool
    warnings: tuple[str, ...]
