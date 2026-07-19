"""A01 grounded AI research runs, insights and evidence.

Revision ID: 0013_a01
Revises: 0012_n01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013_a01"
down_revision: str | None = "0012_n01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.create_table(
        "ai_analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("analysis_type", sa.String(32), nullable=False),
        sa.Column("prompt_template_key", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("input_document_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("input_event_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("instrument_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("user_question", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("input_token_count", sa.Integer(), nullable=True),
        sa.Column("output_token_count", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(20, 8), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "analysis_type IN ('EVENT_SUMMARY','INSTRUMENT_IMPACT','MULTI_EVENT_SYNTHESIS',"
            "'RESEARCH_QUESTION')",
            name=op.f("ck_ai_analysis_runs_ai_analysis_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('CREATED','RUNNING','COMPLETED','FAILED')",
            name=op.f("ck_ai_analysis_runs_ai_analysis_status_valid"),
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name=op.f("ck_ai_analysis_runs_ai_analysis_fingerprint_sha256"),
        ),
        sa.CheckConstraint(
            "input_token_count IS NULL OR input_token_count >= 0",
            name=op.f("ck_ai_analysis_runs_ai_analysis_input_tokens_non_negative"),
        ),
        sa.CheckConstraint(
            "output_token_count IS NULL OR output_token_count >= 0",
            name=op.f("ck_ai_analysis_runs_ai_analysis_output_tokens_non_negative"),
        ),
        sa.CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name=op.f("ck_ai_analysis_runs_ai_analysis_cost_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_analysis_runs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_ai_analysis_runs_idempotency_key")),
    )
    op.create_index(
        "ix_ai_analysis_type_created", "ai_analysis_runs", ["analysis_type", "created_at"]
    )
    op.create_index("ix_ai_analysis_status_created", "ai_analysis_runs", ["status", "created_at"])
    op.create_index("ix_ai_analysis_correlation", "ai_analysis_runs", ["correlation_id"])
    op.create_table(
        "research_insights",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("insight_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("impact_direction", sa.String(16), nullable=False),
        sa.Column("importance_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("time_horizon", sa.String(128), nullable=True),
        sa.Column("key_facts", postgresql.JSONB(), nullable=False),
        sa.Column("uncertainties", postgresql.JSONB(), nullable=False),
        sa.Column("research_questions", postgresql.JSONB(), nullable=False),
        sa.Column("structured_output", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "impact_direction IN ('POSITIVE','NEGATIVE','NEUTRAL','MIXED','UNKNOWN')",
            name=op.f("ck_research_insights_research_insight_direction_valid"),
        ),
        sa.CheckConstraint(
            "importance_score >= 0 AND importance_score <= 100",
            name=op.f("ck_research_insights_research_insight_importance_range"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_research_insights_research_insight_confidence_range"),
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name=op.f("ck_research_insights_research_insight_schema_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["ai_analysis_runs.id"],
            name=op.f("fk_research_insights_analysis_run_id_ai_analysis_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_insights")),
        sa.UniqueConstraint("analysis_run_id", name=op.f("uq_research_insights_analysis_run")),
    )
    op.create_index(
        "ix_research_insights_type_created", "research_insights", ["insight_type", "created_at"]
    )
    op.create_table(
        "research_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("insight_id", sa.Uuid(), nullable=False),
        sa.Column("information_item_id", sa.Uuid(), nullable=True),
        sa.Column("market_event_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_text", sa.String(2000), nullable=False),
        sa.Column("evidence_location", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "(information_item_id IS NOT NULL)::integer + "
            "(market_event_id IS NOT NULL)::integer = 1",
            name=op.f("ck_research_evidence_research_evidence_exactly_one_source"),
        ),
        sa.CheckConstraint(
            "length(evidence_text) <= 2000",
            name=op.f("ck_research_evidence_research_evidence_text_length"),
        ),
        sa.ForeignKeyConstraint(
            ["insight_id"],
            ["research_insights.id"],
            ondelete="RESTRICT",
            name=op.f("fk_research_evidence_insight_id_research_insights"),
        ),
        sa.ForeignKeyConstraint(
            ["information_item_id"],
            ["information_items.id"],
            ondelete="RESTRICT",
            name=op.f("fk_research_evidence_information_item_id_information_items"),
        ),
        sa.ForeignKeyConstraint(
            ["market_event_id"],
            ["market_events.id"],
            ondelete="RESTRICT",
            name=op.f("fk_research_evidence_market_event_id_market_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_evidence")),
    )
    op.create_index(
        "ix_research_evidence_insight", "research_evidence", ["insight_id", "created_at"]
    )
    op.create_index("ix_research_evidence_item", "research_evidence", ["information_item_id"])
    op.create_index("ix_research_evidence_event", "research_evidence", ["market_event_id"])


def downgrade() -> None:
    op.drop_index("ix_research_evidence_event", table_name="research_evidence")
    op.drop_index("ix_research_evidence_item", table_name="research_evidence")
    op.drop_index("ix_research_evidence_insight", table_name="research_evidence")
    op.drop_table("research_evidence")
    op.drop_index("ix_research_insights_type_created", table_name="research_insights")
    op.drop_table("research_insights")
    op.drop_index("ix_ai_analysis_correlation", table_name="ai_analysis_runs")
    op.drop_index("ix_ai_analysis_status_created", table_name="ai_analysis_runs")
    op.drop_index("ix_ai_analysis_type_created", table_name="ai_analysis_runs")
    op.drop_table("ai_analysis_runs")
