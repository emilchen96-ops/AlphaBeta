"""Add versioned user screening definitions and immutable run links.

Revision ID: 0025_sc02c
Revises: 0024_sc02a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025_sc02c"
down_revision: str | None = "0024_sc02a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_screening_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("current_version >= 1", name="user_screening_version_positive"),
        sa.CheckConstraint(
            "status IN ('DRAFT','ACTIVE','ARCHIVED')",
            name="user_screening_status_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_user_screening_definitions_name"),
    )
    op.create_index(
        "ix_user_screening_status_updated",
        "user_screening_definitions",
        ["status", "updated_at"],
    )
    op.create_table(
        "user_screening_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("screening_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("screening_spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["screening_id"], ["user_screening_definitions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "screening_id", "version_number", name="uq_user_screening_versions_number"
        ),
    )
    op.create_index(
        "ix_user_screening_versions_screening",
        "user_screening_versions",
        ["screening_id", "created_at"],
    )
    op.create_table(
        "user_screening_run_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_run_id", sa.Uuid(), nullable=False),
        sa.Column("screening_id", sa.Uuid(), nullable=False),
        sa.Column("screening_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["screening_id"], ["user_screening_definitions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["screening_version_id"], ["user_screening_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_run_id", name="uq_user_screening_run_links_run"),
    )
    op.create_index(
        "ix_user_screening_run_links_screening",
        "user_screening_run_links",
        ["screening_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_screening_run_links_screening", table_name="user_screening_run_links")
    op.drop_table("user_screening_run_links")
    op.drop_index("ix_user_screening_versions_screening", table_name="user_screening_versions")
    op.drop_table("user_screening_versions")
    op.drop_index("ix_user_screening_status_updated", table_name="user_screening_definitions")
    op.drop_table("user_screening_definitions")
