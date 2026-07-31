"""Add durable TA01 multi-agent AI research workbench.

Revision ID: 0030_ta01_workbench
Revises: 0029_bt_batches
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0030_ta01_workbench"
down_revision: str | None = "0029_bt_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "ai_research_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("depth", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("current_stage", sa.String(length=256), nullable=False),
        sa.Column("request_snapshot", jsonb, nullable=False),
        sa.Column("data_snapshot", jsonb, nullable=False),
        sa.Column("warnings", jsonb, nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.CheckConstraint("depth IN ('FAST', 'STANDARD', 'DEEP')", name="ai_research_task_depth_valid"),
        sa.CheckConstraint(
            "status IN ('CREATED', 'PREPARING_DATA', 'RUNNING_AGENTS', 'DEBATING', "
            "'RISK_REVIEW', 'GENERATING_REPORT', 'COMPLETED', 'PARTIALLY_COMPLETED', "
            "'FAILED', 'CANCELED')",
            name="ai_research_task_status_valid",
        ),
        sa.CheckConstraint("progress_percent >= 0 AND progress_percent <= 100", name="ai_research_task_progress_range"),
        sa.CheckConstraint("start_date <= end_date", name="ai_research_task_date_range_valid"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_ai_research_tasks_idempotency_key"),
    )
    op.create_index("ix_ai_research_tasks_status_created", "ai_research_tasks", ["status", "created_at"])
    op.create_index("ix_ai_research_tasks_instrument_created", "ai_research_tasks", ["instrument_id", "created_at"])

    op.create_table(
        "ai_research_agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("structured_output", jsonb, nullable=False),
        sa.Column("citations", jsonb, nullable=False),
        sa.Column("input_token_count", sa.Integer(), nullable=True),
        sa.Column("output_token_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.CheckConstraint(
            "role IN ('MARKET_ANALYST', 'TECHNICAL_ANALYST', 'FUNDAMENTAL_ANALYST', "
            "'NEWS_ANALYST', 'BULL_RESEARCHER', 'BEAR_RESEARCHER', 'RISK_REVIEWER', "
            "'RESEARCH_MANAGER')",
            name="ai_research_agent_role_valid",
        ),
        sa.CheckConstraint("status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'SKIPPED')", name="ai_research_agent_status_valid"),
        sa.CheckConstraint("ordinal >= 0", name="ai_research_agent_ordinal_non_negative"),
        sa.ForeignKeyConstraint(["task_id"], ["ai_research_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "role", name="uq_ai_research_agent_runs_task_role"),
    )
    op.create_index("ix_ai_research_agent_runs_task_ordinal", "ai_research_agent_runs", ["task_id", "ordinal"])

    op.create_table(
        "ai_research_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("stance", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.String(length=32), nullable=False),
        sa.Column("sections", jsonb, nullable=False),
        sa.Column("citations", jsonb, nullable=False),
        sa.Column("limitations", jsonb, nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.CheckConstraint("schema_version >= 1", name="ai_research_report_schema_positive"),
        sa.ForeignKeyConstraint(["task_id"], ["ai_research_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_ai_research_reports_task"),
    )


def downgrade() -> None:
    op.drop_table("ai_research_reports")
    op.drop_index("ix_ai_research_agent_runs_task_ordinal", table_name="ai_research_agent_runs")
    op.drop_table("ai_research_agent_runs")
    op.drop_index("ix_ai_research_tasks_instrument_created", table_name="ai_research_tasks")
    op.drop_index("ix_ai_research_tasks_status_created", table_name="ai_research_tasks")
    op.drop_table("ai_research_tasks")
