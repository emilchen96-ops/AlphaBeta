from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.strategy_runner import StrategyRunRequest
from alphadesk_api.infrastructure.models import (
    AccountCashBalanceModel,
    FillModel,
    OrderModel,
    PositionModel,
    SignalModel,
)
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.strategy_runs import StrategyRunStatus
from tests.integration.test_s01_strategy_runner import NOW, runner, seed_history


@pytest.mark.integration
@pytest.mark.s01
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy_key", "parameters", "closes", "volumes"),
    [
        (
            "volume_breakout",
            {
                "breakout_window": 3,
                "volume_window": 2,
                "exit_window": 2,
                "volume_multiplier": Decimal("1.5"),
                "quantity": Decimal("100"),
            },
            ("10", "10.5", "11", "12", "12.5", "8"),
            ("100", "100", "100", "200", "250", "100"),
        ),
        (
            "trend_pullback",
            {
                "fast_ema": 2,
                "slow_ema": 3,
                "pullback_window": 3,
                "pullback_tolerance": Decimal("0"),
                "quantity": Decimal("100"),
            },
            ("10", "11", "12", "11", "13", "14", "8", "7"),
            ("100",) * 8,
        ),
        (
            "atr_channel",
            {
                "ema_window": 2,
                "atr_window": 2,
                "entry_atr_multiplier": Decimal("0.2"),
                "exit_atr_multiplier": Decimal("0.2"),
                "quantity": Decimal("100"),
            },
            ("10", "10", "10", "14", "15", "7"),
            ("100",) * 6,
        ),
    ],
)
async def test_s02_strategies_use_existing_persistence_without_trading_side_effects(
    session_factory: async_sessionmaker[AsyncSession],
    strategy_key: str,
    parameters: dict,
    closes: tuple[str, ...],
    volumes: tuple[str, ...],
) -> None:
    instrument = await seed_history(session_factory, closes=closes, volumes=volumes)
    protected_models = (OrderModel, FillModel, AccountCashBalanceModel, PositionModel)
    async with session_factory() as session:
        before = [
            await session.scalar(select(func.count()).select_from(model))
            for model in protected_models
        ]
    service = runner(session_factory)

    async def execute(key: str):
        return await service.run(
            StrategyRunRequest(
                idempotency_key=key,
                strategy_key=strategy_key,
                timeframe=MarketTimeframe.MINUTE_1,
                start_at=NOW,
                end_at=NOW + timedelta(minutes=len(closes)),
                instrument_ids=(instrument.id,),
                parameters=parameters,
            )
        )

    first = await execute(f"s02-{strategy_key}-{uuid4()}")
    second = await execute(f"s02-repeat-{strategy_key}-{uuid4()}")
    assert first.run.status is second.run.status is StrategyRunStatus.COMPLETED
    assert first.run.signals_generated == second.run.signals_generated
    assert first.run.signals_generated > 0
    comparable_first = [
        (item.side, item.signal_type, item.bar_timestamp, item.reference_price, item.reason)
        for item in first.signals
    ]
    comparable_second = [
        (item.side, item.signal_type, item.bar_timestamp, item.reference_price, item.reason)
        for item in second.signals
    ]
    assert comparable_first == comparable_second

    async with session_factory() as session:
        for result in (first, second):
            persisted = await session.scalar(
                select(func.count())
                .select_from(SignalModel)
                .where(SignalModel.strategy_run_id == result.run.id)
            )
            assert persisted == result.run.signals_generated
        after = [
            await session.scalar(select(func.count()).select_from(model))
            for model in protected_models
        ]
        assert after == before
