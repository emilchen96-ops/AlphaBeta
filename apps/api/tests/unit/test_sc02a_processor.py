from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Self
from uuid import UUID, uuid4

import pytest

from alphadesk_api.application.screenings import (
    PointInTimeAshareUniverseService,
    RuleBasedScreeningProcessor,
)
from alphadesk_api.workers.scanners import ScannerWorker
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.scanners import (
    ScanMemberStatus,
    ScanResult,
    ScanRun,
    ScanRunMember,
    ScanRunStatus,
)
from alphadesk_domain.screening import (
    RankingRule,
    ScreeningCondition,
    ScreeningSpec,
    UniverseSpec,
    builtin_condition_catalog,
)
from alphadesk_domain.strategy import StrategyBar

SCAN_DATE = date(2026, 7, 22)
SCAN_AT = datetime(2026, 7, 22, 7, tzinfo=UTC)


def instrument(
    symbol: str,
    exchange: str,
    *,
    listed_at: date | None = date(2020, 1, 1),
    delisted_at: date | None = None,
    is_active: bool = True,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        exchange=exchange,
        market="CN_A",
        name=f"测试{symbol}",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
        listed_at=listed_at,
        delisted_at=delisted_at,
        is_active=is_active,
    )


def bar(
    item: Instrument,
    timestamp: datetime,
    *,
    open_price: str = "14",
    high: str = "15",
    low: str = "12",
    close: str = "14",
    volume: str = "100",
) -> StrategyBar:
    return StrategyBar(
        instrument_id=item.id,
        symbol=item.symbol,
        exchange=item.exchange,
        timeframe=MarketTimeframe.DAY_1,
        timestamp=timestamp,
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
        amount=Decimal(close) * Decimal(volume),
    )


def bottom_bars(item: Instrument, *, matching: bool = True) -> list[StrategyBar]:
    values: list[StrategyBar] = []
    for index in range(61):
        values.append(
            bar(
                item,
                SCAN_AT - timedelta(days=61 - index),
                high=("20" if index == 10 else "15"),
                low=("10" if index == 20 else "12"),
            )
        )
    values.append(
        bar(
            item,
            SCAN_AT,
            open_price="11.5",
            high=("12" if matching else "19.5"),
            low="11",
            close=("11.9" if matching else "19"),
            volume="235",
        )
    )
    return values


@dataclass
class Store:
    instruments: list[Instrument]
    runs: dict[UUID, ScanRun] = field(default_factory=dict)
    members: dict[tuple[UUID, UUID], ScanRunMember] = field(default_factory=dict)
    results: list[ScanResult] = field(default_factory=list)
    bars: dict[UUID, list[StrategyBar]] = field(default_factory=dict)
    bar_queries: int = 0
    universe_queries: int = 0
    status_queries: int = 0


class InstrumentRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def list_point_in_time_ashares(
        self, *, as_of_date: date, source_code: str
    ) -> list[Instrument]:
        assert source_code == "MINIQMT"
        self.store.universe_queries += 1
        return deepcopy(
            [
                item
                for item in self.store.instruments
                if item.exchange in {"SSE", "SZSE", "BSE"}
                and item.market == "CN_A"
                and item.asset_type == "STOCK"
                and (item.listed_at is None or item.listed_at <= as_of_date)
                and (item.delisted_at is None or item.delisted_at >= as_of_date)
            ]
        )

    async def get_many(self, instrument_ids: list[UUID]) -> list[Instrument]:
        wanted = set(instrument_ids)
        return deepcopy([item for item in self.store.instruments if item.id in wanted])


class TradingStatusRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def list(self, **_: object) -> list[object]:
        self.store.status_queries += 1
        return [
            SimpleNamespace(
                instrument_id=item.id,
                status=SimpleNamespace(value="TRADING"),
            )
            for item in self.store.instruments
        ]


class RunRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def add(self, entity: ScanRun) -> None:
        self.store.runs[entity.id] = deepcopy(entity)

    async def update(self, entity: ScanRun) -> None:
        self.store.runs[entity.id] = deepcopy(entity)

    async def get_by_id(self, entity_id: UUID) -> ScanRun | None:
        return deepcopy(self.store.runs.get(entity_id))

    async def get_for_update(self, entity_id: UUID) -> ScanRun | None:
        return await self.get_by_id(entity_id)


class MemberRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def upsert_many(self, entities: list[ScanRunMember]) -> None:
        for item in entities:
            self.store.members[(item.scan_run_id, item.instrument_id)] = deepcopy(item)

    async def list_by_run(self, run_id: UUID) -> list[ScanRunMember]:
        return deepcopy(
            [
                item
                for (stored_run_id, _), item in self.store.members.items()
                if stored_run_id == run_id
            ]
        )


class ResultRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def append_many(self, entities: list[ScanResult]) -> None:
        self.store.results.extend(deepcopy(entities))


class HistoricalRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def list_authoritative_bars(self, **filters: object) -> list[StrategyBar]:
        assert filters["source_code"] == "MINIQMT"
        self.store.bar_queries += 1
        wanted = set(filters["instrument_ids"])
        end_at = filters["end_at"]
        return deepcopy(
            [
                market_bar
                for instrument_id in wanted
                for market_bar in self.store.bars.get(instrument_id, [])
                if market_bar.timestamp < end_at
            ]
        )


class UnitOfWork:
    def __init__(self, store: Store) -> None:
        self.instruments = InstrumentRepository(store)
        self.instrument_trading_statuses = TradingStatusRepository(store)
        self.scan_runs = RunRepository(store)
        self.scan_run_members = MemberRepository(store)
        self.scan_results = ResultRepository(store)
        self.historical_bars = HistoricalRepository(store)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        return None


def factory(store: Store):
    return lambda: UnitOfWork(store)


def screening_spec() -> ScreeningSpec:
    return ScreeningSpec(
        schema_version=1,
        name="底部放倍量",
        origin="UNIT_TEST",
        universe_spec=UniverseSpec(),
        as_of_date=SCAN_DATE,
        timeframe=MarketTimeframe.DAY_1,
        conditions=(ScreeningCondition(condition_key="BOTTOM_VOLUME_EXPANSION"),),
        ranking_rules=(RankingRule(field="volume_multiple"),),
        price_adjustment_mode=PriceAdjustmentMode.RAW,
    )


def run(store: Store) -> ScanRun:
    catalog = builtin_condition_catalog()
    item = ScanRun(
        scanner_key="BOTTOM_VOLUME_EXPANSION",
        scanner_version="1.0.0",
        parameters={},
        screening_spec=screening_spec().snapshot(catalog),
        universe_type="ALL_ACTIVE_A_SHARES",
        instrument_ids=(),
        timeframe=MarketTimeframe.DAY_1,
        as_of=datetime(2026, 7, 22, 7, tzinfo=UTC),
        status=ScanRunStatus.QUEUED,
        idempotency_key=f"processor:{uuid4()}",
        request_fingerprint="a" * 64,
        correlation_id=uuid4(),
    )
    store.runs[item.id] = deepcopy(item)
    return item


@pytest.mark.asyncio
async def test_sc02a_worker_continues_when_redis_heartbeat_is_unavailable() -> None:
    class BrokenRedisClient:
        async def set(self, *_: object, **__: object) -> None:
            raise ConnectionError("redis unavailable")

    class Processor:
        called = False

        async def process_next(self, _: object, __: object) -> UUID:
            self.called = True
            return uuid4()

    processor = Processor()
    worker = object.__new__(ScannerWorker)
    worker._redis = SimpleNamespace(client=BrokenRedisClient())
    worker._settings = SimpleNamespace(
        scanner_worker_heartbeat_seconds=5,
    )
    worker._processor = processor  # type: ignore[assignment]

    assert await worker.tick() == 1
    assert processor.called is True


@pytest.mark.asyncio
async def test_point_in_time_universe_includes_sse_szse_bse_and_delisted_later() -> None:
    sse = instrument("600001", "SSE")
    szse = instrument("000001", "SZSE")
    bse = instrument(
        "920001",
        "BSE",
        delisted_at=date(2025, 1, 1),
        is_active=False,
    )
    future = instrument("600999", "SSE", listed_at=date(2025, 1, 1))
    already_delisted = instrument(
        "000999",
        "SZSE",
        delisted_at=date(2023, 1, 1),
        is_active=False,
    )
    store = Store([sse, szse, bse, future, already_delisted])
    resolved = await PointInTimeAshareUniverseService(factory(store)).resolve(
        date(2024, 1, 1), UniverseSpec()
    )
    assert {(item.exchange, item.symbol) for item in resolved.included} == {
        ("SSE", "600001"),
        ("SZSE", "000001"),
        ("BSE", "920001"),
    }
    assert store.universe_queries == 1
    assert store.status_queries == 1


@pytest.mark.asyncio
async def test_processor_batches_once_without_n_plus_one_and_persists_explanations() -> None:
    match = instrument("600001", "SSE")
    no_match = instrument("000001", "SZSE")
    store = Store([match, no_match])
    store.bars[match.id] = bottom_bars(match)
    store.bars[no_match.id] = bottom_bars(no_match, matching=False)
    scan_run = run(store)
    processor = RuleBasedScreeningProcessor(
        factory(store),
        builtin_condition_catalog(),
        batch_size=1,
    )

    await processor.process(scan_run.id)

    saved = store.runs[scan_run.id]
    assert saved.status is ScanRunStatus.COMPLETED
    assert saved.total_instruments == saved.data_ready_instruments == 2
    assert saved.instruments_scanned == 2
    assert saved.matches_found == 1
    assert saved.query_count == 3
    assert saved.bars_read == 124
    assert saved.batch_count == 2
    assert saved.execution_stats["no_n_plus_one"] is True
    assert saved.execution_stats["future_bars_read"] == 0
    assert store.bar_queries == 1
    assert len(store.results) == 1
    assert "当前位于此前60日价格区间底部" in store.results[0].reason
    assert "成交量倍数排名第1" in store.results[0].reason


@pytest.mark.asyncio
async def test_processor_marks_partial_failed_for_insufficient_and_indeterminate() -> None:
    ready = instrument("600001", "SSE")
    insufficient = instrument("000001", "SZSE")
    flat = instrument("920001", "BSE")
    store = Store([ready, insufficient, flat])
    store.bars[ready.id] = bottom_bars(ready)
    store.bars[insufficient.id] = bottom_bars(insufficient)[:10]
    store.bars[flat.id] = [
        bar(
            flat,
            SCAN_AT - timedelta(days=61 - index),
            open_price="10",
            high="10",
            low="10",
            close="10",
        )
        for index in range(62)
    ]
    scan_run = run(store)
    processor = RuleBasedScreeningProcessor(
        factory(store),
        builtin_condition_catalog(),
        batch_size=2,
    )

    await processor.process(scan_run.id)

    saved = store.runs[scan_run.id]
    assert saved.status is ScanRunStatus.PARTIAL_FAILED
    assert saved.insufficient_history == 1
    assert saved.indeterminate_count == 1
    assert saved.failed_instruments == 0
    assert saved.matches_found == 1
    statuses = {
        item.instrument_id: item.status.value
        for item in store.members.values()
        if item.scan_run_id == scan_run.id
    }
    assert statuses[insufficient.id] == "DATA_MISSING"
    assert statuses[flat.id] == "INDETERMINATE"


@pytest.mark.asyncio
async def test_processor_preserves_preparation_failures_in_terminal_status() -> None:
    ready = instrument("600001", "SSE")
    calendar_mismatch = instrument("000001", "SZSE")
    store = Store([ready, calendar_mismatch])
    store.bars[ready.id] = bottom_bars(ready)
    scan_run = run(store)
    scan_run.total_instruments = 2
    scan_run.mark_phase(ScanRunStatus.SCREENING, SCAN_AT, progress_percent=80)
    scan_run.execution_stats = {
        "data_preparation": {
            "prepared": True,
            "ready_instrument_ids": [str(ready.id)],
            "calendar_mismatch_count": 1,
            "reference_data_missing_count": 0,
            "provider_failed_count": 0,
            "quality_failed_count": 0,
            "insufficient_count": 0,
            "listing_history_short_count": 0,
            "data_gap_count": 0,
            "indeterminate_count": 0,
        }
    }
    store.runs[scan_run.id] = deepcopy(scan_run)
    store.members[(scan_run.id, ready.id)] = ScanRunMember(
        scan_run_id=scan_run.id,
        instrument_id=ready.id,
        symbol=ready.symbol,
        exchange=ready.exchange,
        instrument_name=ready.name,
        status=ScanMemberStatus.READY,
    )
    store.members[(scan_run.id, calendar_mismatch.id)] = ScanRunMember(
        scan_run_id=scan_run.id,
        instrument_id=calendar_mismatch.id,
        symbol=calendar_mismatch.symbol,
        exchange=calendar_mismatch.exchange,
        instrument_name=calendar_mismatch.name,
        status=ScanMemberStatus.CALENDAR_MISMATCH,
        reason_code="CALENDAR_MISMATCH",
    )
    processor = RuleBasedScreeningProcessor(
        factory(store),
        builtin_condition_catalog(),
    )

    await processor.process(scan_run.id)

    saved = store.runs[scan_run.id]
    assert saved.status is ScanRunStatus.PARTIAL_FAILED
    assert saved.instruments_scanned == 1
    assert saved.failed_instruments == 1
    assert saved.matches_found == 1


@pytest.mark.asyncio
async def test_processor_isolates_one_instrument_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = instrument("600001", "SSE")
    second = instrument("000001", "SZSE")
    store = Store([first, second])
    store.bars[first.id] = bottom_bars(first)
    store.bars[second.id] = bottom_bars(second)
    scan_run = run(store)

    from alphadesk_api.application import screenings as application_module

    original = application_module.RuleBasedScreeningEngine.evaluate_instrument

    def fail_one(self: object, spec: object, item: Instrument, bars: object, **kwargs: object):
        if item.id == second.id:
            raise ArithmeticError("single instrument failure")
        return original(self, spec, item, bars, **kwargs)

    monkeypatch.setattr(
        application_module.RuleBasedScreeningEngine,
        "evaluate_instrument",
        fail_one,
    )
    processor = RuleBasedScreeningProcessor(
        factory(store),
        builtin_condition_catalog(),
        batch_size=2,
    )

    await processor.process(scan_run.id)

    saved = store.runs[scan_run.id]
    assert saved.status is ScanRunStatus.PARTIAL_FAILED
    assert saved.failed_instruments == 1
    assert saved.matches_found == 1
    failed_member = store.members[(scan_run.id, second.id)]
    assert failed_member.status.value == "FAILED"
    assert failed_member.reason_code == "CONDITION_EVALUATION_FAILED"
