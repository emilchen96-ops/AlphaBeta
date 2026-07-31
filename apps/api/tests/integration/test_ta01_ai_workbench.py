from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.ai_workbench import (
    AIResearchTaskProcessor,
    AIResearchWorkbenchService,
    CreateResearchTaskRequest,
)
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.infrastructure.ai_workbench_provider import FakeWorkbenchProvider
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.ai_workbench import ResearchDepth, ResearchTaskStatus
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketTimeframe,
)
from alphadesk_domain.market import MarketBar, MarketDataSource

pytestmark = [pytest.mark.integration, pytest.mark.a01]


@pytest.mark.asyncio
async def test_task_worker_report_and_idempotency_survive_separate_uow_sessions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))
    instrument = Instrument(
        symbol=f"T{uuid4().hex[:7]}",
        exchange="SZSE",
        market="CN_A",
        name="长信科技 TA01",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
    )
    async with factory() as uow:
        source = await uow.market_data_sources.get_by_code("MINIQMT")
        if source is None:
            source = MarketDataSource(
                source_code="MINIQMT",
                name="MiniQMT 只读行情",
                status=MarketDataSourceStatus.ACTIVE,
                priority=0,
                supports_realtime=True,
                supported_timeframes=(MarketTimeframe.DAY_1,),
                provider_tier=MarketProviderTier.DEMO,
            )
            await uow.market_data_sources.add(source)
        await uow.instruments.add(instrument)
        start = datetime(2026, 4, 1, tzinfo=UTC)
        await uow.market_bars.upsert_many(
            [
                MarketBar(
                    instrument_id=instrument.id,
                    source_id=source.id,
                    timeframe=MarketTimeframe.DAY_1,
                    adjustment_type=AdjustmentType.NONE,
                    bar_time=start + timedelta(days=index),
                    open=Decimal("10") + Decimal(index) / 100,
                    high=Decimal("10.5") + Decimal(index) / 100,
                    low=Decimal("9.5") + Decimal(index) / 100,
                    close=Decimal("10.2") + Decimal(index) / 100,
                    volume=Decimal("100000"),
                    amount=Decimal("1020000"),
                    received_at=start + timedelta(days=index),
                    quality_status=MarketDataQualityStatus.NORMAL,
                )
                for index in range(20)
            ]
        )
        await uow.commit()

    provider = FakeWorkbenchProvider()
    service = AIResearchWorkbenchService(factory, provider)
    request = CreateResearchTaskRequest(
        instrument_id=instrument.id,
        question="分析当前基本面、技术面和主要风险",
        depth=ResearchDepth.STANDARD,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 30),
        idempotency_key=f"ta01-{uuid4()}",
        correlation_id=uuid4(),
    )
    created = await service.create(request)
    replayed = await service.create(request)
    assert replayed.id == created.id

    processor = AIResearchTaskProcessor(factory, provider, stale_seconds=0)
    assert await processor.run_once() == created.id
    detail = await service.get(created.id)
    assert detail.task.status is ResearchTaskStatus.COMPLETED
    assert detail.report is not None
    assert len(detail.report.sections) == 10
    assert all(step.status.value == "COMPLETED" for step in detail.steps)
    assert "Fake Provider" in detail.report.markdown
