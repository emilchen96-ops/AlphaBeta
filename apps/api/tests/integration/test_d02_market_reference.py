from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.models import (
    AdjustmentFactorModel,
    CashLedgerEntryModel,
    FillModel,
    InstrumentLifecycleEventModel,
    InstrumentModel,
    InstrumentTradingStatusModel,
    OrderModel,
    PositionLedgerEntryModel,
    SignalModel,
    TradingCalendarSessionModel,
)
from tests.integration.test_d01_historical_market_data import (
    DatabaseStub,
    FakeHistoricalAdapter,
    ProbeStub,
    seeded,
)
from tests.integration.test_d01_market_data_operations import daily_service


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fixture_sync_query_qfq_and_trading_fact_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    _, backfill, instruments = await seeded(session_factory, adapter)
    await backfill.backfill(
        adapter=adapter,
        instruments=instruments,
        universe="manual",
        timeframe=adapter.bars[instruments[0].symbol][0].timeframe,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=10,
        continue_on_error=True,
        correlation_id=uuid4(),
    )
    guarded = (SignalModel, OrderModel, FillModel, CashLedgerEntryModel, PositionLedgerEntryModel)
    async with session_factory() as session:
        before = {
            model.__tablename__: int(
                await session.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in guarded
        }

    app = create_app(
        Settings(environment="test"),
        database=DatabaseStub(session_factory),
        redis_service=ProbeStub(),
    )
    instrument_ids = [str(item.id) for item in instruments]
    common = {
        "start": "2025-01-01",
        "end": "2025-01-04",
        "instrument_ids": instrument_ids,
        "max_instruments": 2,
        "provider": "fixture",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        dry = await client.post(
            "/api/v1/market-reference/calendar/sync", json={**common, "dry_run": True}
        )
        assert dry.status_code == 200 and dry.json()["persisted"] == 0

        first = await client.post(
            "/api/v1/market-reference/calendar/sync", json={**common, "dry_run": False}
        )
        second = await client.post(
            "/api/v1/market-reference/calendar/sync", json={**common, "dry_run": False}
        )
        assert first.status_code == second.status_code == 200
        for resource in ("adjustments", "suspensions", "instrument-lifecycle"):
            response = await client.post(
                f"/api/v1/market-reference/{resource}/sync",
                json={
                    **common,
                    "start": "2025-01-02",
                    "end": "2025-01-03",
                    "dry_run": False,
                },
            )
            assert response.status_code == 200, response.text

        calendar = await client.get(
            "/api/v1/market-reference/calendar",
            params={"exchange": "SHSE", "start": "2025-01-01", "end": "2025-01-03"},
        )
        assert calendar.status_code == 200 and len(calendar.json()) == 3
        status = await client.get("/api/v1/market-reference/status")
        assert status.status_code == 200
        assert status.json()["calendar_provider"] == "FIXTURE"
        assert status.json()["adjusted_price_ready"] is True
        qfq = await client.get(
            "/api/v1/market-data/bars",
            params={
                "instrument_id": instrument_ids[0],
                "source_code": "BAOSTOCK",
                "start": "2025-01-02T00:00:00Z",
                "end": "2025-01-03T23:59:59Z",
                "adjustment_mode": "QFQ",
            },
        )
        assert qfq.status_code == 200, qfq.text
        assert len(qfq.json()["items"]) == 2
        assert all(item["adjustment_mode"] == "QFQ" for item in qfq.json()["items"])

    closed_adapter = FakeHistoricalAdapter()
    closed = await daily_service(session_factory).update(
        adapter=closed_adapter,
        instruments=instruments,
        universe_key="d02-closed-session",
        target_date=date(2025, 1, 4),
        continue_on_error=True,
        dry_run=False,
        correlation_id=uuid4(),
    )
    assert closed.up_to_date == 2 and not closed_adapter.attempts
    assert closed.run is not None and closed.run.metadata["closed_market"] == 1

    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(TradingCalendarSessionModel)) == 8
        )
        assert await session.scalar(select(func.count()).select_from(AdjustmentFactorModel)) == 4
        assert (
            await session.scalar(select(func.count()).select_from(InstrumentTradingStatusModel))
            == 4
        )
        assert (
            await session.scalar(select(func.count()).select_from(InstrumentLifecycleEventModel))
            == 2
        )
        lifecycle = list((await session.scalars(select(InstrumentModel))).all())
        assert all(
            item.listed_at == date(1990, 1, 1)
            for item in lifecycle
            if item.id in {value.id for value in instruments}
        )
        after = {
            model.__tablename__: int(
                await session.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in guarded
        }
    assert after == before
