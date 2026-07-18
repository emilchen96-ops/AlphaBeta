from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.accounting import AccountQueryService, SimulatedAccountService
from alphadesk_api.application.backtests import BacktestIntegrityService, BacktestQueryService
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.cli.backtests import _run_demo
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.enums import OrderSide, SettlementPolicy
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies
from tests.helpers import require_bt01_test_database_url

pytestmark = [pytest.mark.integration, pytest.mark.bt01]


def _factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> UnitOfWorkFactory:
    return cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))


@pytest.mark.asyncio
async def test_daily_demo_is_t_plus_one_idempotent_isolated_and_reconciled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    require_bt01_test_database_url()
    factory = _factory(session_factory)
    ordinary = await SimulatedAccountService(factory).create(
        account_code="BT01-ORDINARY-CONTROL",
        name="BT01 ordinary account control",
        base_currency="CNY",
        initial_cash=Decimal("50000"),
        settlement_policy=SettlementPolicy.IMMEDIATE,
        idempotency_key="bt01-ordinary-control-v1",
    )
    _, before_balances, before_positions = await AccountQueryService(factory).detail(ordinary.id)

    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    settings = Settings(
        environment="test",
        risk_allow_market_orders=False,
        backtest_max_instruments=5,
        backtest_max_bars=100,
        backtest_max_sessions=100,
    )
    first = await _run_demo(factory, registry, settings)
    repeated = await _run_demo(factory, registry, settings)

    first_run = cast(dict[str, object], first["run"])
    repeated_run = cast(dict[str, object], repeated["run"])
    assert first_run["id"] == repeated_run["id"]
    assert repeated["replayed"] is True
    assert first["signals"] == 2
    assert first["orders"] == 2
    assert first["fills"] == 2
    assert cast(dict[str, object], first["integrity"])["passed"] is True

    run_id = first_run["id"]
    assert isinstance(run_id, UUID)
    query = BacktestQueryService(factory)
    signals = await query.signals(run_id)
    fills = await query.fills(run_id)
    orders = await query.orders(run_id)
    assert [signal.side for signal in signals] == [OrderSide.BUY, OrderSide.SELL]
    assert len(fills) == len(orders) == 2
    order_by_signal = {order.signal_id: order for order in orders}
    fill_by_order = {fill.order_id: fill for fill in fills}
    for signal in signals:
        order = order_by_signal[signal.id]
        fill = fill_by_order[order.id]
        assert order.signal_id == signal.id
        assert fill.executed_at > signal.generated_at
        assert fill.executed_at.hour == 1 and fill.executed_at.minute == 30

    report = await BacktestIntegrityService(factory).verify(run_id)
    assert report.passed
    _, after_balances, after_positions = await AccountQueryService(factory).detail(ordinary.id)
    assert after_balances == before_balances
    assert after_positions == before_positions
