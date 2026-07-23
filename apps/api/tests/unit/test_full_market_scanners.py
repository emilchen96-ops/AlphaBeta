from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from alphadesk_api.application.scanners import (
    FullMarketScannerProcessor,
    FullMarketScannerService,
    FullMarketScanRequest,
    ScannerQueryService,
    ScannerUniverseFilters,
)
from alphadesk_api.infrastructure.repositories import SqlAlchemyScanRunMemberRepository
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.scanners import (
    ScanMemberStatus,
    ScannerRegistry,
    ScanRun,
    ScanRunMember,
    ScanRunStatus,
    register_builtin_scanners,
)
from alphadesk_domain.strategy import StrategyBar

SCAN_DATE = date(2026, 7, 22)
SCAN_AT = datetime(2026, 7, 22, 7, tzinfo=UTC)


class RunRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def add(self, entity: ScanRun) -> None:
        self.store.runs[entity.id] = entity

    async def update(self, entity: ScanRun) -> None:
        self.store.runs[entity.id] = entity

    async def get_by_id(self, run_id: UUID) -> ScanRun | None:
        return self.store.runs.get(run_id)

    async def get_for_update(self, run_id: UUID) -> ScanRun | None:
        return self.store.runs.get(run_id)

    async def get_by_idempotency_key(self, key: str) -> ScanRun | None:
        return next(
            (item for item in self.store.runs.values() if item.idempotency_key == key),
            None,
        )

    async def get_next_pending(self, statuses: tuple[ScanRunStatus, ...]) -> ScanRun | None:
        return next(
            (item for item in self.store.runs.values() if item.status in statuses),
            None,
        )


class ResultRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def append_many(self, entities: list[object]) -> None:
        self.store.results.extend(entities)

    async def list_by_run(self, run_id: UUID) -> list[object]:
        return [item for item in self.store.results if item.scan_run_id == run_id]


class MemberRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def upsert_many(self, entities: list[ScanRunMember]) -> None:
        for entity in entities:
            self.store.members[(entity.scan_run_id, entity.instrument_id)] = entity

    async def list_by_run(self, run_id: UUID, *, status: str | None = None) -> list[ScanRunMember]:
        values = [
            item for (saved_run_id, _), item in self.store.members.items() if saved_run_id == run_id
        ]
        if status is not None:
            values = [item for item in values if item.status.value == status]
        return values

    async def count_by_run(self, run_id: UUID) -> dict[str, int]:
        values: dict[str, int] = {}
        for item in await self.list_by_run(run_id):
            values[item.status.value] = values.get(item.status.value, 0) + 1
        return values


class InstrumentRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def search(self, **filters: object) -> tuple[list[Instrument], int]:
        values = [
            item
            for item in self.store.instruments
            if (not filters.get("asset_type") or item.asset_type == filters["asset_type"])
            and (filters.get("is_active") is None or item.is_active is filters["is_active"])
        ]
        return values, len(values)

    async def get_many(self, instrument_ids: list[UUID]) -> list[Instrument]:
        wanted = set(instrument_ids)
        return [item for item in self.store.instruments if item.id in wanted]


class CalendarRepository:
    async def list(
        self, *, exchange: str | None, start: date | None, end: date | None, limit: int
    ) -> list[object]:
        del exchange, start, limit
        return [SimpleNamespace(session_date=end or SCAN_DATE, is_open=True)]


class TradingStatusRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def list(self, **_: object) -> list[object]:
        return [
            SimpleNamespace(
                instrument_id=instrument_id,
                status=SimpleNamespace(value=value),
            )
            for instrument_id, value in self.store.trading_statuses.items()
        ]


class HistoricalRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def list_authoritative_bars(self, **filters: object) -> list[StrategyBar]:
        self.store.source_calls.append(str(filters["source_code"]))
        wanted = set(filters["instrument_ids"])
        return [bar for instrument_id in wanted for bar in self.store.bars.get(instrument_id, [])]


class Store:
    def __init__(self, instruments: list[Instrument]) -> None:
        self.instruments = instruments
        self.runs: dict[UUID, ScanRun] = {}
        self.results: list[object] = []
        self.members: dict[tuple[UUID, UUID], ScanRunMember] = {}
        self.bars: dict[UUID, list[StrategyBar]] = {}
        self.trading_statuses: dict[UUID, str] = {}
        self.source_calls: list[str] = []


class UnitOfWork:
    def __init__(self, store: Store) -> None:
        self.scan_runs = RunRepository(store)
        self.scan_results = ResultRepository(store)
        self.scan_run_members = MemberRepository(store)
        self.instruments = InstrumentRepository(store)
        self.trading_calendar = CalendarRepository()
        self.instrument_trading_statuses = TradingStatusRepository(store)
        self.historical_bars = HistoricalRepository(store)

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        return None


def make_instrument(
    index: int,
    *,
    exchange: str = "SSE",
    name: str | None = None,
    asset_type: str = "STOCK",
    is_active: bool = True,
) -> Instrument:
    prefix = "6" if exchange == "SSE" else ("3" if exchange == "SZSE" else "9")
    return Instrument(
        symbol=f"{prefix}{index:05d}"[-6:],
        exchange=exchange,
        market="CN_A",
        name=name or f"测试股票{index}",
        asset_type=asset_type,
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
        is_active=is_active,
    )


def ready_bars(item: Instrument) -> list[StrategyBar]:
    return [
        StrategyBar(
            instrument_id=item.id,
            symbol=item.symbol,
            exchange=item.exchange,
            timeframe=MarketTimeframe.DAY_1,
            timestamp=SCAN_AT - timedelta(days=2 - index),
            open=Decimal("10"),
            high=Decimal("10.2"),
            low=Decimal("9.8"),
            close=Decimal("10"),
            volume=Decimal(volume),
            amount=Decimal(volume) * Decimal("10"),
        )
        for index, volume in enumerate(("100", "100", "300"))
    ]


def services(store: Store) -> tuple[FullMarketScannerService, FullMarketScannerProcessor]:
    registry = ScannerRegistry()
    register_builtin_scanners(registry)

    def factory() -> UnitOfWork:
        return UnitOfWork(store)

    return (
        FullMarketScannerService(factory, registry),
        FullMarketScannerProcessor(
            factory,
            registry,
            backfill_wait_seconds=0,
            backfill_batch_size=50,
            scan_batch_size=25,
        ),
    )


async def enqueue(
    service: FullMarketScannerService,
    *,
    filters: ScannerUniverseFilters | None = None,
    key: str = "full-market-test",
) -> ScanRun:
    return (
        await service.enqueue(
            FullMarketScanRequest(
                scanner_key="volume_anomaly",
                parameters={"volume_window": 2, "minimum_volume_ratio": "2"},
                scan_date=SCAN_DATE,
                filters=filters or ScannerUniverseFilters(),
                correlation_id=uuid4(),
                idempotency_key=key,
            )
        )
    ).run


@pytest.mark.asyncio
async def test_more_than_one_hundred_stocks_scan_from_miniqmt_only() -> None:
    stocks = [make_instrument(index) for index in range(125)]
    st = make_instrument(900, name="*ST测试")
    etf = make_instrument(901, asset_type="ETF")
    inactive = make_instrument(902, is_active=False)
    store = Store([*stocks, st, etf, inactive])
    store.bars = {item.id: ready_bars(item) for item in stocks}
    service, processor = services(store)
    run = await enqueue(service)

    await processor.process(run.id, lambda _: _completed())

    assert run.status is ScanRunStatus.COMPLETED
    assert run.total_instruments == 126
    assert run.excluded_instruments == 1
    assert run.instruments_scanned == run.matches_found == 125
    assert set(store.source_calls) == {"MINIQMT"}
    statuses = {item.status for item in store.members.values()}
    assert ScanMemberStatus.EXCLUDED in statuses
    assert ScanMemberStatus.MATCHED in statuses


@pytest.mark.asyncio
async def test_missing_history_is_requested_in_batches_and_finishes_partially() -> None:
    stocks = [make_instrument(index) for index in range(121)]
    store = Store(stocks)
    service, processor = services(store)
    run = await enqueue(service, key="backfill")
    requests: list[dict[str, object]] = []

    async def collect(payload: dict[str, object]) -> None:
        requests.append(payload)

    await processor.process(run.id, collect)
    assert run.status is ScanRunStatus.BACKFILLING
    assert [len(item["instrument_ids"]) for item in requests] == [50, 50, 21]
    assert all(item["origin"] == "SC01_R" for item in requests)

    store.bars = {item.id: ready_bars(item) for item in stocks[:-1]}
    await processor.process(run.id, collect)
    assert run.status is ScanRunStatus.PARTIAL
    assert run.data_ready_instruments == 120
    assert run.insufficient_history == 1
    assert run.instruments_scanned == 120


@pytest.mark.asyncio
async def test_filters_are_audited_and_cancel_survives_worker_boundary() -> None:
    normal = make_instrument(1)
    bse = make_instrument(2, exchange="BSE")
    star = make_instrument(68888)
    star.symbol = "688888"
    chinext = make_instrument(30001, exchange="SZSE")
    chinext.symbol = "300001"
    suspended = make_instrument(3)
    manual = make_instrument(4)
    delisting = make_instrument(5, name="退市测试")
    store = Store([normal, bse, star, chinext, suspended, manual, delisting])
    store.trading_statuses[suspended.id] = "SUSPENDED"
    service, processor = services(store)
    run = await enqueue(
        service,
        key="filters",
        filters=ScannerUniverseFilters(
            exclude_bse=True,
            exclude_star_market=True,
            exclude_chinext=True,
            excluded_instrument_ids=(manual.id,),
        ),
    )

    await processor.process(run.id, lambda _: _completed())
    reasons = {item.instrument_id: item.reason_code for item in store.members.values()}
    assert reasons[bse.id] == "BSE_EXCLUDED"
    assert reasons[star.id] == "STAR_MARKET_EXCLUDED"
    assert reasons[chinext.id] == "CHINEXT_EXCLUDED"
    assert reasons[suspended.id] == "SUSPENDED"
    assert reasons[manual.id] == "MANUAL_EXCLUDED"
    assert reasons[delisting.id] == "DELISTING_EXCLUDED"

    cancel_store = Store([make_instrument(20)])
    cancel_service, cancel_processor = services(cancel_store)
    canceled = await enqueue(cancel_service, key="cancel")
    await ScannerQueryService(lambda: UnitOfWork(cancel_store)).cancel(canceled.id)
    await cancel_processor.process(canceled.id, lambda _: _completed())
    assert canceled.status is ScanRunStatus.CANCELED


@pytest.mark.asyncio
async def test_member_repository_chunks_catalog_larger_than_asyncpg_parameter_limit() -> None:
    session = SimpleNamespace(execute=AsyncMock(), flush=AsyncMock())
    repository = SqlAlchemyScanRunMemberRepository(session)
    run_id = uuid4()
    members = [
        ScanRunMember(
            scan_run_id=run_id,
            instrument_id=uuid4(),
            symbol=f"{index:06d}",
            exchange="SSE",
            instrument_name=f"股票{index}",
            status=ScanMemberStatus.INCLUDED,
        )
        for index in range(2001)
    ]

    await repository.upsert_many(members)

    assert session.execute.await_count == 3
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotency_and_running_job_are_restart_safe() -> None:
    stock = make_instrument(1)
    store = Store([stock])
    store.bars[stock.id] = ready_bars(stock)
    service, processor = services(store)
    first = await enqueue(service, key="same")
    second = await enqueue(service, key="same")
    assert first.id == second.id

    first.instrument_ids = (stock.id,)
    first.status = ScanRunStatus.RUNNING
    first.data_ready_instruments = 1
    processed = await processor.process_next(lambda _: _completed())
    assert processed == first.id
    assert first.status is ScanRunStatus.COMPLETED


async def _completed() -> None:
    return None
