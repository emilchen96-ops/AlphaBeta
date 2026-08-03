"""A01 public API schemas with forbidden secret/trading fields."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AIProviderStatusResponse(BaseModel):
    provider_key: str
    model: str
    model_name: str
    selectable_models: list[str]
    configured: bool
    available: bool
    mode: str
    real_provider_available: bool
    base_url_summary: str | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error_code: str | None
    capabilities: list[str]
    warnings: list[str]
    message: str


class AIProviderTestResponse(BaseModel):
    success: bool
    provider_key: str
    model_name: str
    mode: str
    latency_ms: int | None
    error_code: str | None
    warnings: list[str]


class AIProviderTestBody(BaseModel):
    """Select a configured model without allowing provider or secret overrides."""

    model_config = ConfigDict(extra="forbid")
    model_name: str | None = Field(default=None, min_length=1, max_length=128)


class AIAnalysisCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_type: str
    event_ids: list[UUID] = Field(default_factory=list, max_length=50)
    information_item_ids: list[UUID] = Field(default_factory=list, max_length=50)
    instrument_ids: list[UUID] = Field(default_factory=list, max_length=100)
    question: str | None = Field(default=None, max_length=4000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class ResearchEvidenceResponse(BaseModel):
    evidence_id: UUID
    information_item_id: UUID | None
    market_event_id: UUID | None
    evidence_text: str
    evidence_location: str | None


class ResearchInsightResponse(BaseModel):
    insight_id: UUID
    analysis_run_id: UUID
    insight_type: str
    title: str
    summary: str
    impact_direction: str
    importance_score: str
    confidence: str
    time_horizon: str | None
    key_facts: list[str]
    uncertainties: list[str]
    research_questions: list[str]
    structured_output: dict[str, object]
    schema_version: int
    created_at: datetime
    evidence: list[ResearchEvidenceResponse] = Field(default_factory=list)
    label: str = "AI生成，仅供研究参考。"  # noqa: RUF001 - product-required label


class AIAnalysisRunResponse(BaseModel):
    analysis_id: UUID
    provider_key: str
    model_name: str
    analysis_type: str
    prompt_template_key: str
    prompt_version: str
    input_document_ids: list[UUID]
    input_event_ids: list[UUID]
    instrument_ids: list[UUID]
    user_question: str | None
    status: str
    input_token_count: int | None
    output_token_count: int | None
    total_token_count: int | None
    estimated_cost: str | None
    cost_currency: str | None
    is_real_provider: bool
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    error: dict[str, str] | None
    correlation_id: UUID
    created_at: datetime
    replayed: bool = False
    insight: ResearchInsightResponse | None = None
    capabilities: dict[str, bool]


class AIAnalysisRunPageResponse(BaseModel):
    items: list[AIAnalysisRunResponse]
    page: int
    page_size: int
    total: int


class ResearchInsightPageResponse(BaseModel):
    items: list[ResearchInsightResponse]
    page: int
    page_size: int
    total: int


class AIIntegrityResponse(BaseModel):
    analysis_id: UUID
    valid: bool
    issues: list[dict[str, str]]
