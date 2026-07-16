from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.strategy_runner import StrategyRunner, StrategyRunRequest
from alphadesk_api.infrastructure.models import (
    AccountCashBalanceModel,
    FillModel,
    OrderModel,
    PositionModel,
    SignalModel,
    StrategyRunModel,
)
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketTimeframe,
)
from alphadesk_domain.market import MarketBar, MarketDataSource
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies
from alphadesk_domain.strategy_runs import StrategyRunStatus

NOW = datetime(2026, 2, 2, 1, tzinfo=UTC)


async def seed_history(
    factory: async_sessionmaker[AsyncSession], *, duplicate_source: bool = False
) -> Instrument:
    instrument = Instrument(
        symbol=f"T{uuid4().hex[:7]}",
        exchange="SZSE",
        market="CN",
        name="S01 test",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
    )
    source = MarketDataSource(
        source_code=f"S{uuid4().hex[:7]}",
        name="S01 source",
        status=MarketDataSourceStatus.ACTIVE,
        priority=0,
        supports_realtime=False,
        supported_timeframes=(MarketTimeframe.MINUTE_1,),
        provider_tier=MarketProviderTier.DEMO,
    )
    uow_factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(factory))
    async with uow_factory() as uow:
        await uow.instruments.add(instrument)
        await uow.market_data_sources.add(source)
        bars = [
            MarketBar(
                instrument_id=instrument.id,
                source_id=source.id,
                timeframe=MarketTimeframe.MINUTE_1,
                adjustment_type=AdjustmentType.NONE,
                bar_time=NOW + timedelta(minutes=index),
                open=Decimal("10"),
                high=Decimal("11"),
                low=Decimal("9"),
                close=Decimal("10") + Decimal(index) / Decimal("10"),
                volume=Decimal("1000"),
                received_at=NOW + timedelta(minutes=index),
                quality_status=MarketDataQualityStatus.NORMAL,
            )
            for index in range(8)
        ]
        await uow.market_bars.upsert_many(bars)
        if duplicate_source:
            duplicate = MarketDataSource(
                source_code=f"D{uuid4().hex[:7]}",
                name="duplicate source",
                status=MarketDataSourceStatus.ACTIVE,
                priority=1,
                supports_realtime=False,
                supported_timeframes=(MarketTimeframe.MINUTE_1,),
            )
            await uow.market_data_sources.add(duplicate)
            await uow.market_bars.upsert_many(
                [
                    MarketBar(
                        instrument_id=instrument.id,
                        source_id=duplicate.id,
                        timeframe=MarketTimeframe.MINUTE_1,
                        adjustment_type=AdjustmentType.NONE,
                        bar_time=NOW,
                        open=Decimal("10"),
                        high=Decimal("11"),
                        low=Decimal("9"),
                        close=Decimal("10"),
                        volume=Decimal("1"),
                        received_at=NOW,
                        quality_status=MarketDataQualityStatus.NORMAL,
                    )
                ]
            )
        await uow.commit()
    return instrument


def runner(factory: async_sessionmaker[AsyncSession]) -> StrategyRunner:
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    return StrategyRunner(cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(factory)), registry)


@pytest.mark.integration
@pytest.mark.s01
@pytest.mark.asyncio
async def test_historical_run_persists_idempotently_without_trading_side_effects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    instrument = await seed_history(session_factory)
    fact_models = (OrderModel, FillModel, AccountCashBalanceModel, PositionModel)
    async with session_factory() as session:
        before = [
            await session.scalar(select(func.count()).select_from(model)) for model in fact_models
        ]
    service = runner(session_factory)
    run_request = StrategyRunRequest(
        idempotency_key=f"s01-{uuid4()}",
        strategy_key="sma_crossover",
        timeframe=MarketTimeframe.MINUTE_1,
        start_at=NOW,
        end_at=NOW + timedelta(minutes=8),
        instrument_ids=(instrument.id,),
        parameters={"short_window": 2, "long_window": 3, "quantity": Decimal("100")},
    )
    first = await service.run(run_request)
    second = await service.run(run_request)
    assert first.run.status is StrategyRunStatus.COMPLETED
    assert first.run.bars_processed == 8
    assert second.replayed and second.run.id == first.run.id

    async with session_factory() as session:
        run_count = await session.scalar(select(func.count()).select_from(StrategyRunModel))
        assert (run_count or 0) >= 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SignalModel)
                .where(SignalModel.strategy_run_id == first.run.id)
            )
            == first.run.signals_generated
        )
        after = [
            await session.scalar(select(func.count()).select_from(model)) for model in fact_models
        ]
        assert after == before


@pytest.mark.integration
@pytest.mark.s01
@pytest.mark.asyncio
async def test_ambiguous_historical_bar_rolls_back_and_records_failed_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    instrument = await seed_history(session_factory, duplicate_source=True)
    result = await runner(session_factory).run(
        StrategyRunRequest(
            idempotency_key=f"s01-duplicate-{uuid4()}",
            strategy_key="sma_crossover",
            timeframe=MarketTimeframe.MINUTE_1,
            start_at=NOW,
            end_at=NOW + timedelta(minutes=8),
            instrument_ids=(instrument.id,),
            parameters={"short_window": 2, "long_window": 3, "quantity": Decimal("100")},
        )
    )
    assert result.run.status is StrategyRunStatus.FAILED
    assert result.run.error_code == "STRATEGY_INVALID_BAR"
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SignalModel)
                .where(SignalModel.strategy_run_id == result.run.id)
            )
            == 0
        )
