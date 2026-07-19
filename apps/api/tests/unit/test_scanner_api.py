from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Self
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.scanners import ScanResult, ScanRun
from alphadesk_domain.strategy import StrategyBar

NOW = datetime(2026, 3, 20, tzinfo=UTC)
FIRST_ID = UUID("11111111-1111-1111-1111-111111111111")
SECOND_ID = UUID("22222222-2222-2222-2222-222222222222")


def instrument(entity_id: UUID, symbol: str) -> Instrument:
    return Instrument(
        id=entity_id,
        symbol=symbol,
        exchange="SSE",
        market="CN",
        name=f"测试股票{symbol}",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
    )


def daily_bars(entity_id: UUID, symbol: str, latest_volume: str) -> list[StrategyBar]:
    return [
        StrategyBar(
            instrument_id=entity_id,
            symbol=symbol,
            exchange="SSE",
            timeframe=MarketTimeframe.DAY_1,
            timestamp=NOW - timedelta(days=2 - index),
            open=Decimal("10"),
            high=Decimal("10.2"),
            low=Decimal("9.8"),
            close=Decimal("10"),
            volume=Decimal(volume),
            amount=Decimal("10") * Decimal(volume),
        )
        for index, volume in enumerate(("100", "100", latest_volume))
    ]


@dataclass
class Store:
    runs: dict[UUID, ScanRun]
    results: list[ScanResult]
    instruments: list[Instrument]
    bars: list[StrategyBar]


class RunRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def add(self, entity: ScanRun) -> None:
        self.store.runs[entity.id] = deepcopy(entity)

    async def update(self, entity: ScanRun) -> None:
        self.store.runs[entity.id] = deepcopy(entity)

    async def get_by_id(self, entity_id: UUID) -> ScanRun | None:
        return deepcopy(self.store.runs.get(entity_id))

    async def get_by_idempotency_key(self, key: str) -> ScanRun | None:
        return next(
            (deepcopy(item) for item in self.store.runs.values() if item.idempotency_key == key),
            None,
        )

    async def list(
        self, *, offset: int, limit: int, **filters: object
    ) -> tuple[list[ScanRun], int]:
        values = list(self.store.runs.values())
        scanner_key = filters.get("scanner_key")
        run_status = filters.get("status")
        instrument_id = filters.get("instrument_id")
        if scanner_key is not None:
            values = [item for item in values if item.scanner_key == scanner_key]
        if run_status is not None:
            values = [item for item in values if item.status.value == run_status]
        if instrument_id is not None:
            values = [item for item in values if instrument_id in item.instrument_ids]
        return deepcopy(values[offset : offset + limit]), len(values)


class ResultRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def append_many(self, entities: list[ScanResult]) -> None:
        self.store.results.extend(deepcopy(entities))

    async def list_by_run(self, run_id: UUID) -> list[ScanResult]:
        values = [item for item in self.store.results if item.scan_run_id == run_id]
        return deepcopy(sorted(values, key=lambda item: item.rank))

    async def count_by_run(self, run_id: UUID) -> int:
        return len([item for item in self.store.results if item.scan_run_id == run_id])


class InstrumentRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def get_many(self, entity_ids: list[UUID]) -> list[Instrument]:
        requested = set(entity_ids)
        return deepcopy([item for item in self.store.instruments if item.id in requested])


class BarRepository:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def list_bars(self, **filters: object) -> list[StrategyBar]:
        requested = set(filters["instrument_ids"])
        return deepcopy([item for item in self.store.bars if item.instrument_id in requested])


class FakeUow:
    def __init__(self, shared: Store) -> None:
        self.shared = shared
        self.local = deepcopy(shared)

    async def __aenter__(self) -> Self:
        self.scan_runs = RunRepository(self.local)
        self.scan_results = ResultRepository(self.local)
        self.instruments = InstrumentRepository(self.local)
        self.historical_bars = BarRepository(self.local)
        return self

    async def commit(self) -> None:
        self.shared.runs = self.local.runs
        self.shared.results = self.local.results

    async def rollback(self) -> None:
        pass

    async def __aexit__(self, *args: object) -> None:
        pass


class DatabaseStub:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass

    def unit_of_work(self) -> FakeUow:
        return FakeUow(self.store)


class Probe:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


@pytest.fixture
def scanner_client() -> Iterator[tuple[TestClient, Store]]:
    first = instrument(FIRST_ID, "600001")
    second = instrument(SECOND_ID, "600002")
    store = Store(
        runs={},
        results=[],
        instruments=[first, second],
        bars=daily_bars(first.id, first.symbol, "300")
        + daily_bars(second.id, second.symbol, "400"),
    )
    app = create_app(
        Settings(environment="test", postgres_host="unused", redis_host="unused"),
        database=DatabaseStub(store),
        redis_service=Probe(),
    )
    with TestClient(app) as client:
        yield client, store


def payload(key: str = "scan-api-1") -> dict[str, object]:
    return {
        "scanner_key": "volume_anomaly",
        "parameters": {"volume_window": 2, "minimum_volume_ratio": "2"},
        "instrument_ids": [str(FIRST_ID), str(SECOND_ID)],
        "timeframe": "DAY_1",
        "as_of": NOW.isoformat(),
        "idempotency_key": key,
    }


def test_catalog_is_stable(scanner_client: tuple[TestClient, Store]) -> None:
    response = scanner_client[0].get("/api/v1/scanners/catalog")
    assert response.status_code == 200
    items = response.json()
    assert [item["scanner_key"] for item in items] == [
        "limit_up_pullback",
        "volume_anomaly",
    ]
    assert items[1]["parameters"][0]["name"] == "volume_window"
    assert "class" not in items[1] and "path" not in items[1]


def test_ranked_results_and_no_trading_capability(
    scanner_client: tuple[TestClient, Store],
) -> None:
    client, _ = scanner_client
    created = client.post("/api/v1/scan-runs", json=payload())
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "COMPLETED" and body["matches_found"] == 2
    assert all(value is False for value in body["capabilities"].values())
    results = client.get(f"/api/v1/scan-runs/{body['scan_run_id']}/results").json()
    assert [item["rank"] for item in results["items"]] == [1, 2]
    assert [item["score"] for item in results["items"]] == ["4", "3"]
    assert results["items"][0]["instrument"]["symbol"] == "600002"


def test_idempotency_and_queries(scanner_client: tuple[TestClient, Store]) -> None:
    client, store = scanner_client
    first = client.post("/api/v1/scan-runs", json=payload())
    second = client.post("/api/v1/scan-runs", json=payload())
    assert first.status_code == second.status_code == 201
    run_id = first.json()["scan_run_id"]
    assert second.json()["scan_run_id"] == run_id and second.json()["replayed"] is True
    assert len(store.runs) == 1 and len(store.results) == 2
    assert client.get("/api/v1/scan-runs?page=1&page_size=10").json()["total"] == 1
    assert client.get(f"/api/v1/scan-runs/{run_id}").status_code == 200
    integrity = client.get(f"/api/v1/scan-runs/{run_id}/integrity").json()
    assert integrity == {"scan_run_id": run_id, "valid": True, "issues": []}


def test_conflict_and_invalid_decimal_are_controlled(
    scanner_client: tuple[TestClient, Store],
) -> None:
    client, _ = scanner_client
    assert client.post("/api/v1/scan-runs", json=payload()).status_code == 201
    changed = payload()
    changed["as_of"] = (NOW - timedelta(days=1)).isoformat()
    conflict = client.post("/api/v1/scan-runs", json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "SCAN_RUN_IDEMPOTENCY_CONFLICT"
    invalid = payload("invalid")
    invalid["parameters"] = {"minimum_volume_ratio": 2.0}
    response = client.post("/api/v1/scan-runs", json=invalid)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
