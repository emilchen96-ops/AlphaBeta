from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.scanners import ScannerRunRequest, ScannerRunService
from alphadesk_api.infrastructure.models import (
    AccountCashBalanceModel,
    FillModel,
    OrderModel,
    PositionModel,
    RiskDecisionModel,
    ScanResultModel,
    ScanRunModel,
    SignalModel,
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
from alphadesk_domain.scanners import (
    ScannerRegistry,
    ScanResult,
    ScanRunStatus,
    register_builtin_scanners,
)

NOW = datetime(2026, 3, 20, tzinfo=UTC)


async def seed_daily_history(factory: async_sessionmaker[AsyncSession]) -> Instrument:
    instrument = Instrument(
        symbol=f"T{uuid4().hex[:7]}",
        exchange="SSE",
        market="CN",
        name="SC01 test",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
    )
    source = MarketDataSource(
        source_code=f"C{uuid4().hex[:7]}",
        name="SC01 source",
        status=MarketDataSourceStatus.ACTIVE,
        priority=0,
        supports_realtime=False,
        supported_timeframes=(MarketTimeframe.DAY_1,),
        provider_tier=MarketProviderTier.DEMO,
    )
    uow_factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(factory))
    async with uow_factory() as uow:
        await uow.instruments.add(instrument)
        await uow.market_data_sources.add(source)
        await uow.market_bars.upsert_many(
            [
                MarketBar(
                    instrument_id=instrument.id,
                    source_id=source.id,
                    timeframe=MarketTimeframe.DAY_1,
                    adjustment_type=AdjustmentType.NONE,
                    bar_time=NOW - timedelta(days=2 - index),
                    open=Decimal("10"),
                    high=Decimal("10.2"),
                    low=Decimal("9.8"),
                    close=Decimal("10"),
                    volume=Decimal(volume),
                    amount=Decimal("10") * Decimal(volume),
                    received_at=NOW - timedelta(days=2 - index),
                    quality_status=MarketDataQualityStatus.NORMAL,
                )
                for index, volume in enumerate(("100", "100", "400"))
            ]
        )
        await uow.commit()
    return instrument


def service(factory: async_sessionmaker[AsyncSession]) -> ScannerRunService:
    registry = ScannerRegistry()
    register_builtin_scanners(registry)
    return ScannerRunService(
        cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(factory)), registry
    )


@pytest.mark.integration
@pytest.mark.sc01
@pytest.mark.asyncio
async def test_scan_persists_idempotently_without_trading_side_effects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    instrument = await seed_daily_history(session_factory)
    protected_models = (
        SignalModel,
        RiskDecisionModel,
        OrderModel,
        FillModel,
        AccountCashBalanceModel,
        PositionModel,
    )
    async with session_factory() as session:
        before = [
            await session.scalar(select(func.count()).select_from(model))
            for model in protected_models
        ]
    request = ScannerRunRequest(
        scanner_key="volume_anomaly",
        parameters={"volume_window": 2, "minimum_volume_ratio": Decimal("2")},
        instrument_ids=(instrument.id,),
        timeframe=MarketTimeframe.DAY_1,
        as_of=NOW,
        idempotency_key=f"sc01-{uuid4()}",
        correlation_id=uuid4(),
    )
    first = await service(session_factory).run(request)
    second = await service(session_factory).run(request)
    assert first.run.status is ScanRunStatus.COMPLETED
    assert first.run.matches_found == first.run.instruments_scanned == 1
    assert second.replayed and second.run.id == first.run.id

    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ScanRunModel)
                .where(ScanRunModel.id == first.run.id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ScanResultModel)
                .where(ScanResultModel.scan_run_id == first.run.id)
            )
            == 1
        )
        after = [
            await session.scalar(select(func.count()).select_from(model))
            for model in protected_models
        ]
        assert after == before


@pytest.mark.integration
@pytest.mark.sc01
@pytest.mark.asyncio
async def test_scan_result_run_instrument_is_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    instrument = await seed_daily_history(session_factory)
    outcome = await service(session_factory).run(
        ScannerRunRequest(
            scanner_key="volume_anomaly",
            parameters={"volume_window": 2},
            instrument_ids=(instrument.id,),
            timeframe=MarketTimeframe.DAY_1,
            as_of=NOW,
            idempotency_key=f"sc01-unique-{uuid4()}",
            correlation_id=uuid4(),
        )
    )
    original = outcome.results[0]
    duplicate = ScanResult(
        scan_run_id=outcome.run.id,
        instrument_id=instrument.id,
        rank=2,
        score=original.score,
        matched_at=original.matched_at,
        reference_price=original.reference_price,
        reason_code=original.reason_code,
        reason=original.reason,
        metrics=original.metrics,
    )
    uow_factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))
    with pytest.raises(IntegrityError):
        async with uow_factory() as uow:
            await uow.scan_results.append_many([duplicate])
            await uow.commit()
