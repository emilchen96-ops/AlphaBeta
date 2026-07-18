import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alphadesk_api.application.accounting import AccountQueryService, SimulatedAccountService
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.orders import (
    ConfirmOrderRequest,
    CreateOrderRequest,
    OrderConfirmationService,
    OrderIntentService,
)
from alphadesk_api.application.simulated_execution import (
    LOCAL_CONSUMER,
    LOCAL_SUPPRESSION_REASON,
    SimulatedBrokerExecutionService,
    SimulatedExecutionIntegrityService,
    SimulatedExecutionQueryService,
    SimulatedExecutionRequest,
)
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.broker import ExecutionMarketSnapshot, TradingStatus
from alphadesk_domain.entities import Instrument, Order, TradingAccount
from alphadesk_domain.enums import (
    CommandStatus,
    OrderStatus,
    OutboxStatus,
    ReconciliationStatus,
    SettlementPolicy,
)
from tests.helpers import require_b01_test_database_url

pytestmark = [pytest.mark.integration, pytest.mark.b01]


def _factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> UnitOfWorkFactory:
    return cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    initial_cash: Decimal = Decimal("100000"),
) -> tuple[TradingAccount, Instrument]:
    require_b01_test_database_url()
    factory = _factory(session_factory)
    async with factory() as uow:
        instrument = Instrument(
            symbol=f"B01-{uuid4().hex[:8]}",
            exchange="TEST",
            market="TEST",
            name="B01 simulated execution instrument",
            asset_type="EQUITY",
            currency="CNY",
            lot_size=Decimal("1"),
            price_tick=Decimal("0.01"),
            timezone="Asia/Shanghai",
        )
        await uow.instruments.add(instrument)
        await uow.commit()
    account = await SimulatedAccountService(factory).create(
        account_code=f"B01-{uuid4().hex[:10]}",
        name="B01 simulated account",
        base_currency="CNY",
        initial_cash=initial_cash,
        settlement_policy=SettlementPolicy.IMMEDIATE,
        idempotency_key=f"b01-account-{uuid4()}",
        correlation_id=uuid4(),
    )
    return account, instrument


async def _queued_order(
    factory: UnitOfWorkFactory,
    account: TradingAccount,
    instrument: Instrument,
    *,
    side: str = "BUY",
    quantity: Decimal = Decimal("100"),
    order_type: str = "MARKET",
    limit_price: Decimal | None = None,
    expires_at: datetime | None = None,
) -> Order:
    now = datetime.now(UTC)
    order = await OrderIntentService(factory).create(
        CreateOrderRequest(
            account_id=account.id,
            instrument_id=instrument.id,
            side=side,
            order_type=order_type,
            time_in_force="DAY",
            quantity=quantity,
            limit_price=limit_price,
            expires_at=expires_at,
            idempotency_key=f"b01-order-{uuid4()}",
            correlation_id=uuid4(),
            occurred_at=now,
        )
    )
    return await OrderConfirmationService(factory).confirm(
        ConfirmOrderRequest(
            order_id=order.id,
            idempotency_key=f"b01-confirm-{uuid4()}",
            expected_order_version=order.row_version,
            correlation_id=uuid4(),
            occurred_at=now + timedelta(milliseconds=1),
        )
    )


def _market(
    instrument: Instrument,
    *,
    at: datetime,
    price: Decimal = Decimal("10"),
    available_volume: Decimal | None = None,
    trading_status: TradingStatus = TradingStatus.TRADING,
) -> ExecutionMarketSnapshot:
    return ExecutionMarketSnapshot(
        instrument_id=instrument.id,
        timestamp=at,
        trading_status=trading_status,
        source="B01_TEST_SNAPSHOT",
        is_stale=False,
        last_price=price,
        bid_price=price,
        ask_price=price,
        available_volume=available_volume,
    )


@pytest.mark.asyncio
async def test_market_buy_is_atomic_idempotent_and_suppresses_outbox(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    order = await _queued_order(factory, account, instrument)
    now = datetime.now(UTC)
    request = SimulatedExecutionRequest(
        order_id=order.id,
        execution_market_snapshot=_market(instrument, at=now),
        idempotency_key=f"b01-execute-{uuid4()}",
        correlation_id=uuid4(),
        requested_at=now,
    )
    service = SimulatedBrokerExecutionService(factory)
    result = await service.execute(request)
    repeated = await service.execute(request)

    assert result.order.status is OrderStatus.FILLED
    assert result.attempt.attempt_number == 1
    assert len(result.fills) == 1
    assert len(result.accounting_results) == 1
    assert result.reconciliation is not None
    assert result.reconciliation.run.status is ReconciliationStatus.MATCHED
    assert repeated.idempotent
    assert repeated.attempt.id == result.attempt.id
    assert repeated.fills[0].id == result.fills[0].id
    assert repeated.accounting_results[0].idempotent

    _, balances, positions = await AccountQueryService(factory).detail(account.id)
    total_fee = result.fills[0].commission + result.fills[0].tax + result.fills[0].other_fee
    assert balances[0].total_cash == Decimal("100000") - Decimal("1000") - total_fee
    assert positions[0].total_quantity == Decimal("100")
    assert positions[0].cost_basis == Decimal("1000") + total_fee
    assert await SimulatedExecutionIntegrityService(factory).verify_order(order.id) == []

    async with factory() as uow:
        command = await uow.order_commands.get_submit_command_by_order(order.id)
        outbox = await uow.outbox.list_by_aggregate("ORDER", order.id)
        attempts = await uow.broker_execution_attempts.list_by_order(order.id)
        fills = await uow.fills.list_by_order(order.id)
        assert command is not None
        assert command.status is CommandStatus.CONSUMED
        assert command.consumed_by == LOCAL_CONSUMER
        assert len(outbox) == 1
        assert outbox[0].status is OutboxStatus.SUPPRESSED
        assert outbox[0].suppression_reason == LOCAL_SUPPRESSION_REASON
        assert len(attempts) == 1
        assert len(fills) == 1


@pytest.mark.asyncio
async def test_limit_no_fill_records_attempt_without_ledger_change(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    order = await _queued_order(
        factory,
        account,
        instrument,
        order_type="LIMIT",
        limit_price=Decimal("9"),
    )
    now = datetime.now(UTC)
    result = await SimulatedBrokerExecutionService(factory).execute(
        SimulatedExecutionRequest(
            order_id=order.id,
            execution_market_snapshot=_market(instrument, at=now, price=Decimal("10")),
            idempotency_key=f"b01-no-fill-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=now,
        )
    )
    assert result.attempt.result_status.value == "NO_FILL"
    assert result.order.status is OrderStatus.BROKER_ACCEPTED
    assert result.fills == ()
    assert result.accounting_results == ()
    _, balances, positions = await AccountQueryService(factory).detail(account.id)
    assert balances[0].total_cash == Decimal("100000")
    assert positions == []


@pytest.mark.asyncio
async def test_partial_fills_use_authoritative_facts_and_finish_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    order = await _queued_order(factory, account, instrument, quantity=Decimal("100"))
    service = SimulatedBrokerExecutionService(factory)
    first_at = datetime.now(UTC)
    first = await service.execute(
        SimulatedExecutionRequest(
            order_id=order.id,
            execution_market_snapshot=_market(
                instrument, at=first_at, available_volume=Decimal("40")
            ),
            idempotency_key=f"b01-partial-1-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=first_at,
        )
    )
    assert first.order.status is OrderStatus.PARTIALLY_FILLED
    assert first.fills[0].sequence_number == 1

    second_at = first_at + timedelta(seconds=1)
    second = await service.execute(
        SimulatedExecutionRequest(
            order_id=order.id,
            execution_market_snapshot=_market(
                instrument, at=second_at, available_volume=Decimal("60")
            ),
            idempotency_key=f"b01-partial-2-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=second_at,
        )
    )
    assert second.attempt.attempt_number == 2
    assert second.attempt.previously_filled_quantity == Decimal("40")
    assert second.attempt.attempted_quantity == Decimal("60")
    assert second.order.status is OrderStatus.FILLED
    assert second.fills[0].sequence_number == 2
    summary = await SimulatedExecutionQueryService(factory).by_order(order.id)
    assert summary["filled_quantity"] == Decimal("100")
    assert summary["remaining_quantity"] == ZERO
    assert summary["integrity_issues"] == []


@pytest.mark.asyncio
async def test_sell_posts_cash_position_tax_and_realized_pnl(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    service = SimulatedBrokerExecutionService(factory)
    buy = await _queued_order(factory, account, instrument, quantity=Decimal("100"))
    buy_at = datetime.now(UTC)
    await service.execute(
        SimulatedExecutionRequest(
            order_id=buy.id,
            execution_market_snapshot=_market(instrument, at=buy_at, price=Decimal("10")),
            idempotency_key=f"b01-buy-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=buy_at,
        )
    )
    sell = await _queued_order(factory, account, instrument, side="SELL", quantity=Decimal("40"))
    sell_at = buy_at + timedelta(seconds=1)
    result = await service.execute(
        SimulatedExecutionRequest(
            order_id=sell.id,
            execution_market_snapshot=_market(instrument, at=sell_at, price=Decimal("12")),
            idempotency_key=f"b01-sell-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=sell_at,
        )
    )
    fill = result.fills[0]
    assert fill.tax > ZERO
    assert result.accounting_results[0].cash_delta == fill.net_amount
    _, balances, positions = await AccountQueryService(factory).detail(account.id)
    assert positions[0].total_quantity == Decimal("60")
    assert positions[0].realized_pnl > ZERO
    assert balances[0].total_cash > Decimal("99000")
    assert result.reconciliation is not None
    assert result.reconciliation.run.status is ReconciliationStatus.MATCHED


@pytest.mark.asyncio
async def test_insufficient_cash_records_rejection_without_fill_or_negative_cash(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory, initial_cash=Decimal("100"))
    factory = _factory(session_factory)
    order = await _queued_order(factory, account, instrument, quantity=Decimal("100"))
    now = datetime.now(UTC)
    result = await SimulatedBrokerExecutionService(factory).execute(
        SimulatedExecutionRequest(
            order_id=order.id,
            execution_market_snapshot=_market(instrument, at=now, price=Decimal("10")),
            idempotency_key=f"b01-insufficient-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=now,
        )
    )
    assert result.attempt.rejection_code == "BROKER_INSUFFICIENT_CASH"
    assert result.order.status is OrderStatus.FAILED
    assert result.fills == ()
    _, balances, positions = await AccountQueryService(factory).detail(account.id)
    assert balances[0].total_cash == Decimal("100")
    assert positions == []


@pytest.mark.asyncio
async def test_suspension_expiry_and_insufficient_position_are_controlled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    service = SimulatedBrokerExecutionService(factory)

    suspended = await _queued_order(factory, account, instrument)
    suspended_at = datetime.now(UTC)
    suspended_result = await service.execute(
        SimulatedExecutionRequest(
            order_id=suspended.id,
            execution_market_snapshot=_market(
                instrument,
                at=suspended_at,
                trading_status=TradingStatus.SUSPENDED,
            ),
            idempotency_key=f"b01-suspended-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=suspended_at,
        )
    )
    assert suspended_result.order.status is OrderStatus.EXECUTOR_REJECTED
    assert suspended_result.fills == ()

    created_at = datetime.now(UTC)
    expired = await _queued_order(
        factory,
        account,
        instrument,
        expires_at=created_at + timedelta(seconds=1),
    )
    expired_at = created_at + timedelta(seconds=2)
    expired_result = await service.execute(
        SimulatedExecutionRequest(
            order_id=expired.id,
            execution_market_snapshot=_market(instrument, at=expired_at),
            idempotency_key=f"b01-expired-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=expired_at,
        )
    )
    assert expired_result.order.status is OrderStatus.EXPIRED
    assert expired_result.fills == ()

    sell = await _queued_order(factory, account, instrument, side="SELL", quantity=Decimal("100"))
    sell_at = expired_at + timedelta(seconds=1)
    sell_result = await service.execute(
        SimulatedExecutionRequest(
            order_id=sell.id,
            execution_market_snapshot=_market(instrument, at=sell_at),
            idempotency_key=f"b01-no-position-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=sell_at,
        )
    )
    assert sell_result.attempt.rejection_code == "BROKER_INSUFFICIENT_POSITION"
    assert sell_result.order.status is OrderStatus.FAILED
    assert sell_result.fills == ()


@pytest.mark.parametrize(
    "stage",
    (
        "after_execution_attempt",
        "after_order_transition",
        "after_fill",
        "after_fill_accounting",
        "after_cash_ledger",
        "after_position_ledger",
        "after_fill_state",
        "after_account_snapshot",
        "after_command_consumed",
        "after_outbox_suppressed",
        "before_commit",
    ),
)
@pytest.mark.asyncio
async def test_failure_injection_rolls_back_every_b01_fact(
    session_factory: async_sessionmaker[AsyncSession], stage: str
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    order = await _queued_order(factory, account, instrument)
    now = datetime.now(UTC)

    def fail(current: str) -> None:
        if current == stage:
            raise RuntimeError(f"injected:{stage}")

    with pytest.raises(RuntimeError, match="injected"):
        await SimulatedBrokerExecutionService(factory, failure_injector=fail).execute(
            SimulatedExecutionRequest(
                order_id=order.id,
                execution_market_snapshot=_market(instrument, at=now),
                idempotency_key=f"b01-rollback-{uuid4()}",
                correlation_id=uuid4(),
                requested_at=now,
            )
        )
    async with factory() as uow:
        restored = await uow.orders.get_by_id(order.id)
        command = await uow.order_commands.get_submit_command_by_order(order.id)
        outbox = await uow.outbox.list_by_aggregate("ORDER", order.id)
        attempts = await uow.broker_execution_attempts.list_by_order(order.id)
        fills = await uow.fills.list_by_order(order.id)
        transactions, _ = await uow.ledger_transactions.list_for_account(
            account.id, offset=0, limit=100
        )
        assert restored is not None and restored.status is OrderStatus.QUEUED
        assert restored.row_version == order.row_version
        assert command is not None and command.status is CommandStatus.PENDING
        assert len(outbox) == 1 and outbox[0].status is OutboxStatus.PENDING
        assert attempts == []
        assert fills == []
        assert len(transactions) == 1  # initial deposit only
        assert await uow.account_snapshots.latest(account.id) is None
        assert await uow.account_reconciliations.latest(account.id) is None


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_real_postgres_concurrent_execution_converges_to_one_fill() -> None:
    engine = create_async_engine(require_b01_test_database_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    factory = _factory(sessions)
    try:
        account, instrument = await _seed(sessions)
        order = await _queued_order(factory, account, instrument)
        now = datetime.now(UTC)
        request = SimulatedExecutionRequest(
            order_id=order.id,
            execution_market_snapshot=_market(instrument, at=now),
            idempotency_key=f"b01-concurrent-{uuid4()}",
            correlation_id=uuid4(),
            requested_at=now,
        )
        results = await asyncio.gather(
            SimulatedBrokerExecutionService(factory).execute(request),
            SimulatedBrokerExecutionService(factory).execute(request),
        )
        assert sum(item.idempotent for item in results) == 1
        summary = await SimulatedExecutionQueryService(factory).by_order(order.id)
        assert len(cast(list[object], summary["attempts"])) == 1
        assert len(cast(list[object], summary["fills"])) == 1
        assert summary["integrity_issues"] == []
    finally:
        await engine.dispose()


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_real_postgres_different_keys_and_partial_completion_do_not_overfill() -> None:
    engine = create_async_engine(require_b01_test_database_url(), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    factory = _factory(sessions)
    try:
        account, instrument = await _seed(sessions)
        order = await _queued_order(factory, account, instrument)
        first_at = datetime.now(UTC)
        first = await SimulatedBrokerExecutionService(factory).execute(
            SimulatedExecutionRequest(
                order_id=order.id,
                execution_market_snapshot=_market(
                    instrument, at=first_at, available_volume=Decimal("40")
                ),
                idempotency_key=f"b01-initial-partial-{uuid4()}",
                correlation_id=uuid4(),
                requested_at=first_at,
            )
        )
        assert first.order.status is OrderStatus.PARTIALLY_FILLED
        complete_at = first_at + timedelta(seconds=1)
        requests = [
            SimulatedExecutionRequest(
                order_id=order.id,
                execution_market_snapshot=_market(
                    instrument, at=complete_at, available_volume=Decimal("60")
                ),
                idempotency_key=f"b01-competing-{uuid4()}",
                correlation_id=uuid4(),
                requested_at=complete_at,
            )
            for _ in range(2)
        ]
        results = await asyncio.gather(
            *(SimulatedBrokerExecutionService(factory).execute(item) for item in requests),
            return_exceptions=True,
        )
        successes = [item for item in results if not isinstance(item, Exception)]
        failures = [item for item in results if isinstance(item, ApplicationError)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert failures[0].code == "BROKER_ORDER_NOT_EXECUTABLE"
        summary = await SimulatedExecutionQueryService(factory).by_order(order.id)
        assert summary["filled_quantity"] == Decimal("100")
        assert len(cast(list[object], summary["attempts"])) == 2
        assert len(cast(list[object], summary["fills"])) == 2
        assert summary["integrity_issues"] == []
    finally:
        await engine.dispose()


ZERO = Decimal("0")
