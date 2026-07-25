"""Repair legacy BT01 fingerprints after D02 added the adjustment mode.

Revision ID: 0022_ux02
Revises: 0021_sc01r
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_ux02"
down_revision: str | None = "0021_sc01r"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _fingerprint(configuration: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        configuration,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def repair_legacy_configuration(
    configuration: Mapping[str, Any],
    adjustment_mode: str | None,
) -> tuple[dict[str, Any], str] | None:
    """Return the D02-compatible configuration and fingerprint when repair is needed."""

    if "strategy_price_adjustment_mode" in configuration:
        return None
    repaired = dict(configuration)
    repaired["strategy_price_adjustment_mode"] = adjustment_mode or "RAW"
    return repaired, _fingerprint(repaired)


def upgrade() -> None:
    connection = op.get_bind()
    backtest_runs = sa.table(
        "backtest_runs",
        sa.column("id", sa.Uuid()),
        sa.column("request_fingerprint", sa.String(64)),
        sa.column("configuration", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("strategy_price_adjustment_mode", sa.String(8)),
    )
    rows = connection.execute(
        sa.select(
            backtest_runs.c.id,
            backtest_runs.c.configuration,
            backtest_runs.c.strategy_price_adjustment_mode,
        )
    ).mappings()
    for row in rows:
        repaired = repair_legacy_configuration(
            row["configuration"],
            row["strategy_price_adjustment_mode"],
        )
        if repaired is None:
            continue
        configuration, request_fingerprint = repaired
        connection.execute(
            sa.update(backtest_runs)
            .where(backtest_runs.c.id == row["id"])
            .values(
                configuration=configuration,
                request_fingerprint=request_fingerprint,
            )
        )


def downgrade() -> None:
    # This is a checksum/data-compatibility repair. Removing the restored field would
    # knowingly make valid historical records unreadable again, so downgrade is a no-op.
    pass
