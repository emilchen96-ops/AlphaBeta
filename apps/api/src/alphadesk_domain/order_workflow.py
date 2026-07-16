"""Pure-domain order workflow rules for the manual M05 boundary."""

from dataclasses import dataclass

from alphadesk_domain.enums import OrderStatus


class InvalidOrderTransition(ValueError):
    """Raised when a requested order state transition is not declared."""


@dataclass(frozen=True, slots=True)
class OrderTransitionRule:
    from_status: OrderStatus | None
    to_status: OrderStatus


class OrderStateMachine:
    """Declarative state machine with no framework or persistence dependency."""

    terminal_states = frozenset(
        {
            OrderStatus.RISK_REJECTED,
            OrderStatus.EXECUTOR_REJECTED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.FAILED,
        }
    )
    _rules = frozenset(
        {
            OrderTransitionRule(None, OrderStatus.CREATED),
            OrderTransitionRule(OrderStatus.CREATED, OrderStatus.RISK_CHECKING),
            OrderTransitionRule(OrderStatus.CREATED, OrderStatus.WAITING_CONFIRMATION),
            OrderTransitionRule(OrderStatus.CREATED, OrderStatus.CANCELLED),
            OrderTransitionRule(OrderStatus.CREATED, OrderStatus.EXPIRED),
            OrderTransitionRule(OrderStatus.CREATED, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.RISK_CHECKING, OrderStatus.RISK_REJECTED),
            OrderTransitionRule(OrderStatus.RISK_CHECKING, OrderStatus.WAITING_CONFIRMATION),
            OrderTransitionRule(OrderStatus.RISK_CHECKING, OrderStatus.EXPIRED),
            OrderTransitionRule(OrderStatus.RISK_CHECKING, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.WAITING_CONFIRMATION, OrderStatus.QUEUED),
            OrderTransitionRule(OrderStatus.WAITING_CONFIRMATION, OrderStatus.CANCELLED),
            OrderTransitionRule(OrderStatus.WAITING_CONFIRMATION, OrderStatus.EXPIRED),
            OrderTransitionRule(OrderStatus.WAITING_CONFIRMATION, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.QUEUED, OrderStatus.DISPATCHED),
            OrderTransitionRule(OrderStatus.QUEUED, OrderStatus.CANCEL_PENDING),
            OrderTransitionRule(OrderStatus.QUEUED, OrderStatus.EXPIRED),
            OrderTransitionRule(OrderStatus.QUEUED, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.QUEUED, OrderStatus.RECONCILIATION_REQUIRED),
            OrderTransitionRule(OrderStatus.DISPATCHED, OrderStatus.EXECUTOR_ACCEPTED),
            OrderTransitionRule(OrderStatus.DISPATCHED, OrderStatus.EXECUTOR_REJECTED),
            OrderTransitionRule(OrderStatus.DISPATCHED, OrderStatus.EXPIRED),
            OrderTransitionRule(OrderStatus.DISPATCHED, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.DISPATCHED, OrderStatus.RECONCILIATION_REQUIRED),
            OrderTransitionRule(OrderStatus.EXECUTOR_ACCEPTED, OrderStatus.BROKER_SUBMITTED),
            OrderTransitionRule(OrderStatus.EXECUTOR_ACCEPTED, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.EXECUTOR_ACCEPTED, OrderStatus.RECONCILIATION_REQUIRED),
            OrderTransitionRule(OrderStatus.BROKER_SUBMITTED, OrderStatus.BROKER_ACCEPTED),
            OrderTransitionRule(OrderStatus.BROKER_SUBMITTED, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.BROKER_SUBMITTED, OrderStatus.RECONCILIATION_REQUIRED),
            OrderTransitionRule(OrderStatus.BROKER_ACCEPTED, OrderStatus.PARTIALLY_FILLED),
            OrderTransitionRule(OrderStatus.BROKER_ACCEPTED, OrderStatus.FILLED),
            OrderTransitionRule(OrderStatus.BROKER_ACCEPTED, OrderStatus.CANCEL_PENDING),
            OrderTransitionRule(OrderStatus.BROKER_ACCEPTED, OrderStatus.CANCELLED),
            OrderTransitionRule(OrderStatus.BROKER_ACCEPTED, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.BROKER_ACCEPTED, OrderStatus.RECONCILIATION_REQUIRED),
            OrderTransitionRule(OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED),
            OrderTransitionRule(OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCEL_PENDING),
            OrderTransitionRule(OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELLED),
            OrderTransitionRule(OrderStatus.PARTIALLY_FILLED, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.PARTIALLY_FILLED, OrderStatus.RECONCILIATION_REQUIRED),
            OrderTransitionRule(OrderStatus.CANCEL_PENDING, OrderStatus.CANCELLED),
            OrderTransitionRule(OrderStatus.CANCEL_PENDING, OrderStatus.PARTIALLY_FILLED),
            OrderTransitionRule(OrderStatus.CANCEL_PENDING, OrderStatus.FILLED),
            OrderTransitionRule(OrderStatus.CANCEL_PENDING, OrderStatus.FAILED),
            OrderTransitionRule(OrderStatus.CANCEL_PENDING, OrderStatus.RECONCILIATION_REQUIRED),
            *(
                OrderTransitionRule(OrderStatus.RECONCILIATION_REQUIRED, target)
                for target in (
                    OrderStatus.DISPATCHED,
                    OrderStatus.EXECUTOR_ACCEPTED,
                    OrderStatus.BROKER_SUBMITTED,
                    OrderStatus.BROKER_ACCEPTED,
                    OrderStatus.PARTIALLY_FILLED,
                    OrderStatus.FILLED,
                    OrderStatus.CANCELLED,
                    OrderStatus.FAILED,
                )
            ),
        }
    )

    @classmethod
    def can_transition(cls, from_status: OrderStatus | None, to_status: OrderStatus) -> bool:
        return OrderTransitionRule(from_status, to_status) in cls._rules

    @classmethod
    def require_transition(cls, from_status: OrderStatus | None, to_status: OrderStatus) -> None:
        if not cls.can_transition(from_status, to_status):
            raise InvalidOrderTransition(f"illegal order transition: {from_status} -> {to_status}")
