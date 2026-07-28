from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Self
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_domain.scanners import ScanRun

SCAN_DATE = date(2026, 7, 22)


@dataclass
class Store:
    runs: dict[UUID, ScanRun]


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
        status = filters.get("status")
        if status:
            values = [item for item in values if item.status.value == status]
        return deepcopy(values[offset : offset + limit]), len(values)


class CalendarRepository:
    async def list(
        self, *, exchange: str | None, start: date | None, end: date | None, limit: int
    ) -> list[object]:
        del exchange, start, limit
        return [type("Session", (), {"session_date": end, "is_open": True})()]


class FakeUow:
    def __init__(self, shared: Store) -> None:
        self.shared = shared
        self.local = deepcopy(shared)

    async def __aenter__(self) -> Self:
        self.scan_runs = RunRepository(self.local)
        self.trading_calendar = CalendarRepository()
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        self.shared.runs = self.local.runs


class DatabaseStub:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None

    def unit_of_work(self) -> FakeUow:
        return FakeUow(self.store)


class Probe:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.fixture
def screening_client() -> Iterator[tuple[TestClient, Store]]:
    store = Store(runs={})
    app = create_app(
        Settings(environment="test", postgres_host="unused", redis_host="unused"),
        database=DatabaseStub(store),
        redis_service=Probe(),
    )
    with TestClient(app) as client:
        yield client, store


def payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "底部放倍量",
        "origin": "USER_STRUCTURED",
        "universe_spec": {
            "universe_key": "ALL_A_SHARES",
            "exclude_st": True,
        },
        "as_of_date": SCAN_DATE.isoformat(),
        "timeframe": "DAY_1",
        "conditions": [
            {
                "condition_key": "BOTTOM_VOLUME_EXPANSION",
                "parameters": {},
            }
        ],
        "ranking_rules": [{"field": "volume_multiple", "direction": "DESC"}],
        "price_adjustment_mode": "RAW",
        "idempotency_key": "sc02-api-test",
    }


def test_condition_catalog_and_two_templates_are_public(
    screening_client: tuple[TestClient, Store],
) -> None:
    client, _ = screening_client
    conditions = client.get("/api/v1/screening-conditions")
    assert conditions.status_code == 200
    keys = {item["condition_key"] for item in conditions.json()}
    assert "LIMIT_UP_PULLBACK" in keys
    assert "BOTTOM_VOLUME_EXPANSION" in keys
    assert "TRADING_STATUS" in keys
    bottom = next(
        item for item in conditions.json() if item["condition_key"] == "BOTTOM_VOLUME_EXPANSION"
    )
    assert bottom["parameter_schema"][0]["display_name"] == "价格区间窗口"
    assert "当前位于" in bottom["explanation_template"]

    templates = client.get("/api/v1/screening-templates")
    assert templates.status_code == 200
    assert [item["template_key"] for item in templates.json()] == [
        "LIMIT_UP_PULLBACK",
        "BOTTOM_VOLUME_EXPANSION",
    ]


def test_create_is_async_durable_idempotent_and_queryable(
    screening_client: tuple[TestClient, Store],
) -> None:
    client, store = screening_client
    created = client.post("/api/v1/research/screenings", json=payload())
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "QUEUED"
    assert body["spec"]["conditions"][0]["condition_key"] == "BOTTOM_VOLUME_EXPANSION"
    assert body["processed_instruments"] == 0
    assert len(store.runs) == 1

    replay = client.post("/api/v1/research/screenings", json=payload())
    assert replay.status_code == 202
    assert replay.json()["screening_id"] == body["screening_id"]
    assert replay.json()["replayed"] is True
    assert len(store.runs) == 1

    listed = client.get("/api/v1/research/screenings")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    detail = client.get(f"/api/v1/research/screenings/{body['screening_id']}")
    progress = client.get(f"/api/v1/research/screenings/{body['screening_id']}/progress")
    assert detail.status_code == progress.status_code == 200
    assert progress.json()["status"] == "QUEUED"


@pytest.mark.parametrize(
    "unsafe",
    (
        {"python": "import os"},
        {"sql": "select * from orders"},
        {"url": "https://example.invalid"},
        {"order": {"side": "BUY"}},
        {"fill_id": "anything"},
    ),
)
def test_screening_rejects_code_sql_network_and_trading_fields(
    screening_client: tuple[TestClient, Store], unsafe: dict[str, object]
) -> None:
    client, store = screening_client
    request = payload()
    request["idempotency_key"] = f"unsafe-{next(iter(unsafe))}"
    request["exclusions"] = unsafe
    response = client.post("/api/v1/research/screenings", json=request)
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {
        "SCREENING_UNSAFE_SPEC_FIELD",
        "SCREENING_UNSAFE_SPEC_VALUE",
    }
    assert store.runs == {}


def test_screening_schema_rejects_unknown_top_level_fields(
    screening_client: tuple[TestClient, Store],
) -> None:
    client, store = screening_client
    request = payload()
    request["python_code"] = "print('unsafe')"
    response = client.post("/api/v1/research/screenings", json=request)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert store.runs == {}
