"""Stable, versioned canonical payload helpers for M05 order facts."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("order decimals must be finite Decimal instances")
    return format(value, "f")


def utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("order datetimes must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def payload_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def order_fingerprint(
    *,
    account_id: UUID,
    instrument_id: UUID,
    side: str,
    order_type: str,
    time_in_force: str,
    quantity: Decimal,
    limit_price: Decimal | None,
    expires_at: datetime | None,
) -> str:
    return payload_hash(
        {
            "schema_version": 1,
            "account_id": str(account_id),
            "instrument_id": str(instrument_id),
            "intent_source": "MANUAL",
            "side": side,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "requested_quantity": decimal_text(quantity),
            "limit_price": decimal_text(limit_price),
            "expires_at": utc_text(expires_at),
        }
    )


def action_fingerprint(
    *, order_id: UUID, action_type: str, expected_order_version: int, note: str | None
) -> str:
    return payload_hash(
        {
            "schema_version": 1,
            "order_id": str(order_id),
            "action_type": action_type,
            "expected_order_version": expected_order_version,
            "note": (note or "").strip(),
        }
    )
