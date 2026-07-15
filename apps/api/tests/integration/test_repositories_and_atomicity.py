from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.infrastructure.models import (
    AuditLogModel,
    DomainEventModel,
    OrderModel,
    OrderStateTransitionModel,
    OutboxMessageModel,
)
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.entities import (
    AuditLog,
    DomainEvent,
    Instrument,
    Order,
    OrderStateTransition,
    OutboxMessage,
    TradingAccount,
)
from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    OrderSide,
    OrderStatus,
    OrderType,
    OutboxStatus,
    TimeInForce,
)


def instrument() -> Instrument:
    suffix = uuid4().hex[:8]
    return Instrument(
        symbol=f"T{suffix}",
        exchange="TEST",
        market="TEST",
        name="Repository instrument",
        asset_type="EQUITY",
        currency="CNY",
        lot_size=Decimal("100.00000000"),
        price_tick=Decimal("0.01000000"),
        timezone="UTC",
    )


def account() -> TradingAccount:
    return TradingAccount(
        account_code=f"SIM-{uuid4().hex[:8]}",
        name="Test account",
        account_type=AccountType.SIMULATED,
        status=AccountStatus.ACTIVE,
        broker_type="SIMULATED",
        base_currency="CNY",
    )


def order(account_id: UUID, instrument_id: UUID, correlation_id: UUID) -> Order:
    return Order(
        account_id=account_id,
        instrument_id=instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        requested_quantity=Decimal("100.00000000"),
        limit_price=Decimal("12.34567890"),
        status=OrderStatus.CREATED,
        idempotency_key=f"order-{uuid4()}",
        broker_type="SIMULATED",
        correlation_id=correlation_id,
    )


async def seed_reference_data(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[Instrument, TradingAccount]:
    instrument_entity = instrument()
    account_entity = account()
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.instruments.add(instrument_entity)
        await uow.accounts.add(account_entity)
        await uow.commit()
    return instrument_entity, account_entity


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_add_query_business_key_and_decimal_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    expected = instrument()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.instruments.add(expected)
        assert await uow.instruments.get_by_id(expected.id) == expected
        by_key = await uow.instruments.get_by_business_key(expected.exchange, expected.symbol)
        assert by_key is not None
        assert by_key.price_tick == Decimal("0.01000000")
        assert by_key.created_at.tzinfo is not None
        await uow.commit()


def atomic_records(
    account_id: UUID, instrument_id: UUID
) -> tuple[Order, OrderStateTransition, DomainEvent, AuditLog, OutboxMessage]:
    correlation_id = uuid4()
    order_entity = order(account_id, instrument_id, correlation_id)
    now = datetime.now(UTC)
    transition = OrderStateTransition(
        order_id=order_entity.id,
        from_status=None,
        to_status=OrderStatus.CREATED,
        actor_type="SYSTEM",
        correlation_id=correlation_id,
        occurred_at=now,
    )
    event = DomainEvent(
        event_id=uuid4(),
        event_type="order.created",
        entity_type="Order",
        entity_id=order_entity.id,
        source="M02_TEST",
        event_time=now,
        received_time=now,
        correlation_id=correlation_id,
        schema_version=1,
        payload={"order_id": str(order_entity.id)},
    )
    audit = AuditLog(
        actor_type="SYSTEM",
        action="ORDER_CREATED",
        resource_type="Order",
        resource_id=order_entity.id,
        outcome="SUCCESS",
        correlation_id=correlation_id,
        occurred_at=now,
    )
    outbox = OutboxMessage(
        event_id=event.event_id,
        aggregate_type="Order",
        aggregate_id=order_entity.id,
        topic="orders.events",
        payload=event.payload,
        headers={"correlation_id": str(correlation_id)},
        status=OutboxStatus.PENDING,
        available_at=now,
    )
    return order_entity, transition, event, audit, outbox


async def persist_atomic_records(
    uow: SqlAlchemyUnitOfWork,
    records: tuple[Order, OrderStateTransition, DomainEvent, AuditLog, OutboxMessage],
) -> None:
    order_entity, transition, event, audit, outbox = records
    await uow.orders.add(order_entity)
    await uow.orders.append_transition(transition)
    await uow.events.append(event)
    await uow.audit_logs.append(audit)
    await uow.outbox.add(outbox)


async def record_counts(
    factory: async_sessionmaker[AsyncSession], order_id: UUID, event_id: UUID
) -> tuple[int, int, int, int, int]:
    async with factory() as session:
        statements = (
            select(func.count()).select_from(OrderModel).where(OrderModel.id == order_id),
            select(func.count())
            .select_from(OrderStateTransitionModel)
            .where(OrderStateTransitionModel.order_id == order_id),
            select(func.count())
            .select_from(DomainEventModel)
            .where(DomainEventModel.event_id == event_id),
            select(func.count())
            .select_from(AuditLogModel)
            .where(AuditLogModel.resource_id == order_id),
            select(func.count())
            .select_from(OutboxMessageModel)
            .where(OutboxMessageModel.event_id == event_id),
        )
        counts: list[int] = []
        for statement in statements:
            counts.append(int(await session.scalar(statement) or 0))
        return counts[0], counts[1], counts[2], counts[3], counts[4]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_event_audit_outbox_transaction_is_atomic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    instrument_entity, account_entity = await seed_reference_data(session_factory)
    success = atomic_records(account_entity.id, instrument_entity.id)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await persist_atomic_records(uow, success)
        await uow.commit()
    assert await record_counts(session_factory, success[0].id, success[2].event_id) == (
        1,
        1,
        1,
        1,
        1,
    )
    order_entity, transition, event, audit, outbox = success
    assert {
        order_entity.correlation_id,
        transition.correlation_id,
        event.correlation_id,
        audit.correlation_id,
    } == {order_entity.correlation_id}
    assert outbox.headers["correlation_id"] == str(order_entity.correlation_id)
    assert order_entity.status is OrderStatus.CREATED
    assert outbox.status is OutboxStatus.PENDING

    failed = atomic_records(account_entity.id, instrument_entity.id)
    with pytest.raises(RuntimeError, match="forced rollback"):
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await persist_atomic_records(uow, failed)
            raise RuntimeError("forced rollback")
    assert await record_counts(session_factory, failed[0].id, failed[2].event_id) == (
        0,
        0,
        0,
        0,
        0,
    )

    recovery = instrument()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.instruments.add(recovery)
        await uow.commit()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        assert await uow.instruments.get_by_id(recovery.id) is not None
