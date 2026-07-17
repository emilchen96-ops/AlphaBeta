"""R01-B persisted risk decisions and per-rule facts.

Revision ID: 0009_r01
Revises: 0008_s02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_r01"
down_revision: str | None = "0008_s02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_NOW = sa.text("timezone('utc', now())")
JSON_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.drop_constraint(op.f("ck_risk_decisions_target_required"), "risk_decisions", type_="check")
    op.drop_constraint(op.f("ck_risk_decisions_risk_decision_valid"), "risk_decisions", type_="check")
    op.drop_constraint(op.f("fk_risk_decisions_order_id_orders"), "risk_decisions", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_risk_decisions_order_id_orders"),
        "risk_decisions", "orders", ["order_id"], ["id"],
        ondelete="RESTRICT", deferrable=True, initially="DEFERRED",
    )
    for name, column in (
        ("idempotency_key", sa.Column("idempotency_key", sa.String(128), nullable=True)),
        ("request_fingerprint", sa.Column("request_fingerprint", sa.String(64), nullable=True)),
        ("request_id", sa.Column("request_id", sa.Uuid(), nullable=True)),
        ("source_type", sa.Column("source_type", sa.String(32), nullable=True)),
        ("source_id", sa.Column("source_id", sa.Uuid(), nullable=True)),
        ("account_id", sa.Column("account_id", sa.Uuid(), nullable=True)),
        ("instrument_id", sa.Column("instrument_id", sa.Uuid(), nullable=True)),
        ("overall_decision", sa.Column("overall_decision", sa.String(32), nullable=True)),
        ("estimated_notional", sa.Column("estimated_notional", sa.Numeric(24, 8))),
        ("projected_instrument_weight", sa.Column("projected_instrument_weight", sa.Numeric(12, 8))),
        ("projected_total_exposure", sa.Column("projected_total_exposure", sa.Numeric(12, 8))),
        ("limits_snapshot", sa.Column("limits_snapshot", postgresql.JSONB(), server_default=JSON_EMPTY, nullable=False)),
        ("account_snapshot", sa.Column("account_snapshot", postgresql.JSONB(), server_default=JSON_EMPTY, nullable=False)),
        ("instrument_snapshot", sa.Column("instrument_snapshot", postgresql.JSONB(), server_default=JSON_EMPTY, nullable=False)),
        ("warnings", sa.Column("warnings", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False)),
        ("evaluated_at", sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True)),
        ("schema_version", sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False)),
    ):
        op.add_column("risk_decisions", column)

    op.execute(sa.text("""
        UPDATE risk_decisions rd SET
          idempotency_key = 'legacy:' || rd.id::text,
          request_fingerprint = md5(rd.id::text) || md5(rd.id::text),
          request_id = rd.id,
          source_type = 'MANUAL_ORDER',
          account_id = o.account_id,
          instrument_id = o.instrument_id,
          overall_decision = rd.decision,
          evaluated_at = rd.decided_at
        FROM orders o WHERE o.id = rd.order_id
    """))
    op.execute(sa.text("""
        UPDATE risk_decisions rd SET
          idempotency_key = 'legacy:' || rd.id::text,
          request_fingerprint = md5(rd.id::text) || md5(rd.id::text),
          request_id = rd.id,
          source_type = 'STRATEGY_SIGNAL',
          source_id = rd.signal_id,
          account_id = s.account_id,
          instrument_id = s.instrument_id,
          overall_decision = rd.decision,
          evaluated_at = rd.decided_at
        FROM signals s WHERE s.id = rd.signal_id AND rd.order_id IS NULL
    """))
    for name in ("idempotency_key", "request_fingerprint", "request_id", "source_type", "account_id", "instrument_id", "overall_decision", "evaluated_at"):
        op.alter_column("risk_decisions", name, nullable=False)
    op.create_foreign_key(op.f("fk_risk_decisions_account_id_trading_accounts"), "risk_decisions", "trading_accounts", ["account_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key(op.f("fk_risk_decisions_instrument_id_instruments"), "risk_decisions", "instruments", ["instrument_id"], ["id"], ondelete="RESTRICT")
    op.create_unique_constraint(op.f("uq_risk_decisions_idempotency_key"), "risk_decisions", ["idempotency_key"])
    op.create_unique_constraint(op.f("uq_risk_decisions_request_id"), "risk_decisions", ["request_id"])
    op.create_check_constraint(op.f("ck_risk_decisions_risk_decision_valid"), "risk_decisions", "overall_decision IN ('ALLOW','REJECT','REQUIRE_CONFIRMATION')")
    op.create_check_constraint(op.f("ck_risk_decisions_schema_version_positive"), "risk_decisions", "schema_version >= 1")
    op.create_index("ix_risk_decisions_account_evaluated", "risk_decisions", ["account_id", "evaluated_at"])
    op.create_index("ix_risk_decisions_instrument_evaluated", "risk_decisions", ["instrument_id", "evaluated_at"])
    op.create_index("ix_risk_decisions_source", "risk_decisions", ["source_type", "source_id"])
    for name in ("decision", "rule_code", "reason", "metrics", "decided_at"):
        op.drop_column("risk_decisions", name)

    op.create_table(
        "risk_rule_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("risk_decision_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("rule_key", sa.String(128), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("observed_value", postgresql.JSONB()),
        sa.Column("limit_value", postgresql.JSONB()),
        sa.Column("metadata", postgresql.JSONB(), server_default=JSON_EMPTY, nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=UTC_NOW, nullable=False),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_risk_rule_evaluations_seq_positive")),
        sa.CheckConstraint("decision IN ('ALLOW','REJECT','REQUIRE_CONFIRMATION')", name=op.f("ck_risk_rule_evaluations_decision_valid")),
        sa.ForeignKeyConstraint(["risk_decision_id"], ["risk_decisions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("risk_decision_id", "seq", name=op.f("uq_risk_rule_evaluations_decision_seq")),
        sa.UniqueConstraint("risk_decision_id", "rule_key", name=op.f("uq_risk_rule_evaluations_decision_rule")),
    )
    op.create_index("ix_risk_rule_evaluations_decision_seq", "risk_rule_evaluations", ["risk_decision_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_risk_rule_evaluations_decision_seq", table_name="risk_rule_evaluations")
    op.drop_table("risk_rule_evaluations")
    op.drop_constraint(op.f("fk_risk_decisions_order_id_orders"), "risk_decisions", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_risk_decisions_order_id_orders"),
        "risk_decisions", "orders", ["order_id"], ["id"], ondelete="RESTRICT",
    )
    op.drop_constraint(op.f("ck_risk_decisions_schema_version_positive"), "risk_decisions", type_="check")
    op.drop_constraint(op.f("ck_risk_decisions_risk_decision_valid"), "risk_decisions", type_="check")
    op.add_column("risk_decisions", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("risk_decisions", sa.Column("metrics", postgresql.JSONB(), server_default=JSON_EMPTY, nullable=False))
    op.add_column("risk_decisions", sa.Column("reason", sa.Text()))
    op.add_column("risk_decisions", sa.Column("rule_code", sa.String(128), nullable=True))
    op.add_column("risk_decisions", sa.Column("decision", sa.String(32), nullable=True))
    op.execute(sa.text("UPDATE risk_decisions SET decided_at=evaluated_at, decision=overall_decision, rule_code='R01_AGGREGATE'"))
    for name in ("decided_at", "decision", "rule_code"):
        op.alter_column("risk_decisions", name, nullable=False)
    op.create_check_constraint(op.f("ck_risk_decisions_risk_decision_valid"), "risk_decisions", "decision IN ('ALLOW','REJECT','REQUIRE_CONFIRMATION')")
    op.create_check_constraint(op.f("ck_risk_decisions_target_required"), "risk_decisions", "signal_id IS NOT NULL OR order_id IS NOT NULL")
    op.drop_index("ix_risk_decisions_source", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_instrument_evaluated", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_account_evaluated", table_name="risk_decisions")
    op.drop_constraint(op.f("uq_risk_decisions_request_id"), "risk_decisions", type_="unique")
    op.drop_constraint(op.f("uq_risk_decisions_idempotency_key"), "risk_decisions", type_="unique")
    op.drop_constraint(op.f("fk_risk_decisions_instrument_id_instruments"), "risk_decisions", type_="foreignkey")
    op.drop_constraint(op.f("fk_risk_decisions_account_id_trading_accounts"), "risk_decisions", type_="foreignkey")
    for name in ("schema_version", "evaluated_at", "warnings", "instrument_snapshot", "account_snapshot", "limits_snapshot", "projected_total_exposure", "projected_instrument_weight", "estimated_notional", "overall_decision", "instrument_id", "account_id", "source_id", "source_type", "request_id", "request_fingerprint", "idempotency_key"):
        op.drop_column("risk_decisions", name)
