from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.app_factory import create_app
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.historical_market_data import (
    HistoricalMarketDataBackfillService,
    InstrumentUniverseSyncService,
)
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.models import (
    CashLedgerEntryModel,
    FillModel,
    InstrumentMappingModel,
    InstrumentModel,
    MarketBarModel,
    OrderModel,
    PositionLedgerEntryModel,
    SignalModel,
    WatchlistItemModel,
    WatchlistModel,
)
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketSyncStatus,
    MarketTimeframe,
)
from alphadesk_domain.market_adapters import (
    ExternalInstrument,
    ExternalMarketBar,
    MarketDataAdapterError,
    MarketDataHealth,
)


class ProbeStub:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class DatabaseStub:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.factory)


class FakeHistoricalAdapter:
    source_code = "BAOSTOCK"

    def __init__(
        self,
        *,
        instruments: list[ExternalInstrument] | None = None,
        bars: dict[str, list[ExternalMarketBar]] | None = None,
        failures_before_success: dict[str, int] | None = None,
    ) -> None:
        self.instruments = instruments or external_instruments()
        self.bars = bars or {item.symbol: daily_bars(item.symbol) for item in self.instruments}
        self.failures_before_success = failures_before_success or {}
        self.attempts: dict[str, int] = {}

    async def health_check(self) -> MarketDataHealth:
        raise NotImplementedError

    async def list_instruments(
        self, exchange: str | None = None, market: str | None = None
    ) -> list[ExternalInstrument]:
        return [
            item
            for item in self.instruments
            if (exchange is None or item.exchange == exchange)
            and (market is None or item.market == market)
        ]

    async def fetch_bars(
        self,
        symbols: list[str],
        timeframe: MarketTimeframe,
        start: datetime,
        end: datetime,
        adjustment: AdjustmentType,
    ) -> AsyncIterator[ExternalMarketBar]:
        del timeframe, adjustment
        symbol = symbols[0]
        self.attempts[symbol] = self.attempts.get(symbol, 0) + 1
        if self.attempts[symbol] <= self.failures_before_success.get(symbol, 0):
            raise MarketDataAdapterError("controlled fake failure")
        for item in self.bars.get(symbol, []):
            if start <= item.bar_time <= end:
                yield item


def external_instruments() -> list[ExternalInstrument]:
    return [
        ExternalInstrument(
            symbol="699901",
            exchange="SSE",
            market="CN_A",
            name="浦发银行",
            asset_type="STOCK",
            currency="CNY",
            lot_size="100",
            price_tick="0.01",
            timezone="Asia/Shanghai",
        ),
        ExternalInstrument(
            symbol="399901",
            exchange="SZSE",
            market="CN_A",
            name="平安银行",
            asset_type="STOCK",
            currency="CNY",
            lot_size="100",
            price_tick="0.01",
            timezone="Asia/Shanghai",
        ),
        ExternalInstrument(
            symbol="399902",
            exchange="SZSE",
            market="CN_A",
            name="特锐德",
            asset_type="STOCK",
            currency="CNY",
            lot_size="100",
            price_tick="0.01",
            timezone="Asia/Shanghai",
            is_active=False,
        ),
    ]


def daily_bars(symbol: str) -> list[ExternalMarketBar]:
    return [
        ExternalMarketBar(
            symbol=symbol,
            timeframe=MarketTimeframe.DAY_1,
            bar_time=datetime(2025, 1, day, tzinfo=UTC),
            open=str(10 + day / 10),
            high=str(11 + day / 10),
            low=str(9 + day / 10),
            close=str(10.5 + day / 10),
            volume=str(1000 * day),
            amount=str(10000 * day),
        )
        for day in range(1, 4)
    ]


def factory(session_factory: async_sessionmaker[AsyncSession]) -> UnitOfWorkFactory:
    return cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))


async def seeded(
    session_factory: async_sessionmaker[AsyncSession], adapter: FakeHistoricalAdapter
) -> tuple[InstrumentUniverseSyncService, HistoricalMarketDataBackfillService, list[Instrument]]:
    universes = InstrumentUniverseSyncService(factory(session_factory))
    await universes.sync_instruments(adapter=adapter, correlation_id=uuid4())
    instruments = await universes.resolve_universe(
        universe="manual", limit=500, symbols={"699901", "399901"}
    )
    return universes, HistoricalMarketDataBackfillService(factory(session_factory)), instruments


@pytest.mark.integration
@pytest.mark.asyncio
async def test_instrument_sync_is_filtered_mapped_active_and_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    universes = InstrumentUniverseSyncService(factory(session_factory))
    async with session_factory() as session:
        instruments_before = int(
            await session.scalar(select(func.count()).select_from(InstrumentModel)) or 0
        )
        mappings_before = int(
            await session.scalar(select(func.count()).select_from(InstrumentMappingModel)) or 0
        )
    first = await universes.sync_instruments(adapter=adapter, correlation_id=uuid4())
    second = await universes.sync_instruments(adapter=adapter, correlation_id=uuid4())
    assert first.selected_count == 3
    assert first.active_count == 2 and first.inactive_count == 1
    assert second.instrument_count == 3 and second.mapping_count == 3
    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(InstrumentModel))
            == instruments_before + 3
        )
        assert (
            await session.scalar(select(func.count()).select_from(InstrumentMappingModel))
            == mappings_before + 3
        )
        inactive = await session.scalar(
            select(InstrumentModel).where(InstrumentModel.symbol == "399902")
        )
        assert inactive is not None and inactive.is_active is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_instrument_sync_dry_run_and_limit_do_not_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        before = await session.scalar(select(func.count()).select_from(InstrumentModel))
    result = await InstrumentUniverseSyncService(factory(session_factory)).sync_instruments(
        adapter=FakeHistoricalAdapter(), correlation_id=uuid4(), limit=1, dry_run=True
    )
    assert result.selected_count == 1 and result.instrument_count == 0
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(InstrumentModel)) == before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_research_universe_is_bounded_code_selectable_and_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    universes, _, _ = await seeded(session_factory, FakeHistoricalAdapter())
    first = await universes.create_research_universe(
        correlation_id=uuid4(), limit=2, symbols={"699901", "sz.399901"}
    )
    second = await universes.create_research_universe(
        correlation_id=uuid4(), limit=2, symbols={"699901", "399901"}
    )
    assert second.created is False
    assert set(first.symbols) == {"699901", "399901"}
    async with session_factory() as session:
        watchlist = await session.scalar(
            select(WatchlistModel).where(WatchlistModel.name == "D01 Research Universe")
        )
        assert watchlist is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WatchlistItemModel)
                .where(WatchlistItemModel.watchlist_id == watchlist.id)
            )
            == 2
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_research_universe_rejects_inactive_or_unknown_symbols(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    universes, _, _ = await seeded(session_factory, FakeHistoricalAdapter())
    with pytest.raises(ApplicationError) as captured:
        await universes.create_research_universe(
            correlation_id=uuid4(), limit=2, symbols={"399902", "999999"}
        )
    assert captured.value.code == "D01_UNIVERSE_SYMBOL_NOT_FOUND"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_persists_decimal_daily_bars_and_repeat_skips(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    _, service, instruments = await seeded(session_factory, adapter)
    request = {
        "adapter": adapter,
        "instruments": instruments,
        "universe": "all_active_a_share",
        "timeframe": MarketTimeframe.DAY_1,
        "start": datetime(2025, 1, 1, tzinfo=UTC),
        "end": datetime(2025, 1, 3, tzinfo=UTC),
        "batch_size": 2,
        "continue_on_error": True,
    }
    first = await service.backfill(**request, correlation_id=uuid4())
    second = await service.backfill(**request, correlation_id=uuid4())
    assert first.run is not None and first.run.status is MarketSyncStatus.SUCCEEDED
    assert first.succeeded == 2 and first.run.total_inserted == 6
    assert second.skipped == 2 and second.run is not None
    assert second.run.total_inserted == 0
    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(MarketBarModel).where(
                    MarketBarModel.instrument_id.in_([item.id for item in instruments])
                )
            )
        )
        assert len(rows) == 6
        assert str(rows[0].close).startswith("10.6")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_retries_then_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter(failures_before_success={"699901": 2})
    _, service, instruments = await seeded(session_factory, adapter)
    result = await service.backfill(
        adapter=adapter,
        instruments=[item for item in instruments if item.symbol == "699901"],
        universe="manual",
        timeframe=MarketTimeframe.DAY_1,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=500,
        continue_on_error=True,
        correlation_id=uuid4(),
        max_retries=2,
    )
    assert result.succeeded == 1 and result.retry_count == 2
    assert adapter.attempts["699901"] == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_partial_failure_continues_and_records_stable_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter(failures_before_success={"699901": 99})
    _, service, instruments = await seeded(session_factory, adapter)
    result = await service.backfill(
        adapter=adapter,
        instruments=instruments,
        universe="research",
        timeframe=MarketTimeframe.DAY_1,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=500,
        continue_on_error=True,
        correlation_id=uuid4(),
        max_retries=1,
    )
    assert result.failed == 1 and result.succeeded == 1
    assert result.run is not None and result.run.status is MarketSyncStatus.PARTIALLY_SUCCEEDED
    assert result.failures[0]["code"] == "D01_PROVIDER_FETCH_FAILED"
    assert result.run.metadata["failed_instrument_count"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_all_fail_is_failed_and_stop_marks_unprocessed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter(failures_before_success={"699901": 99, "399901": 99})
    _, service, instruments = await seeded(session_factory, adapter)
    result = await service.backfill(
        adapter=adapter,
        instruments=instruments,
        universe="research",
        timeframe=MarketTimeframe.DAY_1,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=500,
        continue_on_error=False,
        correlation_id=uuid4(),
        max_retries=0,
    )
    assert result.failed == 1 and result.unprocessed == 1
    assert result.run is not None and result.run.status is MarketSyncStatus.FAILED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invalid_ohlc_negative_volume_and_order_are_rejected_per_instrument(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    invalid = daily_bars("699901")
    invalid[0] = ExternalMarketBar(
        symbol="699901",
        timeframe=MarketTimeframe.DAY_1,
        bar_time=datetime(2025, 1, 1, tzinfo=UTC),
        open="10",
        high="9",
        low="8",
        close="10",
        volume="-1",
    )
    invalid[1], invalid[2] = invalid[2], invalid[1]
    adapter = FakeHistoricalAdapter(bars={"699901": invalid, "399901": daily_bars("399901")})
    _, service, instruments = await seeded(session_factory, adapter)
    one = [item for item in instruments if item.symbol == "699901"]
    result = await service.backfill(
        adapter=adapter,
        instruments=one,
        universe="manual",
        timeframe=MarketTimeframe.DAY_1,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=500,
        continue_on_error=True,
        correlation_id=uuid4(),
    )
    assert result.run is not None
    assert result.run.status is MarketSyncStatus.PARTIALLY_SUCCEEDED
    assert result.run.total_rejected == 2
    assert result.run.total_inserted == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_dry_run_has_no_run_or_bar_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    _, service, instruments = await seeded(session_factory, adapter)
    async with session_factory() as session:
        before = await session.scalar(select(func.count()).select_from(MarketBarModel))
    result = await service.backfill(
        adapter=adapter,
        instruments=instruments,
        universe="research",
        timeframe=MarketTimeframe.DAY_1,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=500,
        continue_on_error=True,
        correlation_id=uuid4(),
        dry_run=True,
    )
    assert result.run is None and result.dry_run is True
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MarketBarModel)) == before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_d01_does_not_create_trading_strategy_or_ledger_facts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    guarded_models = (
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
            for model in guarded_models
        }
    adapter = FakeHistoricalAdapter()
    universes, service, instruments = await seeded(session_factory, adapter)
    await universes.create_research_universe(correlation_id=uuid4(), limit=2)
    await service.backfill(
        adapter=adapter,
        instruments=instruments,
        universe="research",
        timeframe=MarketTimeframe.DAY_1,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=500,
        continue_on_error=True,
        correlation_id=uuid4(),
    )
    async with session_factory() as session:
        for model in guarded_models:
            assert (
                await session.scalar(select(func.count()).select_from(model))
                == before[model.__tablename__]
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_run_read_api_returns_metadata_and_stable_not_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    adapter = FakeHistoricalAdapter()
    _, service, instruments = await seeded(session_factory, adapter)
    result = await service.backfill(
        adapter=adapter,
        instruments=instruments[:1],
        universe="manual",
        timeframe=MarketTimeframe.DAY_1,
        start=datetime(2025, 1, 1, tzinfo=UTC),
        end=datetime(2025, 1, 3, tzinfo=UTC),
        batch_size=500,
        continue_on_error=True,
        correlation_id=uuid4(),
    )
    assert result.run is not None
    app = create_app(
        Settings(environment="test"),
        database=DatabaseStub(session_factory),
        redis_service=ProbeStub(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/market-data/sync-runs/{result.run.id}")
        assert response.status_code == 200
        assert response.json()["metadata"]["operation"] == "HISTORICAL_BACKFILL"
        missing = await client.get(f"/api/v1/market-data/sync-runs/{uuid4()}")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "MARKET_SYNC_RUN_NOT_FOUND"


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("timeframe", "batch_size", "max_retries", "expected_code"),
    [
        (MarketTimeframe.MINUTE_1, 500, 2, "D01_TIMEFRAME_UNSUPPORTED"),
        (MarketTimeframe.DAY_1, 0, 2, "D01_BATCH_SIZE_INVALID"),
        (MarketTimeframe.DAY_1, 500, 3, "D01_RETRY_LIMIT_INVALID"),
    ],
)
async def test_backfill_rejects_unsafe_bounds(
    session_factory: async_sessionmaker[AsyncSession],
    timeframe: MarketTimeframe,
    batch_size: int,
    max_retries: int,
    expected_code: str,
) -> None:
    adapter = FakeHistoricalAdapter()
    _, service, instruments = await seeded(session_factory, adapter)
    with pytest.raises(ApplicationError) as captured:
        await service.backfill(
            adapter=adapter,
            instruments=instruments[:1],
            universe="manual",
            timeframe=timeframe,
            start=datetime(2025, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 3, tzinfo=UTC),
            batch_size=batch_size,
            continue_on_error=True,
            correlation_id=uuid4(),
            max_retries=max_retries,
        )
    assert captured.value.code == expected_code
