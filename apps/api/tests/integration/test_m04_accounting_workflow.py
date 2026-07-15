import asyncio
from dataclasses import replace
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alphadesk_api.application.accounting import (
    AccountQueryService,
    AccountReconciliationService,
    CashFundingService,
    FillAccountingService,
    SimulatedAccountService,
)
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.cli.accounting import _demo_facts
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import ReconciliationStatus, SettlementPolicy
from tests.helpers import require_m04_test_database_url

pytestmark = [pytest.mark.integration, pytest.mark.m04]


@pytest.mark.asyncio
async def test_buy_buy_sell_idempotency_and_reconciliation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    require_m04_test_database_url()
    uow_factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))
    async with uow_factory() as uow:
        instrument = Instrument(
            symbol=f"M04-{uuid4().hex[:8]}",
            exchange="TEST",
            market="TEST",
            name="M04 test instrument",
            asset_type="EQUITY",
            currency="CNY",
            lot_size=Decimal("1"),
            price_tick=Decimal("0.01"),
            timezone="Asia/Shanghai",
        )
        await uow.instruments.add(instrument)
        await uow.commit()
    account = await SimulatedAccountService(uow_factory).create(
        account_code=f"M04-{uuid4().hex[:12]}",
        name="M04 integration",
        base_currency="CNY",
        initial_cash=Decimal("100000"),
        settlement_policy=SettlementPolicy.IMMEDIATE,
        idempotency_key=f"m04-test-{uuid4()}",
        correlation_id=uuid4(),
    )
    facts = _demo_facts(account.id, instrument.id)
    async with uow_factory() as uow:
        for order, fill in facts:
            await uow.orders.add(order)
            await uow.fills.append(fill)
        await uow.commit()
    service = FillAccountingService(uow_factory)
    results = [await service.apply(fill_id=fill.id) for _, fill in facts]
    repeated = await service.apply(fill_id=facts[0][1].id)
    assert not any(item.idempotent for item in results)
    assert repeated.idempotent

    _, balances, positions = await AccountQueryService(uow_factory).detail(account.id)
    assert balances[0].total_cash == Decimal("92939.84000000")
    assert positions[0].total_quantity == Decimal("900.00000000")
    assert positions[0].cost_basis == Decimal("7326.00000000")
    assert positions[0].average_cost == Decimal("8.14000000")
    assert positions[0].realized_pnl == Decimal("265.84000000")

    reconciliation = await AccountReconciliationService(uow_factory).run(
        account_id=account.id, correlation_id=uuid4()
    )
    assert reconciliation.run.status is ReconciliationStatus.MATCHED
    assert reconciliation.run.discrepancy_count == 0


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_withdrawals_lock_cash_projection() -> None:
    """Two withdrawals cannot both spend the same available cash."""
    engine = create_async_engine(require_m04_test_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    uow_factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))
    try:
        account = await SimulatedAccountService(uow_factory).create(
            account_code=f"M04-CON-{uuid4().hex[:8]}",
            name="M04 concurrency",
            base_currency="CNY",
            initial_cash=Decimal("100"),
            settlement_policy=SettlementPolicy.IMMEDIATE,
            idempotency_key=f"m04-concurrency-{uuid4()}",
            correlation_id=uuid4(),
        )
        funding = CashFundingService(uow_factory)

        results = await asyncio.gather(
            funding.post(
                account_id=account.id,
                amount=Decimal("70"),
                is_deposit=False,
                idempotency_key=f"withdraw-a-{uuid4()}",
                correlation_id=uuid4(),
            ),
            funding.post(
                account_id=account.id,
                amount=Decimal("70"),
                is_deposit=False,
                idempotency_key=f"withdraw-b-{uuid4()}",
                correlation_id=uuid4(),
            ),
            return_exceptions=True,
        )

        failures = [result for result in results if isinstance(result, ApplicationError)]
        assert len(failures) == 1
        assert failures[0].code == "INSUFFICIENT_CASH"
        _, balances, _ = await AccountQueryService(uow_factory).detail(account.id)
        assert balances[0].total_cash == Decimal("30.00000000")
        assert balances[0].available_cash == Decimal("30.00000000")
    finally:
        await engine.dispose()


@pytest.mark.concurrency
@pytest.mark.asyncio
async def test_concurrent_buys_serialize_and_concurrent_sells_prevent_oversell() -> None:
    """Cash/position locks serialize buys and reject the second overselling fill."""
    engine = create_async_engine(require_m04_test_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    uow_factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))
    try:
        async with uow_factory() as uow:
            instrument = Instrument(
                symbol=f"M04-CON-{uuid4().hex[:8]}",
                exchange="TEST",
                market="TEST",
                name="M04 concurrent fill instrument",
                asset_type="EQUITY",
                currency="CNY",
                lot_size=Decimal("1"),
                price_tick=Decimal("0.01"),
                timezone="Asia/Shanghai",
            )
            await uow.instruments.add(instrument)
            await uow.commit()
        account = await SimulatedAccountService(uow_factory).create(
            account_code=f"M04-FILL-{uuid4().hex[:8]}",
            name="M04 concurrent fills",
            base_currency="CNY",
            initial_cash=Decimal("100000"),
            settlement_policy=SettlementPolicy.IMMEDIATE,
            idempotency_key=f"m04-concurrent-fills-{uuid4()}",
            correlation_id=uuid4(),
        )

        templates = _demo_facts(account.id, instrument.id)
        buy_facts = []
        for order_template, fill_template in templates[:2]:
            correlation_id = uuid4()
            order = replace(
                order_template,
                id=uuid4(),
                idempotency_key=f"M04-CON-BUY-{uuid4()}",
                broker_order_id=f"M04-CON-BUY-{uuid4()}",
                correlation_id=correlation_id,
            )
            fill = replace(
                fill_template,
                id=uuid4(),
                order_id=order.id,
                broker_fill_id=f"M04-CON-BUY-FILL-{uuid4()}",
                correlation_id=correlation_id,
            )
            buy_facts.append((order, fill))
        async with uow_factory() as uow:
            for order, fill in buy_facts:
                await uow.orders.add(order)
                await uow.fills.append(fill)
            await uow.commit()

        accounting = FillAccountingService(uow_factory)
        buy_results = await asyncio.gather(
            *(accounting.apply(fill_id=fill.id) for _, fill in buy_facts),
            return_exceptions=True,
        )
        assert not any(isinstance(result, Exception) for result in buy_results)
        _, _, positions_after_buys = await AccountQueryService(uow_factory).detail(account.id)
        assert positions_after_buys[0].total_quantity == Decimal("1500.00000000")
        assert positions_after_buys[0].average_cost == Decimal("8.14000000")

        sell_template_order, sell_template_fill = templates[2]
        sell_facts = []
        for label in ("A", "B"):
            correlation_id = uuid4()
            order = replace(
                sell_template_order,
                id=uuid4(),
                requested_quantity=Decimal("1000"),
                filled_quantity=Decimal("1000"),
                idempotency_key=f"M04-CON-SELL-{label}-{uuid4()}",
                broker_order_id=f"M04-CON-SELL-{label}-{uuid4()}",
                correlation_id=correlation_id,
            )
            fill = replace(
                sell_template_fill,
                id=uuid4(),
                order_id=order.id,
                quantity=Decimal("1000"),
                gross_amount=Decimal("8600"),
                commission=Decimal("5"),
                tax=Decimal("0"),
                net_amount=Decimal("8595"),
                broker_fill_id=f"M04-CON-SELL-FILL-{label}-{uuid4()}",
                correlation_id=correlation_id,
            )
            sell_facts.append((order, fill))
        async with uow_factory() as uow:
            for order, fill in sell_facts:
                await uow.orders.add(order)
                await uow.fills.append(fill)
            await uow.commit()

        sell_results = await asyncio.gather(
            *(accounting.apply(fill_id=fill.id) for _, fill in sell_facts),
            return_exceptions=True,
        )
        sell_failures = [result for result in sell_results if isinstance(result, ApplicationError)]
        assert len(sell_failures) == 1
        assert sell_failures[0].code == "INSUFFICIENT_POSITION"
        _, _, positions_after_sells = await AccountQueryService(uow_factory).detail(account.id)
        assert positions_after_sells[0].total_quantity == Decimal("500.00000000")
        assert positions_after_sells[0].cost_basis == Decimal("4070.00000000")
    finally:
        await engine.dispose()
