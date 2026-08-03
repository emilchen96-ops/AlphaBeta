"""TA01 durable multi-agent AI research contracts.

The workbench is research-only.  It deliberately has no dependency on orders,
signals, broker adapters or account ledgers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from alphadesk_domain.values import as_utc, non_empty, utc_now

WORKBENCH_SCHEMA_VERSION = 2
WORKBENCH_PROMPT_VERSION = "ta01.2.0"
TRADINGAGENTS_ENGINE_KEY = "tradingagents_graph"


class ResearchDepth(StrEnum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class ResearchTaskStatus(StrEnum):
    CREATED = "CREATED"
    PREPARING_DATA = "PREPARING_DATA"
    RUNNING_AGENTS = "RUNNING_AGENTS"
    DEBATING = "DEBATING"
    RISK_REVIEW = "RISK_REVIEW"
    GENERATING_REPORT = "GENERATING_REPORT"
    COMPLETED = "COMPLETED"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class ResearchAgentRole(StrEnum):
    MARKET_ANALYST = "MARKET_ANALYST"
    SENTIMENT_ANALYST = "SENTIMENT_ANALYST"
    TECHNICAL_ANALYST = "TECHNICAL_ANALYST"
    FUNDAMENTAL_ANALYST = "FUNDAMENTAL_ANALYST"
    NEWS_ANALYST = "NEWS_ANALYST"
    BULL_RESEARCHER = "BULL_RESEARCHER"
    BEAR_RESEARCHER = "BEAR_RESEARCHER"
    RISK_REVIEWER = "RISK_REVIEWER"
    RESEARCH_MANAGER = "RESEARCH_MANAGER"
    TRADER = "TRADER"
    AGGRESSIVE_RISK_ANALYST = "AGGRESSIVE_RISK_ANALYST"
    NEUTRAL_RISK_ANALYST = "NEUTRAL_RISK_ANALYST"
    CONSERVATIVE_RISK_ANALYST = "CONSERVATIVE_RISK_ANALYST"
    PORTFOLIO_MANAGER = "PORTFOLIO_MANAGER"


class ResearchAgentStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


TERMINAL_TASK_STATUSES = frozenset(
    {
        ResearchTaskStatus.COMPLETED,
        ResearchTaskStatus.PARTIALLY_COMPLETED,
        ResearchTaskStatus.FAILED,
        ResearchTaskStatus.CANCELED,
    }
)


def roles_for_depth(depth: ResearchDepth) -> tuple[ResearchAgentRole, ...]:
    """Return the real TradingAgents graph roles in execution order.

    Depth changes model selection and debate rounds, never silently removes the
    bull/bear or three-way risk discussion chain.
    """

    del depth
    return (
        ResearchAgentRole.MARKET_ANALYST,
        ResearchAgentRole.SENTIMENT_ANALYST,
        ResearchAgentRole.NEWS_ANALYST,
        ResearchAgentRole.FUNDAMENTAL_ANALYST,
        ResearchAgentRole.BULL_RESEARCHER,
        ResearchAgentRole.BEAR_RESEARCHER,
        ResearchAgentRole.RESEARCH_MANAGER,
        ResearchAgentRole.TRADER,
        ResearchAgentRole.AGGRESSIVE_RISK_ANALYST,
        ResearchAgentRole.NEUTRAL_RISK_ANALYST,
        ResearchAgentRole.CONSERVATIVE_RISK_ANALYST,
        ResearchAgentRole.PORTFOLIO_MANAGER,
    )


@dataclass(slots=True, kw_only=True)
class MultiAgentResearchTask:
    instrument_id: UUID
    question: str
    depth: ResearchDepth
    start_date: date
    end_date: date
    provider_key: str
    model_name: str
    idempotency_key: str
    correlation_id: UUID
    engine_key: str = TRADINGAGENTS_ENGINE_KEY
    engine_version: str = ""
    checkpoint_key: str = ""
    execution_attempt: int = 0
    last_checkpoint_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    status: ResearchTaskStatus = ResearchTaskStatus.CREATED
    progress_percent: int = 0
    current_stage: str = "等待开始"
    request_snapshot: dict[str, object] = field(default_factory=dict)
    data_snapshot: dict[str, object] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    canceled_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.question = non_empty(self.question, "question")
        self.provider_key = non_empty(self.provider_key, "provider_key")
        self.model_name = non_empty(self.model_name, "model_name")
        self.idempotency_key = non_empty(self.idempotency_key, "idempotency_key")
        if len(self.question) > 4000:
            raise ValueError("question must not exceed 4000 characters")
        if self.start_date > self.end_date:
            raise ValueError("research date range is invalid")
        if not 0 <= self.progress_percent <= 100:
            raise ValueError("progress_percent must be between zero and 100")
        self.created_at = as_utc(self.created_at, "created_at")
        self.updated_at = as_utc(self.updated_at, "updated_at")

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_TASK_STATUSES

    def advance(self, status: ResearchTaskStatus, progress: int, stage: str) -> None:
        if self.terminal:
            raise ValueError("terminal research task cannot advance")
        now = utc_now()
        if self.started_at is None:
            self.started_at = now
        self.status = status
        self.progress_percent = max(self.progress_percent, min(progress, 99))
        self.current_stage = non_empty(stage, "stage")
        # A reclaimed/retried task must not keep displaying the previous
        # attempt's terminal error while the new attempt is actively running.
        self.error_code = None
        self.error_message = None
        self.completed_at = None
        self.updated_at = now

    def finish(self, *, partial: bool, warnings: tuple[str, ...] = ()) -> None:
        now = utc_now()
        self.status = (
            ResearchTaskStatus.PARTIALLY_COMPLETED if partial else ResearchTaskStatus.COMPLETED
        )
        self.progress_percent = 100
        self.current_stage = "调研报告已生成"
        self.warnings = warnings
        self.error_code = None
        self.error_message = None
        self.completed_at = now
        self.updated_at = now

    def fail(self, code: str, message: str) -> None:
        now = utc_now()
        self.status = ResearchTaskStatus.FAILED
        self.current_stage = "调研失败"
        self.error_code = non_empty(code, "code")[:64]
        self.error_message = non_empty(message, "message")[:1000]
        self.completed_at = now
        self.updated_at = now

    def cancel(self) -> None:
        if self.terminal:
            return
        now = utc_now()
        self.status = ResearchTaskStatus.CANCELED
        self.current_stage = "已取消"
        self.canceled_at = now
        self.updated_at = now

    def retry(self) -> None:
        if self.status is not ResearchTaskStatus.FAILED:
            raise ValueError("only failed research tasks can be retried")
        self.status = ResearchTaskStatus.CREATED
        self.progress_percent = 0
        self.current_stage = "等待重新开始"
        self.error_code = None
        self.error_message = None
        self.started_at = None
        self.completed_at = None
        # The worker increments the attempt exactly when it claims the task.
        # Keeping retry() side-effect free here avoids counting one retry twice.
        self.updated_at = utc_now()


@dataclass(slots=True, kw_only=True)
class MultiAgentResearchStep:
    task_id: UUID
    role: ResearchAgentRole
    ordinal: int
    id: UUID = field(default_factory=uuid4)
    status: ResearchAgentStatus = ResearchAgentStatus.PENDING
    title: str = ""
    summary: str = ""
    structured_output: dict[str, object] = field(default_factory=dict)
    citations: tuple[dict[str, object], ...] = ()
    input_token_count: int | None = None
    output_token_count: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True, kw_only=True)
class MultiAgentResearchReport:
    task_id: UUID
    title: str
    executive_summary: str
    stance: str
    confidence: str
    sections: dict[str, object]
    citations: tuple[dict[str, object], ...]
    limitations: tuple[str, ...]
    markdown: str
    id: UUID = field(default_factory=uuid4)
    schema_version: int = WORKBENCH_SCHEMA_VERSION
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True, kw_only=True)
class MultiAgentResearchWorkflowEvent:
    """Append-only audit event for graph nodes and tool calls."""

    task_id: UUID
    sequence: int
    event_type: str
    status: str
    node_name: str = ""
    agent_role: ResearchAgentRole | None = None
    tool_name: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True, kw_only=True)
class MultiAgentResearchArtifact:
    """A durable independent report produced by one TradingAgents node."""

    task_id: UUID
    artifact_key: str
    artifact_type: str
    title: str
    content_markdown: str
    ordinal: int
    artifact_metadata: dict[str, object] = field(default_factory=dict)
    source_ids: tuple[str, ...] = ()
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredResearchRequest:
    role: ResearchAgentRole
    model_name: str
    system_prompt: str
    payload: dict[str, object]
    schema_name: str
    output_schema: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class StructuredResearchResponse:
    output: dict[str, object]
    input_token_count: int | None = None
    output_token_count: int | None = None
    warnings: tuple[str, ...] = ()


class MultiAgentResearchProvider(Protocol):
    provider_key: str
    model_name: str
    selectable_models: tuple[str, ...]
    configured: bool

    async def complete_structured(
        self, request: StructuredResearchRequest
    ) -> StructuredResearchResponse: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphResearchRunRequest:
    task_id: UUID
    model_name: str
    ticker: str
    company_name: str
    question: str
    depth: ResearchDepth
    start_date: date
    end_date: date
    data_snapshot: dict[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class GraphResearchRunResult:
    engine_version: str
    checkpoint_key: str
    final_decision: str
    complete_report_markdown: str
    artifacts: tuple[MultiAgentResearchArtifact, ...]
    events: tuple[MultiAgentResearchWorkflowEvent, ...]
    source_ids: tuple[str, ...]
    input_token_count: int = 0
    output_token_count: int = 0


class GraphResearchRunError(RuntimeError):
    """A failed Graph run that still carries its durable partial audit trail."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "TRADINGAGENTS_GRAPH_FAILED",
        checkpoint_key: str = "",
        events: tuple[MultiAgentResearchWorkflowEvent, ...] = (),
        artifacts: tuple[MultiAgentResearchArtifact, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.checkpoint_key = checkpoint_key
        self.events = events
        self.artifacts = artifacts


class MultiAgentResearchEngine(Protocol):
    configured: bool

    async def run(self, request: GraphResearchRunRequest) -> GraphResearchRunResult: ...
