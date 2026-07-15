from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_domain.entities import Instrument, Position, Signal
from alphadesk_domain.enums import (
    AccountValuationStatus,
    OrderSide,
    SignalStatus,
    SignalType,
)


def instrument(**overrides: object) -> Instrument:
    values: dict[str, object] = {
        "symbol": "600000",
        "exchange": "SSE",
        "market": "CN_A",
        "name": "Test Instrument",
        "asset_type": "EQUITY",
        "currency": "CNY",
        "lot_size": Decimal("100"),
        "price_tick": Decimal("0.01"),
        "timezone": "Asia/Shanghai",
    }
    values.update(overrides)
    return Instrument(**values)  # type: ignore[arg-type]


def signal(**overrides: object) -> Signal:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "strategy_id": uuid4(),
        "strategy_version_id": uuid4(),
        "account_id": uuid4(),
        "instrument_id": uuid4(),
        "signal_type": SignalType.ENTRY,
        "side": OrderSide.BUY,
        "generated_at": now,
        "valid_until": now + timedelta(minutes=5),
        "status": SignalStatus.CREATED,
        "correlation_id": uuid4(),
    }
    values.update(overrides)
    return Signal(**values)  # type: ignore[arg-type]


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        instrument(created_at=datetime.now())


def test_aware_datetime_is_normalized_to_utc() -> None:
    source = datetime(2026, 7, 15, 17, 30, tzinfo=timezone(timedelta(hours=8)))
    entity = instrument(created_at=source)
    assert entity.created_at.tzinfo is UTC
    assert entity.created_at.hour == 9


def test_float_is_rejected_for_decimal_value() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        instrument(price_tick=0.01)


def test_negative_position_quantity_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Position(
            account_id=uuid4(),
            instrument_id=uuid4(),
            total_quantity=Decimal("-1"),
            available_quantity=Decimal("0"),
            frozen_quantity=Decimal("0"),
            unsettled_quantity=Decimal("0"),
            cost_basis=Decimal("0"),
            average_cost=Decimal("1"),
            market_value=Decimal("0"),
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            last_price=None,
            last_price_at=None,
            valuation_status=AccountValuationStatus.UNAVAILABLE,
            as_of=datetime.now(UTC),
        )


def test_target_weight_above_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        signal(target_weight=Decimal("1.00000001"))


def test_signal_valid_until_must_follow_generated_at() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="later than"):
        signal(generated_at=now, valid_until=now - timedelta(seconds=1))
