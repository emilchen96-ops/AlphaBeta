"""N01 information facts, events and source ingestion.

Revision ID: 0012_n01
Revises: 0011_sc01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_n01"
down_revision: str | None = "0011_sc01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
UTC_NOW = sa.text("timezone('utc', now())")


def upgrade() -> None:
    op.create_table(
        "information_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "source_type IN ('MANUAL','RSS','ANNOUNCEMENT','OTHER')",
            name=op.f("ck_information_sources_information_source_type_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_information_sources")),
        sa.UniqueConstraint("source_key", name=op.f("uq_information_sources_source_key")),
    )
    op.create_index(
        "ix_information_sources_type_enabled",
        "information_sources",
        ["source_type", "enabled"],
    )
    op.create_table(
        "information_ingestion_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("fetched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inserted_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duplicate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.String(512), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "status IN ('RUNNING','COMPLETED','FAILED')",
            name=op.f("ck_information_ingestion_runs_information_ingestion_status_valid"),
        ),
        sa.CheckConstraint(
            "fetched_count >= 0 AND inserted_count >= 0 AND duplicate_count >= 0 "
            "AND failed_count >= 0",
            name=op.f("ck_information_ingestion_runs_information_ingestion_counters_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["information_sources.id"],
            name=op.f("fk_information_ingestion_runs_source_id_information_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_information_ingestion_runs")),
    )
    op.create_index(
        "ix_information_ingestion_source_started",
        "information_ingestion_runs",
        ["source_id", "started_at"],
    )
    op.create_index(
        "ix_information_ingestion_status_started",
        "information_ingestion_runs",
        ["status", "started_at"],
    )
    op.create_table(
        "raw_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=True),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "length(content_hash) = 64", name=op.f("ck_raw_documents_raw_document_hash_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["information_sources.id"],
            name=op.f("fk_raw_documents_source_id_information_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["information_ingestion_runs.id"],
            name=op.f("fk_raw_documents_ingestion_run_id_information_ingestion_runs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_raw_documents")),
        sa.UniqueConstraint("content_hash", name=op.f("uq_raw_documents_content_hash")),
        sa.UniqueConstraint(
            "source_id", "external_id", name=op.f("uq_raw_documents_source_external_id")
        ),
    )
    op.create_index(
        "ix_raw_documents_source_received", "raw_documents", ["source_id", "received_at"]
    )
    op.create_index("ix_raw_documents_published", "raw_documents", ["published_at"])
    op.create_table(
        "information_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("raw_document_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_title", sa.String(1024), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE','ARCHIVED')",
            name=op.f("ck_information_items_information_item_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_document_id"],
            ["raw_documents.id"],
            name=op.f("fk_information_items_raw_document_id_raw_documents"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_information_items")),
        sa.UniqueConstraint("raw_document_id", name=op.f("uq_information_items_raw_document")),
    )
    op.create_index("ix_information_items_published", "information_items", ["published_at"])
    op.create_index("ix_information_items_received", "information_items", ["received_at"])
    op.create_table(
        "market_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("information_item_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(1024), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("importance", sa.Numeric(5, 4), nullable=True),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "event_type IN ('COMPANY_ANNOUNCEMENT','COMPANY_NEWS','INDUSTRY','MACRO',"
            "'REGULATION','PRODUCT','EARNINGS','OTHER')",
            name=op.f("ck_market_events_market_event_type_valid"),
        ),
        sa.CheckConstraint(
            "direction IN ('POSITIVE','NEGATIVE','NEUTRAL','MIXED','UNKNOWN')",
            name=op.f("ck_market_events_market_event_direction_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','ARCHIVED')",
            name=op.f("ck_market_events_market_event_status_valid"),
        ),
        sa.CheckConstraint(
            "importance IS NULL OR (importance >= 0 AND importance <= 1)",
            name=op.f("ck_market_events_market_event_importance_range"),
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name=op.f("ck_market_events_market_event_schema_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["information_item_id"],
            ["information_items.id"],
            name=op.f("fk_market_events_information_item_id_information_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_events")),
        sa.UniqueConstraint("information_item_id", name=op.f("uq_market_events_information_item")),
    )
    op.create_index("ix_market_events_type_time", "market_events", ["event_type", "event_at"])
    op.create_index("ix_market_events_direction_time", "market_events", ["direction", "event_at"])
    op.create_table(
        "event_instrument_links",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_event_instrument_links_event_instrument_confidence_range"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["market_events.id"],
            ondelete="RESTRICT",
            name=op.f("fk_event_instrument_links_event_id_market_events"),
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            ondelete="RESTRICT",
            name=op.f("fk_event_instrument_links_instrument_id_instruments"),
        ),
        sa.PrimaryKeyConstraint(
            "event_id", "instrument_id", name=op.f("pk_event_instrument_links")
        ),
    )
    op.create_index(
        "ix_event_instrument_links_instrument",
        "event_instrument_links",
        ["instrument_id", "event_id"],
    )
    op.create_table(
        "event_theme_links",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("theme_key", sa.String(128), nullable=False),
        sa.Column("theme_name", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["market_events.id"],
            ondelete="RESTRICT",
            name=op.f("fk_event_theme_links_event_id_market_events"),
        ),
        sa.PrimaryKeyConstraint("event_id", "theme_key", name=op.f("pk_event_theme_links")),
    )
    op.create_index("ix_event_theme_links_theme", "event_theme_links", ["theme_key", "event_id"])


def downgrade() -> None:
    op.drop_index("ix_event_theme_links_theme", table_name="event_theme_links")
    op.drop_table("event_theme_links")
    op.drop_index("ix_event_instrument_links_instrument", table_name="event_instrument_links")
    op.drop_table("event_instrument_links")
    op.drop_index("ix_market_events_direction_time", table_name="market_events")
    op.drop_index("ix_market_events_type_time", table_name="market_events")
    op.drop_table("market_events")
    op.drop_index("ix_information_items_received", table_name="information_items")
    op.drop_index("ix_information_items_published", table_name="information_items")
    op.drop_table("information_items")
    op.drop_index("ix_raw_documents_published", table_name="raw_documents")
    op.drop_index("ix_raw_documents_source_received", table_name="raw_documents")
    op.drop_table("raw_documents")
    op.drop_index(
        "ix_information_ingestion_status_started", table_name="information_ingestion_runs"
    )
    op.drop_index(
        "ix_information_ingestion_source_started", table_name="information_ingestion_runs"
    )
    op.drop_table("information_ingestion_runs")
    op.drop_index("ix_information_sources_type_enabled", table_name="information_sources")
    op.drop_table("information_sources")
