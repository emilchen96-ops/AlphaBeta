"""Manual-order application services; no broker or message publisher is involved."""

# ruff: noqa: RUF001

import builtins
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TypedDict
from uuid import UUID, uuid4

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.order_contracts import (
    action_fingerprint,
    cancel_fingerprint,
    decimal_text,
    order_fingerprint,
    payload_hash,
    utc_text,
)
from alphadesk_domain.entities import (
    AuditLog,
    DomainEvent,
    Order,
    OrderAction,
    OrderCommand,
    OrderStateTransition,
    OutboxMessage,
)
from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    CommandStatus,
    CommandType,
    OrderActionType,
    OrderActorType,
    OrderIntentSource,
    OrderSide,
    OrderStatus,
    OrderType,
    OutboxStatus,
    TimeInForce,
)
from alphadesk_domain.order_workflow import OrderStateMachine
from alphadesk_domain.unit_of_work import UnitOfWork
from alphadesk_domain.values import as_utc, decimal_value, utc_now


def _aware_time(value: datetime, field_name: str) -> datetime:
    try:
        return as_utc(value, field_name)
    except ValueError as exc:
        raise ApplicationError("ORDER_INVALID_DATETIME", str(exc)) from exc


def _validate_decimal(value: object, field_name: str, code: str) -> Decimal:
    try:
        return decimal_value(value, field_name)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ApplicationError(code, f"{field_name} must be a finite Decimal") from exc


def _validate_text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ApplicationError(
            "ORDER_INVALID_REQUEST", f"{field_name} must contain 1 to {maximum} characters"
        )
    return normalized


def _validate_optional_text(value: str | None, field_name: str, maximum: int) -> None:
    if value is not None and len(value.strip()) > maximum:
        raise ApplicationError(
            "ORDER_INVALID_REQUEST", f"{field_name} must contain at most {maximum} characters"
        )


@dataclass(frozen=True, slots=True)
class CreateOrderRequest:
    account_id: UUID
    instrument_id: UUID
    side: str
    order_type: str
    time_in_force: str
    quantity: Decimal
    limit_price: Decimal | None
    expires_at: datetime | None
    idempotency_key: str
    correlation_id: UUID
    note: str | None = None
    actor_id: str | None = None
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConfirmOrderRequest:
    order_id: UUID
    idempotency_key: str
    expected_order_version: int
    correlation_id: UUID
    note: str | None = None
    actor_type: str = OrderActorType.LOCAL_USER
    actor_id: str | None = None
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CancelOrderRequest:
    order_id: UUID
    idempotency_key: str
    expected_order_version: int
    correlation_id: UUID
    reason: str | None = None
    actor_type: str = OrderActorType.LOCAL_USER
    actor_id: str | None = None
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ExpirationResult:
    expired_order_ids: tuple[UUID, ...]
    skipped_order_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    order_id: UUID
    code: str
    message: str


class OrderPageResult(TypedDict):
    items: builtins.list[dict[str, object]]
    page: int
    page_size: int
    total: int


def _event(
    *,
    event_type: str,
    order: Order,
    correlation_id: UUID,
    occurred_at: datetime,
    payload: dict[str, object],
) -> DomainEvent:
    return DomainEvent(
        event_id=uuid4(),
        event_type=event_type,
        entity_type="ORDER",
        entity_id=order.id,
        source="ALPHADESK_M05",
        event_time=occurred_at,
        received_time=occurred_at,
        correlation_id=correlation_id,
        schema_version=1,
        payload=payload,
    )


async def _audit(
    uow: UnitOfWork,
    *,
    action: str,
    order: Order,
    correlation_id: UUID,
    occurred_at: datetime,
    actor_id: str | None,
    actor_type: str = OrderActorType.LOCAL_USER,
    details: dict[str, object],
) -> None:
    await uow.audit_logs.append(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type="ORDER",
            resource_id=order.id,
            outcome="SUCCESS",
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            details=details,
        )
    )


class OrderIntentService:
    """Validate and atomically persist a manual order awaiting confirmation."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._failure_injector = failure_injector or (lambda _stage: None)

    async def create(self, request: CreateOrderRequest) -> Order:
        async with self._uow_factory() as uow:
            order = await self.create_in_transaction(uow, request)
            await uow.commit()
            return order

    async def create_in_transaction(
        self, uow: UnitOfWork, request: CreateOrderRequest, *, order_id: UUID | None = None
    ) -> Order:
        """Create M05 initial facts in a caller-owned transaction."""

        occurred_at = _aware_time(request.occurred_at or utc_now(), "occurred_at")
        _validate_text(request.idempotency_key, "idempotency_key", 128)
        _validate_optional_text(request.note, "note", 1024)
        _validate_decimal(request.quantity, "quantity", "ORDER_INVALID_QUANTITY")
        if request.limit_price is not None:
            _validate_decimal(request.limit_price, "limit_price", "ORDER_INVALID_LIMIT_PRICE")
        fingerprint = order_fingerprint(
            account_id=request.account_id,
            instrument_id=request.instrument_id,
            side=request.side,
            order_type=request.order_type,
            time_in_force=request.time_in_force,
            quantity=request.quantity,
            limit_price=request.limit_price,
            expires_at=request.expires_at,
        )
        existing = await uow.orders.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if existing.request_fingerprint == fingerprint:
                return existing
            raise ApplicationError(
                "ORDER_IDEMPOTENCY_CONFLICT", "idempotency key has different input"
            )
        account = await uow.accounts.get_by_id(request.account_id)
        if account is None:
            raise ApplicationError("ORDER_ACCOUNT_NOT_FOUND", "trading account was not found")
        if account.account_type is not AccountType.SIMULATED:
            raise ApplicationError(
                "ORDER_ACCOUNT_TYPE_NOT_SUPPORTED", "only simulated accounts are supported"
            )
        if account.status is not AccountStatus.ACTIVE:
            raise ApplicationError("ORDER_ACCOUNT_NOT_ACTIVE", "account is not active")
        instrument = await uow.instruments.get_by_id(request.instrument_id)
        if instrument is None or not instrument.is_active:
            raise ApplicationError("ORDER_INSTRUMENT_NOT_ACTIVE", "instrument is not active")
        self._validate_request(request, instrument.lot_size, instrument.price_tick, occurred_at)
        order = Order(
            account_id=request.account_id,
            instrument_id=request.instrument_id,
            side=OrderSide(request.side),
            order_type=OrderType(request.order_type),
            time_in_force=TimeInForce(request.time_in_force),
            requested_quantity=request.quantity,
            limit_price=request.limit_price,
            expires_at=request.expires_at,
            status=OrderStatus.CREATED,
            idempotency_key=request.idempotency_key,
            broker_type="LOCAL_PENDING",
            correlation_id=request.correlation_id,
            intent_source=OrderIntentSource.MANUAL,
            request_fingerprint=fingerprint,
            row_version=1,
            confirmation_required=True,
            created_by_actor_type=OrderActorType.LOCAL_USER,
            created_by_actor_id=request.actor_id,
            created_at=occurred_at,
            updated_at=occurred_at,
            id=order_id or uuid4(),
        )
        await uow.orders.add(order)
        self._failure_injector("after_order_insert")
        await uow.order_state_transitions.append(
            OrderStateTransition(
                order_id=order.id,
                from_status=None,
                to_status=OrderStatus.CREATED,
                actor_type=OrderActorType.LOCAL_USER,
                actor_id=request.actor_id,
                correlation_id=request.correlation_id,
                occurred_at=occurred_at,
                order_version=1,
            )
        )
        self._failure_injector("after_created_transition")
        OrderStateMachine.require_transition(OrderStatus.CREATED, OrderStatus.WAITING_CONFIRMATION)
        order.status = OrderStatus.WAITING_CONFIRMATION
        order.row_version = 2
        order.updated_at = occurred_at
        await uow.orders.update_projection(order)
        await uow.order_state_transitions.append(
            OrderStateTransition(
                order_id=order.id,
                from_status=OrderStatus.CREATED,
                to_status=OrderStatus.WAITING_CONFIRMATION,
                actor_type=OrderActorType.SYSTEM,
                correlation_id=request.correlation_id,
                occurred_at=occurred_at,
                order_version=2,
            )
        )
        self._failure_injector("after_waiting_transition")
        for event_type in ("ORDER_CREATED", "ORDER_WAITING_CONFIRMATION"):
            await uow.events.append(
                _event(
                    event_type=event_type,
                    order=order,
                    correlation_id=request.correlation_id,
                    occurred_at=occurred_at,
                    payload={"order_id": str(order.id), "row_version": order.row_version},
                )
            )
        self._failure_injector("after_order_events")
        await _audit(
            uow,
            action="ORDER_CREATED",
            order=order,
            correlation_id=request.correlation_id,
            occurred_at=occurred_at,
            actor_id=request.actor_id,
            details={
                "warnings": [
                    "no executor dispatch occurs",
                    "no real trade occurs",
                ]
            },
        )
        self._failure_injector("after_order_audit")
        return order

    @staticmethod
    def _validate_request(
        request: CreateOrderRequest, lot_size: Decimal, price_tick: Decimal, now: datetime
    ) -> None:
        if request.quantity <= 0 or request.quantity % lot_size != 0:
            if request.quantity <= 0:
                raise ApplicationError("ORDER_INVALID_QUANTITY", "quantity must be positive")
            raise ApplicationError("ORDER_LOT_SIZE_VIOLATION", "quantity must be a lot multiple")
        if request.order_type == OrderType.LIMIT and request.limit_price is None:
            raise ApplicationError("ORDER_LIMIT_PRICE_REQUIRED", "limit order requires limit_price")
        if request.order_type == OrderType.MARKET and request.limit_price is not None:
            raise ApplicationError(
                "ORDER_LIMIT_PRICE_NOT_ALLOWED", "market order cannot include limit_price"
            )
        if request.limit_price is not None and request.limit_price % price_tick != 0:
            raise ApplicationError(
                "ORDER_PRICE_TICK_VIOLATION", "limit price must align to the price tick"
            )
        if request.expires_at is not None and _aware_time(request.expires_at, "expires_at") <= now:
            raise ApplicationError("ORDER_EXPIRED", "expiry must be in the future")


class OrderConfirmationService:
    """Confirm a waiting order and atomically stage a command in PostgreSQL Outbox."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._failure_injector = failure_injector or (lambda _stage: None)

    async def confirm(self, request: ConfirmOrderRequest) -> Order:
        occurred_at = _aware_time(request.occurred_at or utc_now(), "occurred_at")
        _validate_text(request.idempotency_key, "idempotency_key", 128)
        _validate_optional_text(request.note, "note", 1024)
        fingerprint = action_fingerprint(
            order_id=request.order_id,
            action_type="CONFIRM",
            expected_order_version=request.expected_order_version,
            note=request.note,
        )
        async with self._uow_factory() as uow:
            action = await uow.order_actions.get_by_idempotency_key(request.idempotency_key)
            if action is not None:
                if action.request_fingerprint == fingerprint:
                    order = await uow.orders.get_by_id(request.order_id)
                    if order is None:
                        raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
                    return order
                raise ApplicationError(
                    "ORDER_ACTION_IDEMPOTENCY_CONFLICT", "idempotency key has different input"
                )
            order = await uow.orders.get_for_update(request.order_id)
            if order is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
            action = await uow.order_actions.get_by_idempotency_key(request.idempotency_key)
            if action is not None:
                if action.request_fingerprint == fingerprint:
                    return order
                raise ApplicationError(
                    "ORDER_ACTION_IDEMPOTENCY_CONFLICT", "idempotency key has different input"
                )
            if order.row_version != request.expected_order_version:
                raise ApplicationError("ORDER_VERSION_CONFLICT", "order version does not match")
            if order.status is not OrderStatus.WAITING_CONFIRMATION:
                if order.status is OrderStatus.QUEUED:
                    raise ApplicationError("ORDER_ALREADY_CONFIRMED", "order is already confirmed")
                if order.status is OrderStatus.CANCELLED:
                    raise ApplicationError("ORDER_ALREADY_CANCELLED", "order is cancelled")
                raise ApplicationError(
                    "ORDER_NOT_CONFIRMABLE", "order is not awaiting confirmation"
                )
            if order.expires_at is not None and order.expires_at <= occurred_at:
                raise ApplicationError("ORDER_EXPIRED", "order is expired")
            account = await uow.accounts.get_by_id(order.account_id)
            instrument = await uow.instruments.get_by_id(order.instrument_id)
            if account is None or account.account_type is not AccountType.SIMULATED:
                raise ApplicationError(
                    "ORDER_ACCOUNT_TYPE_NOT_SUPPORTED", "account type is not supported"
                )
            if account.status is not AccountStatus.ACTIVE:
                raise ApplicationError("ORDER_ACCOUNT_NOT_ACTIVE", "account is not active")
            if instrument is None or not instrument.is_active:
                raise ApplicationError(
                    "ORDER_INSTRUMENT_NOT_ACTIVE", "instrument is no longer active"
                )
            if await uow.order_commands.get_submit_command_by_order(order.id) is not None:
                raise ApplicationError(
                    "ORDER_COMMAND_ALREADY_EXISTS", "submit command already exists"
                )
            action = OrderAction(
                order_id=order.id,
                action_type=OrderActionType.CONFIRM,
                idempotency_key=request.idempotency_key,
                request_fingerprint=fingerprint,
                actor_type=request.actor_type,
                actor_id=request.actor_id,
                expected_order_version=order.row_version,
                applied_order_version=order.row_version + 1,
                correlation_id=request.correlation_id,
                note=request.note,
                occurred_at=occurred_at,
            )
            await uow.order_actions.append(action)
            self._failure_injector("after_action")
            OrderStateMachine.require_transition(order.status, OrderStatus.QUEUED)
            order.status = OrderStatus.QUEUED
            order.row_version += 1
            order.confirmed_at = occurred_at
            order.updated_at = occurred_at
            await uow.orders.update_projection(order)
            await uow.order_state_transitions.append(
                OrderStateTransition(
                    order_id=order.id,
                    from_status=OrderStatus.WAITING_CONFIRMATION,
                    to_status=OrderStatus.QUEUED,
                    actor_type=request.actor_type,
                    actor_id=request.actor_id,
                    action_id=action.id,
                    correlation_id=request.correlation_id,
                    occurred_at=occurred_at,
                    order_version=order.row_version,
                )
            )
            self._failure_injector("after_transition")
            command_id = uuid4()
            payload = {
                "schema_version": 1,
                "command_id": str(command_id),
                "command_type": "SUBMIT_ORDER",
                "order_id": str(order.id),
                "account_id": str(order.account_id),
                "instrument_id": str(order.instrument_id),
                "symbol": instrument.symbol,
                "exchange": instrument.exchange,
                "side": order.side.value,
                "order_type": order.order_type.value,
                "time_in_force": order.time_in_force.value,
                "quantity": decimal_text(order.requested_quantity),
                "limit_price": decimal_text(order.limit_price),
                "created_at": utc_text(occurred_at),
                "expires_at": utc_text(order.expires_at),
                "correlation_id": str(request.correlation_id),
            }
            command = OrderCommand(
                command_id=command_id,
                order_id=order.id,
                command_type=CommandType.SUBMIT_ORDER,
                status=CommandStatus.PENDING,
                sequence_number=1,
                payload=payload,
                payload_hash=payload_hash(payload),
                expires_at=order.expires_at or occurred_at + timedelta(days=1),
                created_at=occurred_at,
                updated_at=occurred_at,
            )
            await uow.order_commands.add(command)
            self._failure_injector("after_command")
            confirmed = _event(
                event_type="ORDER_CONFIRMED",
                order=order,
                correlation_id=request.correlation_id,
                occurred_at=occurred_at,
                payload={
                    "order_id": str(order.id),
                    "action_id": str(action.id),
                    "row_version": order.row_version,
                },
            )
            command_event = _event(
                event_type="ORDER_COMMAND_CREATED",
                order=order,
                correlation_id=request.correlation_id,
                occurred_at=occurred_at,
                payload={
                    "order_id": str(order.id),
                    "command_id": str(command_id),
                    "payload_hash": command.payload_hash,
                },
            )
            await uow.events.append(confirmed)
            await uow.events.append(command_event)
            self._failure_injector("after_events")
            await _audit(
                uow,
                action="ORDER_CONFIRMED",
                order=order,
                correlation_id=request.correlation_id,
                occurred_at=occurred_at,
                actor_id=request.actor_id,
                actor_type=request.actor_type,
                details={"action_id": str(action.id), "command_id": str(command_id)},
            )
            self._failure_injector("after_audit")
            self._failure_injector("before_outbox")
            await uow.outbox.add(
                OutboxMessage(
                    event_id=command_event.event_id,
                    aggregate_type="ORDER",
                    aggregate_id=order.id,
                    topic="order.commands.submit.v1",
                    payload=payload,
                    status=OutboxStatus.PENDING,
                    available_at=occurred_at,
                    created_at=occurred_at,
                    updated_at=occurred_at,
                )
            )
            self._failure_injector("before_commit")
            await uow.commit()
            return order


class OrderCancellationService:
    """Cancel only pre-queue orders while preserving append-only facts."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def cancel(self, request: CancelOrderRequest) -> Order:
        occurred_at = _aware_time(request.occurred_at or utc_now(), "occurred_at")
        _validate_text(request.idempotency_key, "idempotency_key", 128)
        _validate_optional_text(request.reason, "reason", 1024)
        fingerprint = cancel_fingerprint(
            order_id=request.order_id,
            expected_order_version=request.expected_order_version,
            reason=request.reason,
        )
        async with self._uow_factory() as uow:
            existing = await uow.order_actions.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                return await self._idempotent_result(uow, request, fingerprint, existing)
            order = await uow.orders.get_for_update(request.order_id)
            if order is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
            existing = await uow.order_actions.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                return await self._idempotent_result(uow, request, fingerprint, existing)
            if order.row_version != request.expected_order_version:
                raise ApplicationError("ORDER_VERSION_CONFLICT", "order version does not match")
            if order.status is OrderStatus.QUEUED:
                raise ApplicationError("ORDER_ALREADY_QUEUED", "queued orders cannot be cancelled")
            if order.status is OrderStatus.CANCELLED:
                raise ApplicationError("ORDER_ALREADY_CANCELLED", "order is already cancelled")
            if order.status not in (OrderStatus.CREATED, OrderStatus.WAITING_CONFIRMATION):
                raise ApplicationError("ORDER_NOT_CANCELLABLE", "order cannot be cancelled")
            previous_status = order.status
            action = OrderAction(
                order_id=order.id,
                action_type=OrderActionType.CANCEL,
                idempotency_key=request.idempotency_key,
                request_fingerprint=fingerprint,
                actor_type=request.actor_type,
                actor_id=request.actor_id,
                expected_order_version=order.row_version,
                applied_order_version=order.row_version + 1,
                correlation_id=request.correlation_id,
                note=request.reason,
                occurred_at=occurred_at,
            )
            await uow.order_actions.append(action)
            OrderStateMachine.require_transition(previous_status, OrderStatus.CANCELLED)
            order.status = OrderStatus.CANCELLED
            order.row_version += 1
            order.cancelled_at = occurred_at
            order.updated_at = occurred_at
            await uow.orders.update_projection(order)
            await uow.order_state_transitions.append(
                OrderStateTransition(
                    order_id=order.id,
                    from_status=previous_status,
                    to_status=OrderStatus.CANCELLED,
                    actor_type=request.actor_type,
                    actor_id=request.actor_id,
                    reason=request.reason,
                    order_version=order.row_version,
                    action_id=action.id,
                    correlation_id=request.correlation_id,
                    occurred_at=occurred_at,
                )
            )
            await uow.events.append(
                _event(
                    event_type="ORDER_CANCELLED",
                    order=order,
                    correlation_id=request.correlation_id,
                    occurred_at=occurred_at,
                    payload={
                        "order_id": str(order.id),
                        "action_id": str(action.id),
                        "row_version": order.row_version,
                    },
                )
            )
            await _audit(
                uow,
                action="ORDER_CANCELLED",
                order=order,
                correlation_id=request.correlation_id,
                occurred_at=occurred_at,
                actor_id=request.actor_id,
                actor_type=request.actor_type,
                details={"action_id": str(action.id), "reason": (request.reason or "").strip()},
            )
            await uow.commit()
            return order

    @staticmethod
    async def _idempotent_result(
        uow: UnitOfWork,
        request: CancelOrderRequest,
        fingerprint: str,
        existing: OrderAction,
    ) -> Order:
        if existing.request_fingerprint != fingerprint:
            raise ApplicationError(
                "ORDER_ACTION_IDEMPOTENCY_CONFLICT", "idempotency key has different input"
            )
        order = await uow.orders.get_by_id(request.order_id)
        if order is None:
            raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
        return order


class OrderExpirationService:
    """Manually expire due pre-queue orders; no scheduler is started in M05."""

    def __init__(self, uow_factory: UnitOfWorkFactory, batch_limit: int = 100) -> None:
        self._uow_factory = uow_factory
        self._batch_limit = max(1, min(batch_limit, 500))

    async def expire_pending(
        self, *, now: datetime | None = None, correlation_id: UUID | None = None
    ) -> ExpirationResult:
        occurred_at = _aware_time(now or utc_now(), "now")
        correlation = correlation_id or uuid4()
        async with self._uow_factory() as uow:
            candidates = await uow.orders.list_expirable(occurred_at, self._batch_limit)
        expired: list[UUID] = []
        skipped: list[UUID] = []
        for candidate in candidates:
            async with self._uow_factory() as uow:
                order = await uow.orders.get_for_update(candidate.id)
                if (
                    order is None
                    or order.status not in (OrderStatus.CREATED, OrderStatus.WAITING_CONFIRMATION)
                    or order.expires_at is None
                    or order.expires_at > occurred_at
                ):
                    skipped.append(candidate.id)
                    continue
                previous_status = order.status
                OrderStateMachine.require_transition(previous_status, OrderStatus.EXPIRED)
                order.status = OrderStatus.EXPIRED
                order.row_version += 1
                order.expired_at = occurred_at
                order.updated_at = occurred_at
                await uow.orders.update_projection(order)
                await uow.order_state_transitions.append(
                    OrderStateTransition(
                        order_id=order.id,
                        from_status=previous_status,
                        to_status=OrderStatus.EXPIRED,
                        actor_type=OrderActorType.SYSTEM,
                        reason_code="ORDER_EXPIRED",
                        order_version=order.row_version,
                        correlation_id=correlation,
                        occurred_at=occurred_at,
                    )
                )
                await uow.events.append(
                    _event(
                        event_type="ORDER_EXPIRED",
                        order=order,
                        correlation_id=correlation,
                        occurred_at=occurred_at,
                        payload={"order_id": str(order.id), "row_version": order.row_version},
                    )
                )
                await _audit(
                    uow,
                    action="ORDER_EXPIRED",
                    order=order,
                    correlation_id=correlation,
                    occurred_at=occurred_at,
                    actor_id=None,
                    actor_type=OrderActorType.SYSTEM,
                    details={"expires_at": utc_text(order.expires_at)},
                )
                await uow.commit()
                expired.append(order.id)
        return ExpirationResult(tuple(expired), tuple(skipped))


ORDER_WARNINGS = (
    "当前实时行情尚未接入",
    "当前仅完成结构校验，尚未完成资金与组合风控",
    "确认后只创建本地数据库指令事实，尚未发送执行器",
    "不会发送券商，也不会产生成交",
)


def _command_summary(command: OrderCommand) -> dict[str, object]:
    return {
        "command_id": str(command.command_id),
        "command_type": command.command_type.value,
        "status": command.status.value,
        "sequence_number": command.sequence_number,
        "payload_hash": command.payload_hash,
        "created_at": command.created_at,
    }


def _outbox_summary(message: OutboxMessage) -> dict[str, object]:
    return {
        "id": str(message.id),
        "event_id": str(message.event_id),
        "topic": message.topic,
        "status": message.status.value,
        "attempts": message.attempts,
        "available_at": message.available_at,
        "published_at": message.published_at,
    }


def _order_capabilities(order: Order) -> dict[str, bool]:
    return {
        "can_confirm": order.status is OrderStatus.WAITING_CONFIRMATION,
        "can_cancel": order.status in (OrderStatus.CREATED, OrderStatus.WAITING_CONFIRMATION),
        "is_sent": False,
        "can_create_fill": False,
    }


class OrderQueryService:
    """Return safe DTO dictionaries rather than ORM rows or internal metadata."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list(
        self,
        *,
        account_id: UUID | None = None,
        instrument_id: UUID | None = None,
        status: str | None = None,
        side: str | None = None,
        order_type: str | None = None,
        intent_source: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> OrderPageResult:
        size = max(1, min(page_size, 100))
        number = max(1, page)
        if created_from is not None:
            created_from = _aware_time(created_from, "created_from")
        if created_to is not None:
            created_to = _aware_time(created_to, "created_to")
        async with self._uow_factory() as uow:
            orders, total = await uow.orders.list(
                offset=(number - 1) * size,
                limit=size,
                account_id=account_id,
                instrument_id=instrument_id,
                status=status,
                side=side,
                order_type=order_type,
                intent_source=intent_source,
                created_from=created_from,
                created_to=created_to,
            )
            items = [await self._summary(uow, order) for order in orders]
        return {"items": items, "page": number, "page_size": size, "total": total}

    async def detail(self, order_id: UUID) -> dict[str, object]:
        async with self._uow_factory() as uow:
            order = await uow.orders.get_by_id(order_id)
            if order is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
            result = await self._summary(uow, order)
            actions = await uow.order_actions.list_by_order(order_id)
            result["actions"] = [
                {
                    "id": str(action.id),
                    "action_type": str(action.action_type),
                    "actor_type": str(action.actor_type),
                    "actor_id": action.actor_id,
                    "expected_order_version": action.expected_order_version,
                    "applied_order_version": action.applied_order_version,
                    "note": action.note,
                    "occurred_at": action.occurred_at,
                    "correlation_id": str(action.correlation_id),
                }
                for action in actions
            ]
            return result

    async def timeline(self, order_id: UUID) -> builtins.list[dict[str, object]]:
        async with self._uow_factory() as uow:
            if await uow.orders.get_by_id(order_id) is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
            transitions = await uow.order_state_transitions.list_by_order(order_id)
            actions = await uow.order_actions.list_by_order(order_id)
            events = await uow.events.list_by_entity("ORDER", order_id)
        items: builtins.list[dict[str, object]] = []
        items.extend(
            {
                "kind": "TRANSITION",
                "label": f"{transition.from_status or 'START'} → {transition.to_status}",
                "actor_type": transition.actor_type,
                "actor_id": transition.actor_id,
                "reason": transition.reason,
                "order_version": transition.order_version,
                "occurred_at": transition.occurred_at,
                "correlation_id": str(transition.correlation_id),
            }
            for transition in transitions
        )
        items.extend(
            {
                "kind": "ACTION",
                "label": str(action.action_type),
                "actor_type": action.actor_type,
                "actor_id": action.actor_id,
                "reason": action.note,
                "order_version": action.applied_order_version,
                "occurred_at": action.occurred_at,
                "correlation_id": str(action.correlation_id),
            }
            for action in actions
        )
        items.extend(
            {
                "kind": "EVENT",
                "label": event.event_type,
                "actor_type": event.source,
                "actor_id": None,
                "reason": None,
                "order_version": event.payload.get("row_version"),
                "occurred_at": event.event_time,
                "correlation_id": str(event.correlation_id),
            }
            for event in events
        )
        return sorted(items, key=lambda item: (str(item["occurred_at"]), str(item["kind"])))

    @staticmethod
    async def _summary(uow: UnitOfWork, order: Order) -> dict[str, object]:
        account = await uow.accounts.get_by_id(order.account_id)
        instrument = await uow.instruments.get_by_id(order.instrument_id)
        commands = await uow.order_commands.list_by_order(order.id)
        outbox = await uow.outbox.list_by_aggregate("ORDER", order.id)
        estimated_notional = (
            (order.requested_quantity * order.limit_price).quantize(Decimal("0.01"))
            if order.order_type is OrderType.LIMIT and order.limit_price is not None
            else None
        )
        return {
            "id": str(order.id),
            "account_id": str(order.account_id),
            "account_name": None if account is None else account.name,
            "instrument_id": str(order.instrument_id),
            "symbol": None if instrument is None else instrument.symbol,
            "exchange": None if instrument is None else instrument.exchange,
            "instrument_name": None if instrument is None else instrument.name,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "time_in_force": order.time_in_force.value,
            "requested_quantity": decimal_text(order.requested_quantity),
            "limit_price": decimal_text(order.limit_price),
            "estimated_notional": decimal_text(estimated_notional),
            "status": order.status.value,
            "intent_source": str(order.intent_source),
            "row_version": order.row_version,
            "confirmation_required": order.confirmation_required,
            "correlation_id": str(order.correlation_id),
            "expires_at": order.expires_at,
            "confirmed_at": order.confirmed_at,
            "cancelled_at": order.cancelled_at,
            "expired_at": order.expired_at,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "capabilities": _order_capabilities(order),
            "warnings": list(ORDER_WARNINGS),
            "commands": [_command_summary(command) for command in commands],
            "outbox": [_outbox_summary(message) for message in outbox],
        }


class OrderIntegrityService:
    """Report M05 fact mismatches without modifying any record."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def verify(self) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        offset = 0
        while True:
            async with self._uow_factory() as uow:
                orders, total = await uow.orders.list(offset=offset, limit=100)
                for order in orders:
                    # Legacy/synthetic fills predate M05 and deliberately have no
                    # manual-confirmation transition chain.
                    if not order.confirmation_required or order.status not in {
                        OrderStatus.CREATED,
                        OrderStatus.WAITING_CONFIRMATION,
                        OrderStatus.QUEUED,
                        OrderStatus.CANCELLED,
                        OrderStatus.EXPIRED,
                    }:
                        continue
                    issues.extend(await self._verify_order(uow, order))
            offset += len(orders)
            if offset >= total or not orders:
                break
        return issues

    @staticmethod
    async def _verify_order(uow: UnitOfWork, order: Order) -> list[IntegrityIssue]:
        issues: list[IntegrityIssue] = []
        latest = await uow.order_state_transitions.get_latest_by_order(order.id)
        commands = await uow.order_commands.list_by_order(order.id)
        submit_commands = [
            item for item in commands if item.command_type is CommandType.SUBMIT_ORDER
        ]
        outbox = await uow.outbox.list_by_aggregate("ORDER", order.id)
        if latest is None or latest.to_status is not order.status:
            issues.append(
                IntegrityIssue(order.id, "ORDER_STATE_MISMATCH", "latest transition differs")
            )
        if latest is None or latest.order_version != order.row_version:
            issues.append(
                IntegrityIssue(order.id, "ORDER_VERSION_MISMATCH", "latest version differs")
            )
        if (
            order.status
            in (
                OrderStatus.WAITING_CONFIRMATION,
                OrderStatus.CANCELLED,
                OrderStatus.EXPIRED,
            )
            and submit_commands
        ):
            issues.append(
                IntegrityIssue(
                    order.id, "UNEXPECTED_SUBMIT_COMMAND", "pre-queue/terminal order has command"
                )
            )
        if order.status is OrderStatus.QUEUED and len(submit_commands) != 1:
            issues.append(
                IntegrityIssue(
                    order.id, "SUBMIT_COMMAND_COUNT", "queued order must have one command"
                )
            )
        if order.status is OrderStatus.QUEUED and len(outbox) != 1:
            issues.append(
                IntegrityIssue(order.id, "OUTBOX_COUNT", "queued order must have one outbox")
            )
        for command in submit_commands:
            if payload_hash(command.payload) != command.payload_hash:
                issues.append(
                    IntegrityIssue(order.id, "COMMAND_HASH_MISMATCH", "payload hash differs")
                )
        if submit_commands and outbox and submit_commands[0].payload != outbox[0].payload:
            issues.append(
                IntegrityIssue(order.id, "OUTBOX_PAYLOAD_MISMATCH", "command and outbox differ")
            )
        if order.status is OrderStatus.QUEUED and any(
            message.status is not OutboxStatus.PENDING for message in outbox
        ):
            issues.append(
                IntegrityIssue(order.id, "OUTBOX_NOT_PENDING", "M05 outbox must remain pending")
            )
        return issues
