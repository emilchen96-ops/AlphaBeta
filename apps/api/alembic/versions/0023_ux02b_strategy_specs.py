"""Add versioned user strategy specs and immutable backtest snapshots.

Revision ID: 0023_ux02b
Revises: 0022_ux02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_ux02b"
down_revision: str | None = "0022_ux02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_strategy_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.CheckConstraint("current_version >= 1", name="user_strategy_current_version_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_strategy_definitions_archived_updated",
        "user_strategy_definitions",
        ["archived", "updated_at"],
        unique=False,
    )
    op.create_table(
        "user_strategy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "spec_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.CheckConstraint("version_number >= 1", name="user_strategy_version_positive"),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["user_strategy_definitions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "strategy_id",
            "version_number",
            name="uq_user_strategy_versions_number",
        ),
    )
    op.create_index(
        "ix_user_strategy_versions_strategy_created",
        "user_strategy_versions",
        ["strategy_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "research_backtest_specs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("backtest_run_id", sa.Uuid(), nullable=False),
        sa.Column("user_strategy_id", sa.Uuid(), nullable=True),
        sa.Column("user_strategy_version_id", sa.Uuid(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "spec_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["backtest_run_id"], ["backtest_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["user_strategy_id"],
            ["user_strategy_definitions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_strategy_version_id"],
            ["user_strategy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("backtest_run_id", name="uq_research_backtest_specs_run"),
    )
    op.create_index(
        "ix_research_backtest_specs_user_strategy",
        "research_backtest_specs",
        ["user_strategy_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_backtest_specs_user_strategy",
        table_name="research_backtest_specs",
    )
    op.drop_table("research_backtest_specs")
    op.drop_index(
        "ix_user_strategy_versions_strategy_created",
        table_name="user_strategy_versions",
    )
    op.drop_table("user_strategy_versions")
    op.drop_index(
        "ix_user_strategy_definitions_archived_updated",
        table_name="user_strategy_definitions",
    )
    op.drop_table("user_strategy_definitions")
