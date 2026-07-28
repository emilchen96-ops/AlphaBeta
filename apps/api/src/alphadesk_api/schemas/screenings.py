"""SC02-A structured screening HTTP contracts."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UniverseSpecBody(StrictBody):
    universe_key: Literal["ALL_A_SHARES"] = "ALL_A_SHARES"
    excluded_instrument_ids: list[UUID] = Field(default_factory=list, max_length=1_000)
    exclude_st: bool = False
    exclude_bse: bool = False
    exclude_star_market: bool = False
    exclude_chinext: bool = False


class ScreeningConditionBody(StrictBody):
    condition_key: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]+$")
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class RankingRuleBody(StrictBody):
    field: Literal[
        "score",
        "volume_multiple",
        "range_position",
        "distance_to_anchor",
        "current_close",
    ] = "score"
    direction: Literal["ASC", "DESC"] = "DESC"


class ScreeningCreateBody(StrictBody):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=128)
    origin: Literal["USER_STRUCTURED", "BUILTIN_TEMPLATE", "API"] = "USER_STRUCTURED"
    universe_spec: UniverseSpecBody = Field(default_factory=UniverseSpecBody)
    as_of_date: date
    timeframe: Literal["DAY_1"] = "DAY_1"
    conditions: list[ScreeningConditionBody] = Field(min_length=1, max_length=32)
    exclusions: dict[str, Any] = Field(default_factory=dict)
    ranking_rules: list[RankingRuleBody] = Field(default_factory=list, max_length=8)
    top_n: int | None = Field(default=None, ge=1, le=10_000)
    price_adjustment_mode: Literal["RAW"] = "RAW"
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class ConditionParameterResponse(BaseModel):
    name: str
    display_name: str
    type: str
    description: str
    default: str | int | bool | None
    required: bool
    nullable: bool
    min_value: str | None
    max_value: str | None
    enum_values: list[str]
    unit: str | None


class ConditionDefinitionResponse(BaseModel):
    condition_key: str
    display_name: str
    description: str
    category: str
    parameter_schema: list[ConditionParameterResponse]
    required_fields: list[str]
    required_history_bars: int
    supported_timeframes: list[str]
    price_adjustment_mode: str
    evaluator_key: str
    explanation_template: str
    version: str
    enabled: bool


class ScreeningTemplateResponse(BaseModel):
    template_key: str
    display_name: str
    description: str
    spec: dict[str, Any]


class ScreeningRunResponse(BaseModel):
    screening_id: UUID
    name: str
    status: str
    current_phase: str
    spec: dict[str, Any]
    total_instruments: int
    processed_instruments: int
    ready_instruments: int
    insufficient_data_count: int
    indeterminate_count: int
    failed_count: int
    matched_count: int
    progress_percent: int
    elapsed_ms: int
    query_count: int
    bars_read: int
    batch_count: int
    execution_stats: dict[str, Any]
    error: dict[str, str] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    replayed: bool = False


class ScreeningRunPageResponse(BaseModel):
    items: list[ScreeningRunResponse]
    page: int
    page_size: int
    total: int


class ScreeningProgressResponse(BaseModel):
    screening_id: UUID
    status: str
    total_instruments: int
    processed_instruments: int
    ready_instruments: int
    insufficient_data_count: int
    indeterminate_count: int
    failed_count: int
    matched_count: int
    progress_percent: int
    elapsed_ms: int


class ScreeningResultResponse(BaseModel):
    result_id: UUID
    screening_id: UUID
    rank: int
    instrument_id: UUID
    symbol: str
    exchange: str
    instrument_name: str
    score: str
    reference_price: str
    matched_at: datetime
    reason_code: str
    reason: str
    metrics: dict[str, Any]


class ScreeningResultPageResponse(BaseModel):
    items: list[ScreeningResultResponse]
    page: int
    page_size: int
    total: int
