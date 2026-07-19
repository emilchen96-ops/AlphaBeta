from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.app_factory import create_app
from alphadesk_api.application.catalog import InstrumentCatalogService
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.market_data import MarketDataIngestionService
from alphadesk_api.application.watchlists import WatchlistService
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.market_data import DemoCsvMarketDataAdapter
from alphadesk_api.infrastructure.models import (
    AuditLogModel,
    DomainEventModel,
    MarketBarModel,
    OutboxMessageModel,
)
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataSourceStatus,
    MarketSyncStatus,
    MarketTimeframe,
    SyncTriggerType,
)


class DatabaseStub:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.factory)


class ProbeStub:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def services(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[InstrumentCatalogService, MarketDataIngestionService, WatchlistService]:
    uow_factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(factory))
    return (
        InstrumentCatalogService(uow_factory),
        MarketDataIngestionService(uow_factory, batch_size=200),
        WatchlistService(uow_factory),
    )


async def seed_demo(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[InstrumentCatalogService, MarketDataIngestionService]:
    catalog, ingestion, _ = services(factory)
    adapter = DemoCsvMarketDataAdapter()
    await catalog.ensure_source(
        source_code="DEMO",
        name="Integration Demo",
        status=MarketDataSourceStatus.ACTIVE,
        priority=0,
        supports_realtime=False,
        supported_timeframes=(MarketTimeframe.DAY_1, MarketTimeframe.MINUTE_1),
    )
    assert await catalog.import_from_adapter(adapter, uuid4()) == (3, 3)
    return catalog, ingestion


@pytest.mark.integration
@pytest.mark.asyncio
async def test_demo_ingestion_is_idempotent_audited_and_has_no_outbox_publication(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        outbox_before = await session.scalar(select(func.count()).select_from(OutboxMessageModel))
    catalog, ingestion = await seed_demo(session_factory)
    del catalog
    adapter = DemoCsvMarketDataAdapter()
    arguments = {
        "adapter": adapter,
        "symbols": ["600000", "000001", "510300"],
        "timeframe": MarketTimeframe.DAY_1,
        "adjustment": AdjustmentType.NONE,
        "start": datetime(2025, 1, 1, tzinfo=UTC),
        "end": datetime(2025, 12, 31, tzinfo=UTC),
        "trigger_type": SyncTriggerType.CLI,
    }
    first = await ingestion.sync_bars(**arguments, correlation_id=uuid4())
    second = await ingestion.sync_bars(**arguments, correlation_id=uuid4())
    assert first.status is MarketSyncStatus.SUCCEEDED
    assert first.total_inserted == 540
    assert second.total_inserted == 0
    assert second.total_updated == 0
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MarketBarModel)) == 540
        assert await session.scalar(select(func.count()).select_from(DomainEventModel)) >= 7
        assert await session.scalar(select(func.count()).select_from(AuditLogModel)) >= 7
        outbox_after = await session.scalar(select(func.count()).select_from(OutboxMessageModel))
        assert outbox_after == outbox_before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_watchlist_and_market_read_api_business_loop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    catalog, ingestion, watchlists = services(session_factory)
    adapter = DemoCsvMarketDataAdapter()
    await catalog.ensure_source(
        source_code="DEMO",
        name="API Demo",
        status=MarketDataSourceStatus.ACTIVE,
        priority=0,
        supports_realtime=False,
        supported_timeframes=(MarketTimeframe.DAY_1, MarketTimeframe.MINUTE_1),
    )
    await catalog.import_from_adapter(adapter, uuid4())
    instruments, total = await catalog.search(
        keyword="600000",
        exchange=None,
        market=None,
        asset_type=None,
        is_active=True,
        page=1,
        page_size=10,
    )
    assert total == 1
    watchlist = await watchlists.create(name="API观察", description=None, correlation_id=uuid4())
    item = await watchlists.add_item(
        watchlist.id,
        instrument_id=instruments[0].id,
        note="核心",
        correlation_id=uuid4(),
    )
    await watchlists.update_item(watchlist.id, item.id, note="已更新", correlation_id=uuid4())
    await ingestion.sync_bars(
        adapter=adapter,
        symbols=["600000"],
        timeframe=MarketTimeframe.DAY_1,
        adjustment=AdjustmentType.NONE,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 2, 1, tzinfo=UTC),
        trigger_type=SyncTriggerType.MANUAL,
        correlation_id=uuid4(),
    )

    app = create_app(
        Settings(environment="test"),
        database=DatabaseStub(session_factory),
        redis_service=ProbeStub(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        instrument_response = await client.get("/api/v1/instruments", params={"keyword": "600000"})
        assert instrument_response.status_code == 200
        assert instrument_response.json()["total"] == 1
        watchlist_response = await client.get(f"/api/v1/watchlists/{watchlist.id}")
        assert watchlist_response.status_code == 200
        assert watchlist_response.json()["items"][0]["note"] == "已更新"
        bars_response = await client.get(
            "/api/v1/market-data/bars",
            params={
                "instrument_id": str(instruments[0].id),
                "timeframe": "DAY_1",
                "start": "2025-01-01T00:00:00Z",
                "end": "2025-02-01T00:00:00Z",
            },
        )
        assert bars_response.status_code == 200
        assert len(bars_response.json()["items"]) == 32
        assert bars_response.json()["source_code"] == "DEMO"
        bad_range = await client.get(
            "/api/v1/market-data/bars",
            params={
                "instrument_id": str(instruments[0].id),
                "start": "2025-02-01T00:00:00Z",
                "end": "2025-01-01T00:00:00Z",
            },
        )
        assert bad_range.status_code == 422
        assert bad_range.json()["error"]["code"] == "MARKET_DATA_INVALID_RANGE"
