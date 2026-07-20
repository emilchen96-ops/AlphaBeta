"""BT01 public HTTP contracts; calculated facts are response-only."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class BacktestFeeBody(BaseModel):
    commission_rate: str = "0.0003"
    minimum_commission: str = "5"
    stamp_duty_rate: str = "0.0005"
    transfer_fee_rate: str = "0.00001"


class BacktestSlippageBody(BaseModel):
    basis_points: str = "0"
    maximum_slippage: str | None = None


class BacktestCreateBody(BaseModel):
    strategy_key: str = Field(min_length=2, max_length=64)
    parameters: dict[str, str | int | bool] = Field(default_factory=dict)
    instrument_ids: list[UUID] = Field(min_length=1, max_length=200)
    timeframe: str = "DAY_1"
    start_at: datetime
    end_at: datetime
    initial_cash: str
    order_type: str = "LIMIT"
    time_in_force: str = "DAY"
    fee_configuration: BacktestFeeBody = Field(default_factory=BacktestFeeBody)
    slippage_configuration: BacktestSlippageBody = Field(default_factory=BacktestSlippageBody)
    maximum_volume_participation: str | None = None
    benchmark_symbol: str | None = None
    data_source_code: str | None = Field(default=None, min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)


class BacktestRunResponse(BaseModel):
    id: UUID
    idempotency_key: str
    strategy_key: str
    strategy_version: str
    status: str
    strategy_run_id: UUID | None
    account_id: UUID | None
    bars_processed: int
    sessions_processed: int
    signals_generated: int
    risk_passed: int
    risk_rejected: int
    risk_reviewed: int
    orders_created: int
    fills_generated: int
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    replayed: bool = False
    metrics: dict[str, Any] | None = None
    configuration: dict[str, Any] | None = None


class BacktestPageResponse(BaseModel):
    items: list[BacktestRunResponse]
    page: int
    page_size: int
    total: int


class BacktestMetricResponse(BaseModel):
    metrics: dict[str, Any]


class BacktestCollectionResponse(BaseModel):
    items: list[dict[str, Any]]


class BacktestIntegrityResponse(BaseModel):
    run_id: UUID
    passed: bool
    checked_at: datetime
    issues: list[dict[str, Any]]
