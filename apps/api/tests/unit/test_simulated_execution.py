from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_domain.broker import BrokerExecutionMode, BrokerExecutionStatus
from alphadesk_domain.enums import OrderStatus
from alphadesk_domain.simulated_execution import BrokerExecutionAttempt

pytestmark = pytest.mark.unit


def _attempt(**changes: object) -> BrokerExecutionAttempt:
    values: dict[str, object] = {
        "idempotency_key": "execution-key",
        "request_fingerprint": "a" * 64,
        "broker_key": "simulated",
        "broker_version": "1.0.0",
        "execution_mode": BrokerExecutionMode.SIMULATED,
        "order_id": uuid4(),
        "command_id": uuid4(),
        "account_id": uuid4(),
        "instrument_id": uuid4(),
        "attempt_number": 2,
        "input_order_status": OrderStatus.PARTIALLY_FILLED,
        "result_status": BrokerExecutionStatus.FILLED,
        "requested_quantity": Decimal("100"),
        "previously_filled_quantity": Decimal("40"),
        "attempted_quantity": Decimal("60"),
        "filled_quantity": Decimal("60"),
        "remaining_quantity": Decimal("0"),
        "average_fill_price": Decimal("10"),
        "message": "filled",
        "market_snapshot": {"source": "test"},
        "account_snapshot": {"cash_available": "1000"},
        "fee_model_version": "fee-v1",
        "slippage_model_version": "slippage-v1",
        "correlation_id": uuid4(),
        "started_at": datetime.now(UTC),
        "completed_at": datetime.now(UTC),
    }
    values.update(changes)
    return BrokerExecutionAttempt(**values)  # type: ignore[arg-type]


def test_execution_attempt_validates_partial_fill_quantity_balance() -> None:
    attempt = _attempt()
    assert attempt.attempt_number == 2
    assert attempt.remaining_quantity == Decimal("0")

    with pytest.raises(ValueError, match="quantities do not balance"):
        _attempt(remaining_quantity=Decimal("1"))


def test_execution_attempt_rejects_missing_average_and_invalid_attempt_number() -> None:
    with pytest.raises(ValueError, match="average_fill_price"):
        _attempt(average_fill_price=None)

    with pytest.raises(ValueError, match="attempt_number"):
        _attempt(attempt_number=0)
