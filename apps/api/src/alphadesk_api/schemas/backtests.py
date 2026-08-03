"""BT01 public HTTP contracts; calculated facts are response-only."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from alphadesk_domain.backtest import BacktestExecutionPriceMode
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode


class BacktestFeeBody(BaseModel):
    commission_rate: str = "0.0003"
    minimum_commission: str | None = "5"
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
    order_type: str = "MARKET"
    time_in_force: str = "DAY"
    execution_price_mode: BacktestExecutionPriceMode = BacktestExecutionPriceMode.NEXT_OPEN
    signal_timeframe: MarketTimeframe = MarketTimeframe.MINUTE_1
    auto_prepare_minute_data: bool = True
    optimistic_fill_assumption: bool = False
    # Omitted by legacy API clients that still use fixed strategy quantities.
    # The current web workbench sends an explicit ratio for NEXT_OPEN runs.
    position_size_ratio: str | None = None
    maximum_entry_gap_ratio: str | None = "0.05"
    fee_configuration: BacktestFeeBody = Field(default_factory=BacktestFeeBody)
    slippage_configuration: BacktestSlippageBody = Field(default_factory=BacktestSlippageBody)
    maximum_volume_participation: str | None = None
    benchmark_symbol: str | None = None
    data_source_code: str | None = Field(default=None, min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    strategy_price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW


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
    candidate_session_count: int = 0
    minute_replay_session_count: int = 0
    processed_minute_bar_count: int = 0
    skipped_reason: str | None = None
    data_preparation_summary: dict[str, Any] = Field(default_factory=dict)
    performance_summary: dict[str, Any] = Field(default_factory=dict)
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
