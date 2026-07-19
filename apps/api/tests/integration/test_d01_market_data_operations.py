from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.app_factory import create_app
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.market_data_operations import (
    DailyMarketDataUpdateService,
    MarketDataQualityIntegrityService,
    MarketDataQualityService,
    MarketDataReadinessService,
)
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.models import (
    CashLedgerEntryModel,
    FillModel,
    MarketBarModel,
    MarketDataQualityIssueModel,
    MarketDataQualityRunModel,
    OrderModel,
    PositionLedgerEntryModel,
    SignalModel,
)
from alphadesk_domain.enums import MarketDataReadinessStatus, MarketSyncStatus
from alphadesk_domain.market_adapters import ExternalMarketBar, MarketDataAdapterError
from tests.integration.test_d01_historical_market_data import (
    DatabaseStub,
    FakeHistoricalAdapter,
    ProbeStub,
    daily_bars,
    factory,
    seeded,
)


def daily_service(
    session_factory: async_sessionmaker[AsyncSession], *, maximum: int = 500
) -> DailyMarketDataUpdateService:
    return DailyMarketDataUpdateService(
        factory(session_factory),
        default_start_date=date(2025, 1, 1),
        max_instruments=maximum,
        batch_size=2,
        max_retries=2,
        request_interval_seconds=0,
        future_tolerance_seconds=300,
    )


def bar(symbol: str, day: int) -> ExternalMarketBar:
    return ExternalMarketBar(
        symbol=symbol,
        timeframe=daily_bars(symbol)[0].timeframe,
        bar_time=datetime(2025, 1, day, tzinfo=UTC),
        open="10",
        high="12",
        low="9",
        close="11",
        volume="1000",
        amount="10000",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daily_update_dry_run_initial_write_and_idempotent_replay(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    _, _, instruments = await seeded(session_factory, adapter)
    service = daily_service(session_factory)
    async with session_factory() as session:
        before = int(await session.scalar(select(func.count()).select_from(MarketBarModel)) or 0)
    dry_run = await service.update(
        adapter=adapter,
        instruments=instruments,
        universe_key="manual",
        target_date=date(2025, 1, 3),
        continue_on_error=True,
        dry_run=True,
        correlation_id=uuid4(),
    )
    assert dry_run.run is None and dry_run.unprocessed == 2
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MarketBarModel)) == before

    first = await service.update(
        adapter=adapter,
        instruments=instruments,
        universe_key="manual",
        target_date=date(2025, 1, 3),
        continue_on_error=True,
        dry_run=False,
        correlation_id=uuid4(),
    )
    replay = await service.update(
        adapter=adapter,
        instruments=instruments,
        universe_key="manual",
        target_date=date(2025, 1, 3),
        continue_on_error=True,
        dry_run=False,
        correlation_id=uuid4(),
    )
    assert first.completed == 2 and first.bars_inserted == 6
    assert first.run is not None and first.run.status is MarketSyncStatus.SUCCEEDED
    assert replay.idempotent_replay is True and replay.run is not None
    assert replay.run.id == first.run.id
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MarketBarModel)) == before + 6


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daily_update_incremental_retry_partial_and_up_to_date(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    initial = FakeHistoricalAdapter()
    _, backfill, instruments = await seeded(session_factory, initial)
    await backfill.backfill(
        adapter=initial,
        instruments=instruments,
        universe="manual",
        timeframe=daily_bars("699901")[0].timeframe,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=10,
        continue_on_error=True,
        correlation_id=uuid4(),
    )
    bars = {item.symbol: [*daily_bars(item.symbol), bar(item.symbol, 4)] for item in instruments}
    retrying = FakeHistoricalAdapter(
        bars=bars,
        failures_before_success={instruments[0].symbol: 1},
    )
    result = await daily_service(session_factory).update(
        adapter=retrying,
        instruments=instruments,
        universe_key="manual",
        target_date=date(2025, 1, 4),
        continue_on_error=True,
        dry_run=False,
        correlation_id=uuid4(),
    )
    assert result.completed == 2 and result.retry_count == 1
    assert result.bars_inserted == 2 and all(
        plan.start_date == date(2025, 1, 4) for plan in result.plans
    )

    latest = await daily_service(session_factory).update(
        adapter=FakeHistoricalAdapter(bars=bars),
        instruments=instruments,
        universe_key="manual-latest",
        target_date=date(2025, 1, 4),
        continue_on_error=True,
        dry_run=False,
        correlation_id=uuid4(),
    )
    assert latest.up_to_date == 2 and latest.completed == 0 and latest.bars_inserted == 0

    failing = FakeHistoricalAdapter(
        bars={item.symbol: [*bars[item.symbol], bar(item.symbol, 5)] for item in instruments},
        failures_before_success={instruments[0].symbol: 99},
    )
    partial = await daily_service(session_factory).update(
        adapter=failing,
        instruments=instruments,
        universe_key="manual-partial",
        target_date=date(2025, 1, 5),
        continue_on_error=True,
        dry_run=False,
        correlation_id=uuid4(),
    )
    assert partial.failed == 1 and partial.completed == 1
    assert partial.run is not None and partial.run.status is MarketSyncStatus.PARTIALLY_SUCCEEDED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daily_update_rejects_future_and_limits_and_stops_on_global_open_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    _, _, instruments = await seeded(session_factory, adapter)
    with pytest.raises(ApplicationError, match="target_date") as future:
        await daily_service(session_factory).update(
            adapter=adapter,
            instruments=instruments,
            universe_key="manual",
            target_date=date(2099, 1, 1),
            continue_on_error=True,
            dry_run=False,
            correlation_id=uuid4(),
        )
    assert future.value.code == "MARKET_DATA_INVALID_TARGET_DATE"
    with pytest.raises(ApplicationError) as too_many:
        await daily_service(session_factory, maximum=1).update(
            adapter=adapter,
            instruments=instruments,
            universe_key="manual",
            target_date=date(2025, 1, 3),
            continue_on_error=True,
            dry_run=False,
            correlation_id=uuid4(),
        )
    assert too_many.value.code == "MARKET_DATA_TOO_MANY_INSTRUMENTS"

    class LoginFailure(FakeHistoricalAdapter):
        async def open(self) -> None:
            raise MarketDataAdapterError("credentials are intentionally hidden")

    failed = await daily_service(session_factory).update(
        adapter=LoginFailure(),
        instruments=instruments,
        universe_key="login-failure",
        target_date=date(2025, 1, 3),
        continue_on_error=True,
        dry_run=False,
        correlation_id=uuid4(),
    )
    assert failed.failed == 2 and failed.run is not None
    assert failed.run.status is MarketSyncStatus.FAILED
    assert "credentials" not in (failed.run.error_summary or "")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quality_run_persists_statistics_readiness_and_integrity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    _, backfill, instruments = await seeded(session_factory, adapter)
    await backfill.backfill(
        adapter=adapter,
        instruments=instruments,
        universe="manual",
        timeframe=daily_bars("699901")[0].timeframe,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=10,
        continue_on_error=True,
        correlation_id=uuid4(),
    )
    result = await MarketDataQualityService(
        factory(session_factory), stale_calendar_days=7, minimum_bars=5
    ).verify(
        instruments=instruments,
        universe_key="manual",
        provider="baostock",
        correlation_id=uuid4(),
        checked_at=datetime(2025, 1, 20, tzinfo=UTC),
    )
    types = {item.issue_type for item in result.issues}
    assert {"STALE_DATA", "INSUFFICIENT_BARS"}.issubset(types)
    assert result.run.instruments_checked == 2 and result.run.bars_checked == 6
    assert result.run.warning_count == 4 and result.run.issues_found == 4
    assert (
        await MarketDataQualityIntegrityService(factory(session_factory)).verify(result.run.id)
        == ()
    )
    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(MarketDataQualityRunModel)) == 1
        )
        assert (
            await session.scalar(select(func.count()).select_from(MarketDataQualityIssueModel)) == 4
        )

    readiness = await MarketDataReadinessService(
        factory(session_factory), backtest_minimum_bars=3
    ).readiness(instruments=instruments, provider="baostock")
    by_key = {item.capability_key: item for item in readiness}
    assert by_key["backtest_daily"].status is MarketDataReadinessStatus.READY
    assert by_key["strategy_sma_crossover"].status is MarketDataReadinessStatus.NOT_READY


@pytest.mark.integration
@pytest.mark.asyncio
async def test_quality_rules_detect_mapping_ohlc_turnover_duplicate_order_and_future(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    _, _, instruments = await seeded(session_factory, adapter)
    instrument = instruments[0]
    timestamp = datetime(2025, 1, 3, tzinfo=UTC)
    invalid = SimpleNamespace(
        bar_time=timestamp,
        open=Decimal("10"),
        high=Decimal("9"),
        low=Decimal("11"),
        close=Decimal("10"),
        volume=Decimal("-1"),
        amount=Decimal("-1"),
    )
    service = MarketDataQualityService(
        factory(session_factory), stale_calendar_days=7, minimum_bars=2
    )
    issues = service._instrument_issues(
        uuid4(),
        instrument,
        None,
        [],
        [invalid, invalid],
        datetime(2025, 1, 2, tzinfo=UTC),
    )
    issue_types = {item.issue_type for item in issues}
    assert {
        "MAPPING_MISSING",
        "DUPLICATE_BAR",
        "TIME_ORDER_INVALID",
        "FUTURE_BAR",
        "OHLC_INVALID",
        "NEGATIVE_TURNOVER",
    }.issubset(issue_types)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_daily_update_and_quality_api_are_real_database_flows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    universes, _, instruments = await seeded(session_factory, adapter)
    await universes.create_research_universe(correlation_id=uuid4(), limit=2)
    instrument_ids = [str(item.id) for item in instruments]
    app = create_app(
        Settings(
            environment="test",
            market_daily_default_start_date=date(2025, 1, 1),
            market_data_backtest_minimum_bars=20,
            market_backfill_request_interval_seconds=0,
        ),
        database=DatabaseStub(session_factory),
        redis_service=ProbeStub(),
    )
    app.state.historical_market_adapter_factory = lambda: adapter
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        dry = await client.post(
            "/api/v1/market-data/daily-updates",
            json={
                "target_date": "2025-01-03",
                "instrument_ids": instrument_ids,
                "max_instruments": 2,
                "dry_run": True,
            },
        )
        assert dry.status_code == 200 and dry.json()["dry_run"] is True
        assert dry.headers["x-correlation-id"]
        update = await client.post(
            "/api/v1/market-data/daily-updates",
            json={
                "target_date": "2025-01-03",
                "instrument_ids": instrument_ids,
                "max_instruments": 2,
                "dry_run": False,
            },
        )
        assert update.status_code == 200 and update.json()["bars_inserted"] == 6
        quality = await client.post(
            "/api/v1/market-data/quality-runs",
            json={"provider": "baostock", "universe_key": "research", "max_instruments": 2},
        )
        assert quality.status_code == 200
        run_id = quality.json()["run"]["id"]
        detail = await client.get(
            f"/api/v1/market-data/quality-runs/{run_id}?severity=WARNING&page=1&page_size=1"
        )
        assert detail.status_code == 200 and detail.json()["issue_page_size"] == 1
        for path in ("overview", "coverage", "readiness", "sync-runs"):
            response = await client.get(f"/api/v1/market-data/{path}")
            assert response.status_code == 200, response.text
        missing = await client.get(f"/api/v1/market-data/quality-runs/{uuid4()}")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "MARKET_DATA_QUALITY_RUN_NOT_FOUND"
        assert not any(
            getattr(route, "path", None) == "/api/v1/market-data/bars"
            and "POST" in getattr(route, "methods", set())
            for route in app.routes
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_d01_operations_do_not_mutate_trading_facts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    guarded = (
        SignalModel,
        OrderModel,
        FillModel,
        CashLedgerEntryModel,
        PositionLedgerEntryModel,
    )
    async with session_factory() as session:
        before = {
            model.__tablename__: int(
                await session.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in guarded
        }
    adapter = FakeHistoricalAdapter()
    _, _, instruments = await seeded(session_factory, adapter)
    await daily_service(session_factory).update(
        adapter=adapter,
        instruments=instruments,
        universe_key="guarded",
        target_date=date(2025, 1, 3),
        continue_on_error=True,
        dry_run=False,
        correlation_id=uuid4(),
    )
    await MarketDataQualityService(
        factory(session_factory), stale_calendar_days=7, minimum_bars=3
    ).verify(
        instruments=instruments,
        universe_key="guarded",
        provider="baostock",
        correlation_id=uuid4(),
        checked_at=datetime(2025, 1, 3, tzinfo=UTC),
    )
    async with session_factory() as session:
        for model in guarded:
            assert (
                await session.scalar(select(func.count()).select_from(model))
                == before[model.__tablename__]
            )
