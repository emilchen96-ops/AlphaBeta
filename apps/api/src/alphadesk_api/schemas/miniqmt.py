"""HTTP schemas for the MiniQMT read-only market-data boundary."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return value


class AgentStatusRequest(BaseModel):
    state: str = Field(max_length=32)
    checked_at: datetime
    agent_version: str | None = Field(default=None, max_length=32)
    last_market_time: datetime | None = None
    last_received_at: datetime | None = None
    last_minute_bar_time: datetime | None = None
    last_catalog_sync_at: datetime | None = None
    catalog_instrument_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=512)

    _validate_times = field_validator(
        "checked_at",
        "last_market_time",
        "last_received_at",
        "last_minute_bar_time",
        "last_catalog_sync_at",
    )(_aware)


class InstrumentCatalogItem(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    exchange: str = Field(pattern=r"^(SSE|SZSE|BSE)$")
    market: str = Field(default="CN_A", max_length=32)
    name: str = Field(min_length=1, max_length=256)
    asset_type: str = Field(pattern=r"^(STOCK|ETF)$")
    currency: str = "CNY"
    lot_size: Decimal = Field(gt=0)
    price_tick: Decimal = Field(gt=0)
    timezone: str = "Asia/Shanghai"
    is_active: bool = True
    listed_at: date | None = None
    delisted_at: date | None = None
    provider_symbol: str = Field(pattern=r"^\d{6}\.(SH|SZ|BJ)$")


class InstrumentCatalogIngestRequest(BaseModel):
    sync_token: UUID
    complete: bool = False
    items: list[InstrumentCatalogItem] = Field(min_length=1, max_length=500)


class QuoteSnapshotIngestRequest(BaseModel):
    schema_version: int = 1
    instrument_id: UUID
    symbol: str = Field(min_length=1, max_length=64)
    exchange: str = Field(min_length=1, max_length=16)
    market_time: datetime
    received_at: datetime
    ingested_at: datetime
    last_price: Decimal
    open_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    previous_close: Decimal | None = None
    volume: Decimal | None = None
    amount: Decimal | None = None
    bid_price_1: Decimal | None = None
    ask_price_1: Decimal | None = None
    bid_volume_1: Decimal | None = None
    ask_volume_1: Decimal | None = None
    upper_limit_price: Decimal | None = None
    lower_limit_price: Decimal | None = None
    trading_status: str = "UNKNOWN"
    source_sequence: str | None = Field(default=None, max_length=128)

    _validate_times = field_validator("market_time", "received_at", "ingested_at")(_aware)


class SubscriptionOperationResult(BaseModel):
    instrument_id: UUID
    provider_symbol: str = Field(min_length=1, max_length=32)
    success: bool
    subscription_id: str | None = Field(default=None, max_length=64)
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=512)


class SubscriptionSyncReportRequest(BaseModel):
    subscriptions: list[SubscriptionOperationResult] = Field(default_factory=list, max_length=2000)
    unsubscriptions: list[SubscriptionOperationResult] = Field(
        default_factory=list, max_length=2000
    )


class MinuteBarIngestItem(BaseModel):
    instrument_id: UUID
    timeframe: str = "MINUTE_1"
    bar_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    amount: Decimal | None = None
    source_updated_at: datetime | None = None

    _validate_times = field_validator("bar_time", "source_updated_at")(_aware)


class MinuteBarIngestRequest(BaseModel):
    items: list[MinuteBarIngestItem] = Field(min_length=1, max_length=1000)


class HistoryBackfillRequest(BaseModel):
    instrument_ids: list[UUID] = Field(min_length=1, max_length=50)
    timeframe: str
    start_at: datetime
    end_at: datetime

    _validate_times = field_validator("start_at", "end_at")(_aware)


class HistoryRequestResultRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=512)


class TemporarySubscriptionRequest(BaseModel):
    instrument_id: UUID
    enabled: bool


class GenericResponse(BaseModel):
    schema_version: int = 1
    data: dict[str, Any]
