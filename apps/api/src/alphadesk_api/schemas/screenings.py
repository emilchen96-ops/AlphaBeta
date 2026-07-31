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
    node_type: Literal["CONDITION"] = "CONDITION"
    condition_key: str = Field(min_length=2, max_length=64, pattern=r"^[A-Z][A-Z0-9_]+$")
    condition_version: str | None = Field(default=None, min_length=1, max_length=32)
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ScreeningConditionGroupBody(StrictBody):
    node_type: Literal["GROUP"] = "GROUP"
    operator: Literal["AND", "OR"] = "AND"
    children: list["ScreeningConditionBody | ScreeningConditionGroupBody"] = Field(
        min_length=1,
        max_length=20,
    )


class RankingRuleBody(StrictBody):
    field: Literal[
        "score",
        "volume_multiple",
        "range_position",
        "distance_to_anchor",
        "current_close",
    ] = "score"
    direction: Literal["ASC", "DESC"] = "DESC"


class ScreeningSpecPayload(StrictBody):
    schema_version: Literal[1, 2] = 1
    name: str = Field(min_length=1, max_length=128)
    origin: Literal[
        "USER_STRUCTURED",
        "USER_CORRECTED",
        "NATURAL_LANGUAGE",
        "AI_ASSISTED",
        "BUILTIN_TEMPLATE",
        "API",
    ] = "USER_STRUCTURED"
    universe_spec: UniverseSpecBody = Field(default_factory=UniverseSpecBody)
    as_of_date: date
    timeframe: Literal["DAY_1"] = "DAY_1"
    conditions: list[ScreeningConditionBody] = Field(default_factory=list, max_length=32)
    root_group: ScreeningConditionGroupBody | None = None
    exclusions: dict[str, Any] = Field(default_factory=dict)
    ranking_rules: list[RankingRuleBody] = Field(default_factory=list, max_length=8)
    top_n: int | None = Field(default=None, ge=1, le=10_000)
    price_adjustment_mode: Literal["RAW"] = "RAW"


class ScreeningCreateBody(ScreeningSpecPayload):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    use_existing_data_only: bool = False


class ScreeningTextParseBody(StrictBody):
    text: str = Field(min_length=1, max_length=1000)
    as_of_date: date | None = None
    universe: UniverseSpecBody | None = None
    allow_ai_assistance: bool = True


class ScreeningSpecBody(StrictBody):
    screening_spec: ScreeningSpecPayload


class RecognizedConditionResponse(BaseModel):
    condition_key: str
    display_name: str
    matched_expression: str


class AppliedDefaultResponse(BaseModel):
    condition_key: str
    parameter_name: str
    display_name: str
    value: str | int | bool | None
    explanation: str


class ScreeningPreviewResponse(BaseModel):
    summary: str
    universe: str
    conditions: list[str]
    screening_time: str
    ranking: list[str]
    defaults: list[str]
    data_requirements: list[str]
    parser_source: str
    no_future_data_rule: str
    data_ready: bool
    data_readiness_message: str
    can_execute: bool
    notices: list[str]


class ScreeningParseResponse(BaseModel):
    parse_status: Literal["COMPLETE", "PARTIAL", "AMBIGUOUS", "UNSUPPORTED"]
    parser_source: Literal["LOCAL_RULES", "AI_ASSISTED"]
    screening_spec: dict[str, Any] | None
    recognized_conditions: list[RecognizedConditionResponse]
    ambiguities: list[str]
    unsupported_fragments: list[str]
    defaults_applied: list[AppliedDefaultResponse]
    preview: ScreeningPreviewResponse | None
    can_execute: bool


class ScreeningValidationResponse(BaseModel):
    valid: bool
    parse_status: Literal["COMPLETE"]
    screening_spec: dict[str, Any]
    recognized_conditions: list[RecognizedConditionResponse]
    preview: ScreeningPreviewResponse
    can_execute: bool


class ScreeningPreviewEnvelopeResponse(BaseModel):
    screening_spec: dict[str, Any]
    preview: ScreeningPreviewResponse
    can_execute: bool


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
    display_unit: str | None = None
    precision: int | None = None
    placeholder: str | None = None
    help_text: str | None = None


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
    aliases: list[str] = Field(default_factory=list)
    deprecated: bool = False
    replacement_condition_key: str | None = None


class ScreeningTemplateResponse(BaseModel):
    template_key: str
    display_name: str
    description: str
    timeframe: str = "日线"
    required_data: str = "MiniQMT历史日线"
    enabled: bool = True
    spec: dict[str, Any]


class UserScreeningWriteBody(StrictBody):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=1000)
    source_text: str | None = Field(default=None, max_length=1000)
    screening_spec: ScreeningSpecPayload
    origin: str = Field(default="USER", min_length=1, max_length=32)


class UserScreeningResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    source_text: str | None
    origin: str
    current_version: int
    status: Literal["DRAFT", "ACTIVE", "ARCHIVED"]
    screening_spec: dict[str, Any]
    summary: str
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None


class UserScreeningPageResponse(BaseModel):
    items: list[UserScreeningResponse]
    page: int
    page_size: int
    total: int


class UserScreeningRunBody(StrictBody):
    as_of_date: date
    idempotency_key: str | None = Field(default=None, max_length=128)
    use_existing_data_only: bool = False


class ScreeningRetryBody(StrictBody):
    idempotency_key: str | None = Field(default=None, max_length=128)


class ScreeningWatchlistBody(StrictBody):
    instrument_ids: list[UUID] = Field(min_length=1, max_length=200)
    watchlist_id: UUID | None = None
    new_watchlist_name: str | None = Field(default=None, max_length=128)
    realtime_monitor: bool = False


class ScreeningWatchlistResponse(BaseModel):
    watchlist_id: UUID
    succeeded: int
    already_exists: int
    failed: int


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
    data_requirement_plan: dict[str, Any] | None = None
    data_preparation: dict[str, Any] | None = None


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
    current_stage: str
    stage_label: str
    current_action: str
    downloading_count: int
    provider_failed_count: int
    quality_failed_count: int
    not_applicable_count: int
    listing_history_short_count: int
    currently_suspended_count: int
    stale_data_count: int
    data_gap_count: int
    calendar_mismatch_count: int
    calendar_mismatch_dates: list[str]
    excluded_count: int
    backfill_total_batches: int
    backfill_pending_batches: int | None
    backfill_processed_batches: int
    backfill_progress_percent: int | None
    backfill_estimated_remaining_seconds: int | None


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
