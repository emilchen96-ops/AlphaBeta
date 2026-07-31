"""Persist BT01 execution-price policy and repair legacy fingerprints.

Revision ID: 0028_bt01exec
Revises: 0027_cal01r
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028_bt01exec"
down_revision: str | None = "0027_cal01r"
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
) -> tuple[dict[str, Any], str] | None:
    """Add the explicit legacy limit-price policy to historical runs."""

    if (
        "execution_price_mode" in configuration
        and "maximum_entry_gap_ratio" in configuration
    ):
        return None
    repaired = dict(configuration)
    repaired.setdefault(
        "execution_price_mode",
        (
            "NEXT_OPEN"
            if str(repaired.get("order_type", "LIMIT")) == "MARKET"
            else "SIGNAL_CLOSE_LIMIT"
        ),
    )
    repaired.setdefault("maximum_entry_gap_ratio", None)
    return repaired, _fingerprint(repaired)


def upgrade() -> None:
    connection = op.get_bind()
    backtest_runs = sa.table(
        "backtest_runs",
        sa.column("id", sa.Uuid()),
        sa.column("request_fingerprint", sa.String(64)),
        sa.column("configuration", postgresql.JSONB(astext_type=sa.Text())),
    )
    rows = connection.execute(
        sa.select(backtest_runs.c.id, backtest_runs.c.configuration)
    ).mappings()
    for row in rows:
        repaired = repair_legacy_configuration(row["configuration"])
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
    # Historical fingerprints must remain readable after a downgrade.
    pass
