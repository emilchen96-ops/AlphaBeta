"""Add the real TradingAgents graph audit trail and artifacts.

Revision ID: 0031_ta01_graph
Revises: 0030_ta01_workbench
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0031_ta01_graph"
down_revision: str | None = "0030_ta01_workbench"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column(
        "ai_research_tasks",
        sa.Column(
            "engine_key",
            sa.String(length=64),
            server_default="tradingagents_graph",
            nullable=False,
        ),
    )
    op.add_column(
        "ai_research_tasks",
        sa.Column("engine_version", sa.String(length=128), server_default="", nullable=False),
    )
    op.add_column(
        "ai_research_tasks",
        sa.Column("checkpoint_key", sa.String(length=256), server_default="", nullable=False),
    )
    op.add_column(
        "ai_research_tasks",
        sa.Column("execution_attempt", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "ai_research_tasks",
        sa.Column("last_checkpoint_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_constraint("ai_research_agent_role_valid", "ai_research_agent_runs", type_="check")
    op.create_check_constraint(
        "ai_research_agent_role_valid",
        "ai_research_agent_runs",
        "role IN ('MARKET_ANALYST', 'SENTIMENT_ANALYST', 'TECHNICAL_ANALYST', "
        "'FUNDAMENTAL_ANALYST', 'NEWS_ANALYST', 'BULL_RESEARCHER', 'BEAR_RESEARCHER', "
        "'RISK_REVIEWER', 'RESEARCH_MANAGER', 'TRADER', 'AGGRESSIVE_RISK_ANALYST', "
        "'NEUTRAL_RISK_ANALYST', 'CONSERVATIVE_RISK_ANALYST', 'PORTFOLIO_MANAGER')",
    )

    op.create_table(
        "ai_research_workflow_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("node_name", sa.String(length=128), nullable=False),
        sa.Column("agent_role", sa.String(length=32), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.CheckConstraint("sequence >= 0", name="ai_research_event_sequence_non_negative"),
        sa.ForeignKeyConstraint(["task_id"], ["ai_research_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "sequence", name="uq_ai_research_events_task_sequence"),
    )
    op.create_index(
        "ix_ai_research_events_task_sequence",
        "ai_research_workflow_events",
        ["task_id", "sequence"],
    )

    op.create_table(
        "ai_research_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_key", sa.String(length=128), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("metadata", jsonb, nullable=False),
        sa.Column("source_ids", jsonb, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal >= 0", name="ai_research_artifact_ordinal_non_negative"),
        sa.ForeignKeyConstraint(["task_id"], ["ai_research_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "artifact_key", name="uq_ai_research_artifacts_task_key"),
    )
    op.create_index(
        "ix_ai_research_artifacts_task_ordinal",
        "ai_research_artifacts",
        ["task_id", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_research_artifacts_task_ordinal", table_name="ai_research_artifacts")
    op.drop_table("ai_research_artifacts")
    op.drop_index("ix_ai_research_events_task_sequence", table_name="ai_research_workflow_events")
    op.drop_table("ai_research_workflow_events")
    op.drop_constraint("ai_research_agent_role_valid", "ai_research_agent_runs", type_="check")
    op.create_check_constraint(
        "ai_research_agent_role_valid",
        "ai_research_agent_runs",
        "role IN ('MARKET_ANALYST', 'TECHNICAL_ANALYST', 'FUNDAMENTAL_ANALYST', "
        "'NEWS_ANALYST', 'BULL_RESEARCHER', 'BEAR_RESEARCHER', 'RISK_REVIEWER', "
        "'RESEARCH_MANAGER')",
    )
    for column in (
        "last_checkpoint_at",
        "execution_attempt",
        "checkpoint_key",
        "engine_version",
        "engine_key",
    ):
        op.drop_column("ai_research_tasks", column)
