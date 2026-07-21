from dataclasses import asdict
from datetime import timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.accounting import AccountQueryService, SimulatedAccountService
from alphadesk_api.application.backtests import BacktestQueryService
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.replays import (
    CreateReplayRequest,
    ReplayControlRequest,
    ReplayIntegrityService,
    ReplayQueryService,
    ReplayService,
)
from alphadesk_api.cli.backtests import _ensure_demo_history
from alphadesk_api.cli.backtests import _run_demo as run_backtest_demo
from alphadesk_api.cli.replays import _run_demo as run_replay_demo
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.broker import AshareSimpleFeeModel, FixedBasisPointsSlippageModel
from alphadesk_domain.enums import (
    OrderSide,
    OrderType,
    OutboxStatus,
    SettlementPolicy,
    TimeInForce,
)
from alphadesk_domain.replay import (
    ReplayControlActionType,
    ReplayRunStatus,
    ReplaySpeedMode,
)
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies
from tests.helpers import require_rt01_test_database_url

pytestmark = [pytest.mark.integration, pytest.mark.rt01]


def _factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> UnitOfWorkFactory:
    return cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))


@pytest.mark.asyncio
async def test_replay_demo_is_isolated_t_plus_one_reconciled_and_matches_bt01(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    require_rt01_test_database_url()
    factory = _factory(session_factory)
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    settings = Settings(
        environment="test",
        risk_allow_market_orders=False,
        replay_max_instruments=5,
        replay_max_sessions=100,
        backtest_max_instruments=5,
        backtest_max_bars=100,
        backtest_max_sessions=100,
    )
    ordinary = await SimulatedAccountService(factory).create(
        account_code="RT01-ORDINARY-CONTROL",
        name="RT01 ordinary account control",
        base_currency="CNY",
        initial_cash=Decimal("50000"),
        settlement_policy=SettlementPolicy.IMMEDIATE,
        idempotency_key="rt01-ordinary-control-v1",
    )
    _, before_cash, before_positions = await AccountQueryService(factory).detail(ordinary.id)

    backtest = await run_backtest_demo(factory, registry, settings)
    replay = await run_replay_demo(factory, registry, settings)
    replay_again = await run_replay_demo(factory, registry, settings)
    replay_run = cast(dict[str, object], replay["run"])
    assert replay_run["id"] == cast(dict[str, object], replay_again["run"])["id"]
    assert replay_run["status"] == ReplayRunStatus.COMPLETED.value
    assert replay["signals"] == replay["orders"] == replay["fills"] == 2
    assert cast(dict[str, object], replay["integrity"])["ok"] is True

    replay_id = replay_run["id"]
    assert isinstance(replay_id, UUID)
    query = ReplayQueryService(factory)
    signals = await query.signals(replay_id)
    orders = await query.orders(replay_id)
    fills = await query.fills(replay_id)
    points = await query.equity(replay_id)
    assert [item.side for item in signals] == [OrderSide.BUY, OrderSide.SELL]
    order_by_signal = {item.signal_id: item for item in orders}
    fill_by_order = {item.order_id: item for item in fills}
    for signal in signals:
        order = order_by_signal[signal.id]
        fill = fill_by_order[order.id]
        assert fill.executed_at > signal.generated_at
        assert (fill.executed_at.hour, fill.executed_at.minute) == (1, 30)

    backtest_run = cast(dict[str, object], backtest["run"])
    backtest_id = backtest_run["id"]
    assert isinstance(backtest_id, UUID)
    backtest_query = BacktestQueryService(factory)
    backtest_signals = await backtest_query.signals(backtest_id)
    backtest_orders = await backtest_query.orders(backtest_id)
    backtest_fills = await backtest_query.fills(backtest_id)
    backtest_metrics = await backtest_query.metrics(backtest_id)
    assert [(item.side, item.target_quantity) for item in signals] == [
        (item.side, item.target_quantity) for item in backtest_signals
    ]
    assert [(item.side, item.requested_quantity) for item in orders] == [
        (item.side, item.requested_quantity) for item in backtest_orders
    ]
    assert [(item.quantity, item.price) for item in fills] == [
        (item.quantity, item.price) for item in backtest_fills
    ]
    final_summary = cast(dict[str, object], replay_run["final_summary"])
    for field in (
        "final_equity",
        "total_fees",
        "total_return",
        "maximum_drawdown",
        "realized_pnl",
    ):
        assert final_summary[field] == str(getattr(backtest_metrics, field))
    assert points[-1].total_equity == backtest_metrics.final_equity

    async with factory() as uow:
        for order in orders:
            outbox = await uow.outbox.list_by_aggregate("ORDER", order.id)
            assert len(outbox) == 1
            assert outbox[0].status is OutboxStatus.SUPPRESSED
            assert outbox[0].suppression_reason == "REPLAY_ENGINE"
            assert outbox[0].published_at is None
        account_id = replay_run["account_id"]
        assert isinstance(account_id, UUID)
        account = await uow.accounts.get_by_id(account_id)
        assert account is not None
        assert account.metadata["scope"] == "RT01"
        assert account.metadata["owner_id"] == str(replay_id)

    report = await ReplayIntegrityService(factory).verify(replay_id)
    assert report.ok, asdict(report)
    _, after_cash, after_positions = await AccountQueryService(factory).detail(ordinary.id)
    assert after_cash == before_cash
    assert after_positions == before_positions


@pytest.mark.asyncio
async def test_replay_control_is_versioned_idempotent_and_step_advances_one_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    require_rt01_test_database_url()
    factory = _factory(session_factory)
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    settings = Settings(environment="test", replay_max_sessions=100)
    instrument, bars = await _ensure_demo_history(factory)
    service = ReplayService(factory, registry, settings)
    created = await service.create(
        CreateReplayRequest(
            strategy_key="sma_crossover",
            parameters={"short_window": 2, "long_window": 3, "quantity": Decimal("100")},
            instrument_ids=(instrument.id,),
            start_at=bars[0].timestamp,
            end_at=bars[-1].timestamp + timedelta(days=2),
            initial_cash=Decimal("100000"),
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            fee_configuration=AshareSimpleFeeModel(),
            slippage_configuration=FixedBasisPointsSlippageModel(basis_points=Decimal("2")),
            maximum_volume_participation=Decimal("0.1"),
            speed_mode=ReplaySpeedMode.MANUAL,
            data_source_code="BT01_DEMO",
            idempotency_key="rt01-control-test-v1",
        )
    )
    run = created.run
    assert run.status is ReplayRunStatus.READY

    request = ReplayControlRequest(
        replay_run_id=run.id,
        action_type=ReplayControlActionType.START,
        idempotency_key="start-once",
        expected_run_version=run.row_version,
    )
    run = await service.control(request)
    first_started_version = run.row_version
    replayed = await service.control(request)
    assert replayed.row_version == first_started_version
    with pytest.raises(ApplicationError) as stale:
        await service.control(
            ReplayControlRequest(
                replay_run_id=run.id,
                action_type=ReplayControlActionType.PAUSE,
                idempotency_key="stale-pause",
                expected_run_version=run.row_version - 1,
            )
        )
    assert stale.value.code == "REPLAY_VERSION_CONFLICT"

    run = await service.control(
        ReplayControlRequest(
            replay_run_id=run.id,
            action_type=ReplayControlActionType.PAUSE,
            idempotency_key="pause-1",
            expected_run_version=run.row_version,
        )
    )
    run = await service.control(
        ReplayControlRequest(
            replay_run_id=run.id,
            action_type=ReplayControlActionType.SET_SPEED,
            idempotency_key="speed-x10",
            expected_run_version=run.row_version,
            requested_speed=ReplaySpeedMode.X10,
        )
    )
    assert run.speed_mode is ReplaySpeedMode.X10
    run = await service.control(
        ReplayControlRequest(
            replay_run_id=run.id,
            action_type=ReplayControlActionType.RESUME,
            idempotency_key="resume-1",
            expected_run_version=run.row_version,
        )
    )
    run = await service.control(
        ReplayControlRequest(
            replay_run_id=run.id,
            action_type=ReplayControlActionType.PAUSE,
            idempotency_key="pause-2",
            expected_run_version=run.row_version,
        )
    )
    before_step = run.current_session_index
    run = await service.control(
        ReplayControlRequest(
            replay_run_id=run.id,
            action_type=ReplayControlActionType.STEP,
            idempotency_key="step-exactly-one",
            expected_run_version=run.row_version,
        )
    )
    assert run.status is ReplayRunStatus.PAUSED
    assert run.current_session_index == before_step + 1

    run = await service.control(
        ReplayControlRequest(
            replay_run_id=run.id,
            action_type=ReplayControlActionType.STOP,
            idempotency_key="stop-1",
            expected_run_version=run.row_version,
        )
    )
    assert run.status is ReplayRunStatus.STOPPED
    with pytest.raises(ApplicationError) as terminal:
        await service.control(
            ReplayControlRequest(
                replay_run_id=run.id,
                action_type=ReplayControlActionType.STEP,
                idempotency_key="step-after-stop",
                expected_run_version=run.row_version,
            )
        )
    assert terminal.value.code == "REPLAY_TERMINAL_STATE"

    timeline = await ReplayQueryService(factory).events(
        run.id,
        after_sequence=0,
        event_type=None,
        instrument_id=None,
        page=1,
        page_size=1000,
    )
    items = cast(list[dict[str, object]], timeline["items"])
    assert [item["sequence_number"] for item in items] == list(range(1, len(items) + 1))
