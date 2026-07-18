"""Shared application-layer errors and audit/event helpers."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from alphadesk_domain.entities import AuditLog, DomainEvent
from alphadesk_domain.unit_of_work import UnitOfWork

UnitOfWorkFactory = Callable[[], UnitOfWork]


class ApplicationError(Exception):
    def __init__(self, code: str, message: str, details: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def correlation_uuid(value: str | UUID | None) -> UUID:
    if isinstance(value, UUID):
        return value
    if value:
        try:
            return UUID(value)
        except ValueError:
            return uuid5(NAMESPACE_URL, f"alphadesk:{value}")
    return uuid4()


async def append_event_and_audit(
    uow: UnitOfWork,
    *,
    event_type: str,
    entity_type: str,
    entity_id: UUID,
    correlation_id: UUID,
    payload: dict[str, object],
    action: str | None = None,
    outcome: str = "SUCCESS",
    details: dict[str, object] | None = None,
    source: str = "ALPHADESK_M03",
    actor_type: str = "LOCAL_USER",
) -> None:
    now = datetime.now(UTC)
    await uow.events.append(
        DomainEvent(
            event_id=uuid4(),
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            source=source,
            event_time=now,
            received_time=now,
            correlation_id=correlation_id,
            schema_version=1,
            payload=payload,
        )
    )
    await uow.audit_logs.append(
        AuditLog(
            actor_type=actor_type,
            action=action or event_type,
            resource_type=entity_type,
            resource_id=entity_id,
            outcome=outcome,
            correlation_id=correlation_id,
            occurred_at=now,
            details=details or {},
        )
    )
