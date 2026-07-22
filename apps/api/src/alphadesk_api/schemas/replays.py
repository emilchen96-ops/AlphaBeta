"""RT01 public HTTP contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from alphadesk_api.schemas.backtests import BacktestFeeBody, BacktestSlippageBody
from alphadesk_domain.market_reference import PriceAdjustmentMode


class ReplayCreateBody(BaseModel):
    strategy_key: str = Field(min_length=2, max_length=64)
    parameters: dict[str, str | int | bool] = Field(default_factory=dict)
    instrument_ids: list[UUID] = Field(min_length=1, max_length=200)
    start_at: datetime
    end_at: datetime
    initial_cash: str
    order_type: str = "LIMIT"
    time_in_force: str = "DAY"
    fee_configuration: BacktestFeeBody = Field(default_factory=BacktestFeeBody)
    slippage_configuration: BacktestSlippageBody = Field(default_factory=BacktestSlippageBody)
    maximum_volume_participation: str | None = None
    risk_configuration_reference: str = Field(default="r01-default-v1", max_length=128)
    speed_mode: str = "MANUAL"
    data_source_code: str | None = Field(default=None, min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    strategy_price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW


class ReplayControlBody(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    expected_run_version: int = Field(ge=0)


class ReplaySpeedBody(ReplayControlBody):
    speed_mode: str


class ReplayRunResponse(BaseModel):
    id: UUID
    idempotency_key: str
    status: str
    row_version: int
    strategy_key: str
    strategy_version: str
    account_id: UUID | None
    strategy_run_id: UUID | None
    current_session_date: datetime | str | None
    current_session_index: int
    total_sessions: int
    speed_mode: str
    bars_processed: int
    signals_generated: int
    orders_created: int
    fills_generated: int
    started_at: datetime | None
    paused_at: datetime | None
    completed_at: datetime | None
    stopped_at: datetime | None
    failed_at: datetime | None
    error_code: str | None
    error_message: str | None
    last_heartbeat_at: datetime | None
    worker_online: bool
    created_at: datetime
    updated_at: datetime
    replayed: bool = False
    configuration: dict[str, Any] | None = None
    final_summary: dict[str, Any] | None = None
    integrity_summary: dict[str, Any] | None = None


class ReplayPageResponse(BaseModel):
    items: list[ReplayRunResponse]
    page: int
    page_size: int
    total: int


class ReplayCollectionResponse(BaseModel):
    items: list[dict[str, Any]]


class ReplayEventPageResponse(ReplayCollectionResponse):
    page: int
    page_size: int
    total: int


class ReplayStateResponse(BaseModel):
    state: dict[str, Any]


class ReplayIntegrityResponse(BaseModel):
    replay_run_id: UUID
    ok: bool
    checked_at: datetime
    issues: list[str]
    facts: dict[str, Any]
