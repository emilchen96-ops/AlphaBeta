from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_api.application.order_contracts import action_fingerprint, order_fingerprint
from alphadesk_domain.entities import OrderAction, OrderStateTransition
from alphadesk_domain.enums import OrderStatus
from alphadesk_domain.order_workflow import InvalidOrderTransition, OrderStateMachine


def test_m05_manual_path_is_declared() -> None:
    assert OrderStateMachine.can_transition(None, OrderStatus.CREATED)
    assert OrderStateMachine.can_transition(OrderStatus.CREATED, OrderStatus.WAITING_CONFIRMATION)
    assert OrderStateMachine.can_transition(OrderStatus.WAITING_CONFIRMATION, OrderStatus.QUEUED)


@pytest.mark.parametrize("status", list(OrderStateMachine.terminal_states))
def test_terminal_state_cannot_continue(status: OrderStatus) -> None:
    assert not OrderStateMachine.can_transition(status, OrderStatus.QUEUED)
    with pytest.raises(InvalidOrderTransition):
        OrderStateMachine.require_transition(status, OrderStatus.QUEUED)


def test_reconciliation_is_not_terminal() -> None:
    assert OrderStateMachine.can_transition(OrderStatus.RECONCILIATION_REQUIRED, OrderStatus.FAILED)


def test_waiting_confirmation_can_be_cancelled() -> None:
    assert OrderStateMachine.can_transition(OrderStatus.WAITING_CONFIRMATION, OrderStatus.CANCELLED)


def test_waiting_confirmation_can_expire() -> None:
    assert OrderStateMachine.can_transition(OrderStatus.WAITING_CONFIRMATION, OrderStatus.EXPIRED)


def test_queued_dispatch_rule_is_declared() -> None:
    assert OrderStateMachine.can_transition(OrderStatus.QUEUED, OrderStatus.DISPATCHED)


def test_same_state_transition_is_rejected() -> None:
    assert not OrderStateMachine.can_transition(OrderStatus.CREATED, OrderStatus.CREATED)


def test_transition_requires_aware_datetime_and_positive_version() -> None:
    with pytest.raises(ValueError):
        OrderStateTransition(
            order_id=uuid4(),
            to_status=OrderStatus.CREATED,
            actor_type="LOCAL_USER",
            correlation_id=uuid4(),
            occurred_at=datetime(2026, 7, 16),
        )
    with pytest.raises(ValueError):
        OrderStateTransition(
            order_id=uuid4(),
            to_status=OrderStatus.CREATED,
            actor_type="LOCAL_USER",
            correlation_id=uuid4(),
            occurred_at=datetime(2026, 7, 16, tzinfo=UTC),
            order_version=0,
        )


def test_transition_normalizes_time_to_utc() -> None:
    transition = OrderStateTransition(
        order_id=uuid4(),
        to_status=OrderStatus.CREATED,
        actor_type="LOCAL_USER",
        correlation_id=uuid4(),
        occurred_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    assert transition.occurred_at.tzinfo is UTC


def test_order_action_validates_versions() -> None:
    with pytest.raises(ValueError):
        OrderAction(
            order_id=uuid4(),
            action_type="CONFIRM",
            idempotency_key="confirm-1",
            request_fingerprint="f" * 64,
            actor_type="LOCAL_USER",
            expected_order_version=2,
            applied_order_version=1,
            correlation_id=uuid4(),
            occurred_at=datetime(2026, 7, 16, tzinfo=UTC),
        )


def test_order_fingerprints_are_stable_and_sensitive_to_business_input() -> None:
    values = dict(
        account_id=uuid4(),
        instrument_id=uuid4(),
        side="BUY",
        order_type="LIMIT",
        time_in_force="DAY",
        quantity=Decimal("100"),
        limit_price=Decimal("12.3400"),
        expires_at=datetime(2026, 7, 16, tzinfo=UTC),
    )
    assert order_fingerprint(**values) == order_fingerprint(**values)
    order_id = uuid4()
    assert action_fingerprint(
        order_id=order_id, action_type="CONFIRM", expected_order_version=2, note="ok"
    ) == action_fingerprint(
        order_id=order_id, action_type="CONFIRM", expected_order_version=2, note="ok"
    )
    assert action_fingerprint(
        order_id=order_id, action_type="CONFIRM", expected_order_version=2, note="changed"
    ) != action_fingerprint(
        order_id=order_id, action_type="CONFIRM", expected_order_version=2, note="ok"
    )
