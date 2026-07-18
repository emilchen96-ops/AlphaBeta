import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.orders import (
    CancelOrderRequest,
    ConfirmOrderRequest,
    CreateOrderRequest,
    OrderCancellationService,
    OrderConfirmationService,
    OrderExpirationService,
    OrderIntegrityService,
    OrderIntentService,
    OrderQueryService,
)
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.accounting import CashBalance
from alphadesk_domain.entities import Instrument, TradingAccount
from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    OrderStatus,
    SettlementPolicy,
)
from tests.helpers import require_test_database_url

pytestmark = [pytest.mark.integration, pytest.mark.m05]


def _factory(session_factory: async_sessionmaker[AsyncSession]):
    return lambda: SqlAlchemyUnitOfWork(session_factory)


async def _seed(session_factory: async_sessionmaker[AsyncSession], *, with_cash: bool = False):
    factory = _factory(session_factory)
    async with factory() as uow:
        account = TradingAccount(
            account_code=f"M05-{uuid4().hex[:10]}",
            name="M05 Demo",
            account_type=AccountType.SIMULATED,
            status=AccountStatus.ACTIVE,
            broker_type="SIMULATED",
            base_currency="CNY",
            settlement_policy=SettlementPolicy.IMMEDIATE,
        )
        instrument = Instrument(
            symbol=uuid4().hex[:6].upper(),
            exchange="SZSE",
            market="CN",
            name="M05 Instrument",
            asset_type="EQUITY",
            currency="CNY",
            lot_size=Decimal("100"),
            price_tick=Decimal("0.01"),
            timezone="Asia/Shanghai",
        )
        await uow.accounts.add(account)
        await uow.instruments.add(instrument)
        if with_cash:
            await uow.cash_balances.add(
                CashBalance(
                    account_id=account.id,
                    currency="CNY",
                    total_cash=Decimal("1000000"),
                    available_cash=Decimal("1000000"),
                    frozen_cash=Decimal("0"),
                    as_of=datetime.now(UTC),
                )
            )
        await uow.commit()
    return account, instrument


def _create_request(account, instrument, *, key: str | None = None, expires_at=None):
    now = datetime.now(UTC)
    return CreateOrderRequest(
        account_id=account.id,
        instrument_id=instrument.id,
        side="BUY",
        order_type="LIMIT",
        time_in_force="DAY",
        quantity=Decimal("1000"),
        limit_price=Decimal("12.34"),
        expires_at=expires_at,
        idempotency_key=key or f"create-{uuid4()}",
        note="manual test",
        correlation_id=uuid4(),
        occurred_at=now,
    )


@pytest.mark.asyncio
async def test_create_confirm_outbox_query_and_integrity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    create_service = OrderIntentService(factory)
    request = _create_request(account, instrument)
    order = await create_service.create(request)
    duplicate = await create_service.create(request)
    assert duplicate.id == order.id
    assert order.status is OrderStatus.WAITING_CONFIRMATION
    assert order.row_version == 2

    confirmed = await OrderConfirmationService(factory).confirm(
        ConfirmOrderRequest(
            order_id=order.id,
            idempotency_key=f"confirm-{order.id}",
            expected_order_version=2,
            correlation_id=uuid4(),
            occurred_at=datetime.now(UTC),
        )
    )
    assert confirmed.status is OrderStatus.QUEUED
    assert confirmed.row_version == 3

    detail = await OrderQueryService(factory).detail(order.id)
    assert detail["status"] == "QUEUED"
    assert detail["estimated_notional"] == "12340.00"
    assert len(detail["commands"]) == 1
    assert detail["commands"][0]["status"] == "PENDING"
    assert len(detail["outbox"]) == 1
    assert detail["outbox"][0]["status"] == "PENDING"
    assert await OrderIntegrityService(factory).verify() == []


@pytest.mark.asyncio
async def test_create_idempotency_conflict_and_order_validation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    service = OrderIntentService(_factory(session_factory))
    request = _create_request(account, instrument)
    await service.create(request)
    changed = replace(
        _create_request(account, instrument, key=request.idempotency_key),
        limit_price=Decimal("12.35"),
    )
    with pytest.raises(ApplicationError, match="idempotency") as conflict:
        await service.create(changed)
    assert conflict.value.code == "ORDER_IDEMPOTENCY_CONFLICT"

    invalid = replace(_create_request(account, instrument), quantity=Decimal("10"))
    with pytest.raises(ApplicationError) as lot_error:
        await service.create(invalid)
    assert lot_error.value.code == "ORDER_LOT_SIZE_VIOLATION"


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_queued_order_is_not_cancellable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    first = await OrderIntentService(factory).create(_create_request(account, instrument))
    cancel_request = CancelOrderRequest(
        order_id=first.id,
        idempotency_key=f"cancel-{first.id}",
        expected_order_version=2,
        correlation_id=uuid4(),
        reason="user cancelled",
        occurred_at=datetime.now(UTC),
    )
    cancelled = await OrderCancellationService(factory).cancel(cancel_request)
    repeated = await OrderCancellationService(factory).cancel(cancel_request)
    assert cancelled.status is OrderStatus.CANCELLED
    assert repeated.row_version == 3

    queued = await OrderIntentService(factory).create(_create_request(account, instrument))
    await OrderConfirmationService(factory).confirm(
        ConfirmOrderRequest(
            order_id=queued.id,
            idempotency_key=f"confirm-{queued.id}",
            expected_order_version=2,
            correlation_id=uuid4(),
        )
    )
    with pytest.raises(ApplicationError) as error:
        await OrderCancellationService(factory).cancel(
            CancelOrderRequest(
                order_id=queued.id,
                idempotency_key=f"cancel-{queued.id}",
                expected_order_version=3,
                correlation_id=uuid4(),
            )
        )
    assert error.value.code == "ORDER_ALREADY_QUEUED"


@pytest.mark.asyncio
async def test_expiration_only_changes_due_pending_orders(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    now = datetime.now(UTC)
    order = await OrderIntentService(factory).create(
        _create_request(account, instrument, expires_at=now + timedelta(seconds=1))
    )
    result = await OrderExpirationService(factory).expire_pending(
        now=now + timedelta(seconds=2), correlation_id=uuid4()
    )
    assert result.expired_order_ids == (order.id,)
    detail = await OrderQueryService(factory).detail(order.id)
    assert detail["status"] == "EXPIRED"
    assert detail["row_version"] == 3


@pytest.mark.asyncio
async def test_stale_confirmation_rolls_back_without_command(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    order = await OrderIntentService(factory).create(_create_request(account, instrument))
    with pytest.raises(ApplicationError) as error:
        await OrderConfirmationService(factory).confirm(
            ConfirmOrderRequest(
                order_id=order.id,
                idempotency_key=f"confirm-{order.id}",
                expected_order_version=1,
                correlation_id=uuid4(),
            )
        )
    assert error.value.code == "ORDER_VERSION_CONFLICT"
    detail = await OrderQueryService(factory).detail(order.id)
    assert detail["status"] == "WAITING_CONFIRMATION"
    assert detail["commands"] == []
    assert detail["outbox"] == []


@pytest.mark.parametrize(
    "failure_stage",
    (
        "after_action",
        "after_transition",
        "after_command",
        "after_events",
        "after_audit",
        "before_outbox",
        "before_commit",
    ),
)
@pytest.mark.asyncio
async def test_confirmation_failure_injection_rolls_back_every_fact(
    session_factory: async_sessionmaker[AsyncSession], failure_stage: str
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    order = await OrderIntentService(factory).create(_create_request(account, instrument))

    def fail(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError(f"injected:{stage}")

    with pytest.raises(RuntimeError, match="injected"):
        await OrderConfirmationService(factory, fail).confirm(
            ConfirmOrderRequest(
                order_id=order.id,
                idempotency_key=f"confirm-{order.id}",
                expected_order_version=2,
                correlation_id=uuid4(),
            )
        )
    detail = await OrderQueryService(factory).detail(order.id)
    assert detail["status"] == "WAITING_CONFIRMATION"
    assert detail["row_version"] == 2
    assert detail["confirmed_at"] is None
    assert detail["actions"] == []
    assert detail["commands"] == []
    assert detail["outbox"] == []
    assert len(await OrderQueryService(factory).timeline(order.id)) == 4


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_real_postgres_concurrent_confirmation_creates_one_fact_set() -> None:
    engine = create_async_engine(require_test_database_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(sessions))
    try:
        account, instrument = await _seed(sessions)
        order = await OrderIntentService(factory).create(_create_request(account, instrument))
        request = ConfirmOrderRequest(
            order_id=order.id,
            idempotency_key=f"concurrent-confirm-{order.id}",
            expected_order_version=2,
            correlation_id=uuid4(),
        )
        results = await asyncio.gather(
            OrderConfirmationService(factory).confirm(request),
            OrderConfirmationService(factory).confirm(request),
            return_exceptions=True,
        )
        assert any(not isinstance(item, Exception) for item in results)
        detail = await OrderQueryService(factory).detail(order.id)
        timeline = await OrderQueryService(factory).timeline(order.id)
        assert detail["status"] == "QUEUED"
        assert detail["row_version"] == 3
        assert len(detail["actions"]) == 1
        assert len(detail["commands"]) == 1
        assert len(detail["outbox"]) == 1
        assert (
            sum(
                item["label"].endswith("QUEUED")
                for item in timeline
                if item["kind"] == "TRANSITION"
            )
            == 1
        )
    finally:
        await engine.dispose()


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_real_postgres_confirmation_and_cancellation_are_serialized() -> None:
    engine = create_async_engine(require_test_database_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(sessions))
    try:
        account, instrument = await _seed(sessions)
        order = await OrderIntentService(factory).create(_create_request(account, instrument))
        results = await asyncio.gather(
            OrderConfirmationService(factory).confirm(
                ConfirmOrderRequest(order.id, f"confirm-{order.id}", 2, uuid4())
            ),
            OrderCancellationService(factory).cancel(
                CancelOrderRequest(order.id, f"cancel-{order.id}", 2, uuid4())
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, Exception) for item in results) == 1
        detail = await OrderQueryService(factory).detail(order.id)
        assert detail["status"] in ("QUEUED", "CANCELLED")
        assert detail["row_version"] == 3
        assert len(detail["actions"]) == 1
        assert len(detail["commands"]) == (1 if detail["status"] == "QUEUED" else 0)
        assert len(detail["outbox"]) == (1 if detail["status"] == "QUEUED" else 0)
    finally:
        await engine.dispose()


@pytest.mark.accounting_regression
@pytest.mark.asyncio
async def test_m05_never_mutates_accounting_tables(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    table_names = (
        "account_cash_balances",
        "positions",
        "cash_ledger_entries",
        "position_ledger_entries",
        "fills",
        "account_snapshots",
    )

    async def counts() -> dict[str, int]:
        async with session_factory() as session:
            return {
                name: int(await session.scalar(text(f"SELECT count(*) FROM {name}")) or 0)
                for name in table_names
            }

    before = await counts()
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    confirmed = await OrderIntentService(factory).create(_create_request(account, instrument))
    await OrderConfirmationService(factory).confirm(
        ConfirmOrderRequest(confirmed.id, f"confirm-{confirmed.id}", 2, uuid4())
    )
    cancelled = await OrderIntentService(factory).create(_create_request(account, instrument))
    await OrderCancellationService(factory).cancel(
        CancelOrderRequest(cancelled.id, f"cancel-{cancelled.id}", 2, uuid4())
    )
    expiring = await OrderIntentService(factory).create(
        _create_request(account, instrument, expires_at=datetime.now(UTC) + timedelta(seconds=1))
    )
    await OrderExpirationService(factory).expire_pending(
        now=datetime.now(UTC) + timedelta(seconds=2), correlation_id=uuid4()
    )
    assert (await OrderQueryService(factory).detail(expiring.id))["status"] == "EXPIRED"
    assert await counts() == before


@pytest.mark.asyncio
async def test_m05_command_constraints_accept_local_pending_submit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) "
                "FROM pg_constraint WHERE conrelid = 'order_commands'::regclass "
                "AND conname IN ('ck_order_commands_command_type_valid', "
                "'ck_order_commands_command_status_valid')"
            )
        )
        definitions = {name: definition for name, definition in rows}
    assert "SUBMIT_ORDER" in definitions["ck_order_commands_command_type_valid"]
    assert "PENDING" in definitions["ck_order_commands_command_status_valid"]
