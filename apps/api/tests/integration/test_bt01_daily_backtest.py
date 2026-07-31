from datetime import timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.accounting import AccountQueryService, SimulatedAccountService
from alphadesk_api.application.backtests import (
    BacktestIntegrityService,
    BacktestQueryService,
    BacktestService,
    CreateBacktestRequest,
)
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.cli.backtests import _ensure_demo_history, _run_demo
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.backtest import (
    BacktestEventType,
    BacktestExecutionPriceMode,
    BacktestRunStatus,
)
from alphadesk_domain.broker import AshareSimpleFeeModel, FixedBasisPointsSlippageModel
from alphadesk_domain.enums import (
    MarketTimeframe,
    OrderActorType,
    OrderSide,
    OrderType,
    OutboxStatus,
    SettlementPolicy,
    TimeInForce,
)
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
    assert first_run["status"] == BacktestRunStatus.COMPLETED
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
    points = await query.equity_curve(run_id)
    metrics = await query.metrics(run_id)
    timeline = await query.timeline(run_id)
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

    assert len(points) == metrics.trading_sessions == 9
    assert metrics.fill_count == metrics.buy_fill_count + metrics.sell_fill_count == 2
    assert points[-1].total_equity == metrics.final_equity
    assert [event.sequence_number for event in timeline] == list(range(1, len(timeline) + 1))
    phases = [event.event_type for event in timeline]
    assert (
        phases.index(BacktestEventType.SESSION_OPEN)
        < phases.index(BacktestEventType.SESSION_CLOSE)
        < phases.index(BacktestEventType.SESSION_END)
    )

    async with factory() as uow:
        owned_accounts = [
            item
            for item in await uow.accounts.list_all()
            if item.metadata.get("owner_id") == str(run_id)
        ]
        assert len(owned_accounts) == 1
        for order in orders:
            actions = await uow.order_actions.list_by_order(order.id)
            confirmations = [item for item in actions if str(item.action_type) == "CONFIRM"]
            assert len(confirmations) == 1
            assert confirmations[0].actor_type == OrderActorType.SYSTEM
            assert confirmations[0].actor_id == "BACKTEST_ENGINE"
            outbox = await uow.outbox.list_by_aggregate("ORDER", order.id)
            assert len(outbox) == 1
            assert outbox[0].status is OutboxStatus.SUPPRESSED
            assert outbox[0].suppression_reason == "BACKTEST_ENGINE"
            assert outbox[0].published_at is None
            assert outbox[0].attempts == 0
            attempts = await uow.broker_execution_attempts.list_by_order(order.id)
            assert len(attempts) == 1
            snapshot = attempts[0].market_snapshot
            assert snapshot["source"] == "BACKTEST_DAILY_BAR"
            assert snapshot["open"] == snapshot["high"] == snapshot["low"] == snapshot["close"]
        for fill in fills:
            transaction = await uow.ledger_transactions.get_by_fill_id(fill.id)
            assert transaction is not None
            assert transaction.related_order_id == fill.order_id
            assert transaction.occurred_at == fill.executed_at

    report = await BacktestIntegrityService(factory).verify(run_id)
    assert report.passed
    _, after_balances, after_positions = await AccountQueryService(factory).detail(ordinary.id)
    assert after_balances == before_balances
    assert after_positions == before_positions


@pytest.mark.asyncio
async def test_next_open_mode_fills_after_signal_close_with_configured_slippage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    require_bt01_test_database_url()
    factory = _factory(session_factory)
    instrument, bars = await _ensure_demo_history(factory)
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    settings = Settings(
        environment="test",
        risk_allow_market_orders=False,
        backtest_max_instruments=5,
        backtest_max_bars=100,
        backtest_max_sessions=100,
    )

    result = await BacktestService(factory, registry, settings).run(
        CreateBacktestRequest(
            strategy_key="sma_crossover",
            parameters={
                "short_window": 2,
                "long_window": 3,
                "quantity": Decimal("100"),
            },
            instrument_ids=(instrument.id,),
            timeframe=MarketTimeframe.DAY_1,
            start_at=bars[0].timestamp,
            end_at=bars[-1].timestamp + timedelta(days=2),
            initial_cash=Decimal("100000"),
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            execution_price_mode=BacktestExecutionPriceMode.NEXT_OPEN,
            position_size_ratio=Decimal("0.5"),
            maximum_entry_gap_ratio=None,
            fee_configuration=AshareSimpleFeeModel(),
            slippage_configuration=FixedBasisPointsSlippageModel(basis_points=Decimal("2")),
            maximum_volume_participation=Decimal("0.1"),
            benchmark_symbol=None,
            data_source_code="BT01_DEMO",
            idempotency_key="bt01-next-open-position-sizing-v3",
        )
    )

    query = BacktestQueryService(factory)
    signals = await query.signals(result.run.id)
    orders = await query.orders(result.run.id)
    fills = await query.fills(result.run.id)
    assert len(signals) == len(orders) == len(fills) == 2
    assert [signal.target_weight for signal in signals] == [
        Decimal("0.5"),
        Decimal("0"),
    ]
    assert all(signal.target_quantity is None for signal in signals)
    assert all(order.order_type is OrderType.MARKET for order in orders)
    order_by_signal = {order.signal_id: order for order in orders}
    fill_by_order = {fill.order_id: fill for fill in fills}
    for signal in signals:
        fill = fill_by_order[order_by_signal[signal.id].id]
        assert fill.executed_at > signal.generated_at
    buy_signal = next(signal for signal in signals if signal.side is OrderSide.BUY)
    sell_signal = next(signal for signal in signals if signal.side is OrderSide.SELL)
    buy_order = order_by_signal[buy_signal.id]
    sell_order = order_by_signal[sell_signal.id]
    assert buy_order.requested_quantity > Decimal("100")
    assert buy_order.requested_quantity % instrument.lot_size == Decimal("0")
    assert sell_order.requested_quantity == buy_order.requested_quantity
    assert fill_by_order[order_by_signal[buy_signal.id].id].price == Decimal("12.00240000")
    assert result.run.configuration.risk_configuration_snapshot is not None
    assert result.run.configuration.risk_configuration_snapshot.allow_market_orders is True
