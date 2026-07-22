"""S01-C public strategy research API contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from alphadesk_domain.market_reference import PriceAdjustmentMode


class StrategyParameterResponse(BaseModel):
    name: str
    type: str
    required: bool
    default: str | int | bool | None
    description: str
    min_value: str | int | None
    max_value: str | int | None
    choices: list[str]


class StrategyCatalogResponse(BaseModel):
    strategy_key: str
    display_name: str
    description: str
    version: str
    supported_timeframes: list[str]
    parameter_schema_version: int
    parameters: list[StrategyParameterResponse]


class StrategyRunCreateBody(BaseModel):
    strategy_key: str = Field(min_length=2, max_length=64)
    parameters: dict[str, str | int | bool] = Field(default_factory=dict)
    instrument_ids: list[UUID] = Field(min_length=1, max_length=100)
    timeframe: str
    start_at: datetime
    end_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=128)
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW


class StrategyRunResponse(BaseModel):
    run_id: UUID
    strategy_key: str
    strategy_version: str
    status: str
    timeframe: str
    instrument_ids: list[UUID]
    start_at: datetime
    end_at: datetime
    bars_processed: int
    signals_generated: int
    warnings: list[str]
    replayed: bool = False
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW


class StrategyRunDetailResponse(StrategyRunResponse):
    parameters: dict[str, str | int | bool]
    instruments: list[dict[str, Any]]
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
    error: dict[str, str] | None
    capabilities: dict[str, bool]


class StrategyRunPageResponse(BaseModel):
    items: list[StrategyRunDetailResponse]
    page: int
    page_size: int
    total: int


class StrategySignalResponse(BaseModel):
    signal_id: UUID
    strategy_run_id: UUID
    sequence_number: int
    strategy_key: str
    strategy_version: str
    instrument_id: UUID
    instrument: dict[str, str | None]
    signal_type: str
    side: str
    generated_at: datetime
    bar_timestamp: datetime
    quantity: str | None
    target_weight: str | None
    reference_price: str | None
    confidence: str | None
    reason: str | None
    schema_version: int


class StrategySignalPageResponse(BaseModel):
    items: list[StrategySignalResponse]
    page: int
    page_size: int
    total: int


class StrategyExperimentCreateBody(BaseModel):
    strategy_key: str = Field(min_length=2, max_length=64)
    parameter_grid: dict[str, list[str | int | bool]]
    instrument_ids: list[UUID] = Field(min_length=1, max_length=100)
    timeframe: str
    start_at: datetime
    end_at: datetime
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW
    idempotency_key: str = Field(min_length=1, max_length=128)


class StrategyExperimentResponse(BaseModel):
    experiment_id: UUID
    idempotency_key: str
    strategy_key: str
    strategy_version: str
    environment: str
    timeframe: str
    instrument_ids: list[UUID]
    start_at: datetime
    end_at: datetime
    parameter_grid: dict[str, list[str | int | bool]]
    combination_count: int
    runs_completed: int
    runs_failed: int
    total_signals: int
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    error: dict[str, str] | None
    correlation_id: UUID
    created_at: datetime
    updated_at: datetime
    replayed: bool = False
    capabilities: dict[str, bool]


class StrategyExperimentPageResponse(BaseModel):
    items: list[StrategyExperimentResponse]
    page: int
    page_size: int
    total: int


class StrategyExperimentRunResponse(BaseModel):
    combination_index: int
    normalized_parameters: dict[str, str | int | bool]
    strategy_run_id: UUID
    run_status: str
    bars_processed: int
    signals_generated: int
    warning: str | None


class StrategyExperimentComparisonResponse(BaseModel):
    combination_index: int
    normalized_parameters: dict[str, str | int | bool]
    strategy_run_id: UUID
    run_status: str
    bars_processed: int
    total_signals: int
    buy_signals: int
    sell_signals: int
    first_signal_at: datetime | None
    last_signal_at: datetime | None
    signaled_instrument_count: int
    warning: str | None


class StrategySignalOverlapResponse(BaseModel):
    left_combination_index: int
    right_combination_index: int
    intersection_count: int
    union_count: int
    similarity: str
