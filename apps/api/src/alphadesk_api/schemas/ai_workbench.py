"""TA01 public task, agent-step and report schemas."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ResearchTaskCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: UUID
    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    depth: str
    start_date: date
    end_date: date
    idempotency_key: str = Field(min_length=1, max_length=128)


class ResearchAgentStepResponse(BaseModel):
    step_id: UUID
    role: str
    role_label: str
    ordinal: int
    status: str
    title: str
    summary: str
    structured_output: dict[str, object]
    citations: list[dict[str, object]]
    input_token_count: int | None
    output_token_count: int | None
    error: dict[str, str] | None
    started_at: datetime | None
    completed_at: datetime | None


class ResearchReportSummaryResponse(BaseModel):
    report_id: UUID
    title: str
    executive_summary: str
    stance: str
    confidence: str
    schema_version: int
    created_at: datetime


class ResearchReportResponse(ResearchReportSummaryResponse):
    task_id: UUID
    sections: dict[str, object]
    citations: list[dict[str, object]]
    limitations: list[str]
    markdown: str
    disclaimer: str = "AI 生成，仅供研究参考，不构成投资建议。"  # noqa: RUF001


class ResearchWorkflowEventResponse(BaseModel):
    event_id: UUID
    sequence: int
    event_type: str
    status: str
    node_name: str
    agent_role: str | None
    tool_name: str | None
    payload: dict[str, object]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ResearchArtifactResponse(BaseModel):
    artifact_id: UUID
    artifact_key: str
    artifact_type: str
    title: str
    content_markdown: str
    ordinal: int
    metadata: dict[str, object]
    source_ids: list[str]
    created_at: datetime


class ResearchTaskResponse(BaseModel):
    task_id: UUID
    instrument: dict[str, object]
    question: str
    depth: str
    start_date: date
    end_date: date
    provider_key: str
    model_name: str
    engine_key: str
    engine_version: str
    checkpoint_key: str
    execution_attempt: int
    last_checkpoint_at: datetime | None
    is_real_provider: bool
    status: str
    progress_percent: int
    current_stage: str
    warnings: list[str]
    error: dict[str, str] | None
    correlation_id: UUID
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    steps: list[ResearchAgentStepResponse]
    events: list[ResearchWorkflowEventResponse]
    artifacts: list[ResearchArtifactResponse]
    report: ResearchReportSummaryResponse | None
    capabilities: dict[str, bool]


class ResearchTaskPageResponse(BaseModel):
    items: list[ResearchTaskResponse]
    page: int
    page_size: int
    total: int
