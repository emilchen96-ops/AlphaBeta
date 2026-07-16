from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_domain.entities import Signal
from alphadesk_domain.enums import OrderSide, SignalStatus, SignalType
from tests.unit.test_strategy_runner import INSTRUMENT, NOW, FakeUow, Store, bar


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
def strategy_client() -> Iterator[tuple[TestClient, Store]]:
    store = Store({}, [], [bar(index) for index in range(8)])
    app = create_app(
        Settings(environment="test", postgres_host="unused", redis_host="unused"),
        database=DatabaseStub(store),
        redis_service=Probe(),
    )
    with TestClient(app) as client:
        yield client, store


def payload(key: str = "api-run") -> dict[str, object]:
    return {
        "strategy_key": "sma_crossover",
        "parameters": {
            "short_window": 2,
            "long_window": 3,
            "quantity": "100.00",
        },
        "instrument_ids": [str(INSTRUMENT)],
        "timeframe": "MINUTE_1",
        "start_at": NOW.isoformat(),
        "end_at": (NOW + timedelta(hours=1)).isoformat(),
        "idempotency_key": key,
    }


def test_catalog_is_stable_and_hides_implementation(
    strategy_client: tuple[TestClient, Store],
) -> None:
    response = strategy_client[0].get("/api/v1/strategies/catalog")
    assert response.status_code == 200
    item = response.json()[0]
    assert item["strategy_key"] == "sma_crossover"
    assert item["parameters"][2]["default"] == "100"
    assert "class" not in item and "path" not in item


def test_catalog_detail_and_missing_error(strategy_client: tuple[TestClient, Store]) -> None:
    client, _ = strategy_client
    assert client.get("/api/v1/strategies/catalog/sma_crossover").status_code == 200
    missing = client.get("/api/v1/strategies/catalog/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "STRATEGY_NOT_FOUND"
    assert missing.json()["error"]["correlation_id"]


def test_create_run_and_idempotent_replay(strategy_client: tuple[TestClient, Store]) -> None:
    client, store = strategy_client
    first = client.post("/api/v1/strategy-runs", json=payload())
    second = client.post("/api/v1/strategy-runs", json=payload())
    assert first.status_code == second.status_code == 201
    assert first.json()["run_id"] == second.json()["run_id"]
    assert second.json()["replayed"] is True
    assert len(store.runs) == 1


def test_idempotency_conflict_is_409(strategy_client: tuple[TestClient, Store]) -> None:
    client, _ = strategy_client
    assert client.post("/api/v1/strategy-runs", json=payload()).status_code == 201
    changed = payload()
    changed["end_at"] = (NOW + timedelta(hours=2)).isoformat()
    response = client.post("/api/v1/strategy-runs", json=changed)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STRATEGY_RUN_IDEMPOTENCY_CONFLICT"


def test_invalid_time_range_has_stable_error(strategy_client: tuple[TestClient, Store]) -> None:
    body = payload()
    body["end_at"] = body["start_at"]
    response = strategy_client[0].post("/api/v1/strategy-runs", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "STRATEGY_INVALID_TIME_RANGE"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("timeframe", "WEEK_1", "STRATEGY_TIMEFRAME_NOT_SUPPORTED"),
        ("parameters", {"unknown": 1}, "STRATEGY_UNKNOWN_PARAMETER"),
        ("parameters", {"quantity": 1}, "STRATEGY_INVALID_PARAMETER"),
    ],
)
def test_controlled_request_errors(
    strategy_client: tuple[TestClient, Store], field: str, value: object, code: str
) -> None:
    body = payload()
    body[field] = value
    response = strategy_client[0].post("/api/v1/strategy-runs", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_run_and_signal_queries_are_paginated(strategy_client: tuple[TestClient, Store]) -> None:
    client, _ = strategy_client
    created = client.post("/api/v1/strategy-runs", json=payload()).json()
    runs = client.get("/api/v1/strategy-runs?page=1&page_size=10")
    detail = client.get(f"/api/v1/strategy-runs/{created['run_id']}")
    signals = client.get(f"/api/v1/strategy-runs/{created['run_id']}/signals")
    assert runs.json()["total"] == 1
    assert detail.json()["capabilities"]["creates_orders"] is False
    assert signals.status_code == 200 and "total" in signals.json()


def test_missing_run_is_404(strategy_client: tuple[TestClient, Store]) -> None:
    response = strategy_client[0].get("/api/v1/strategy-runs/11111111-2222-3333-4444-555555555555")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "STRATEGY_RUN_NOT_FOUND"


def test_signal_decimals_are_json_strings(strategy_client: tuple[TestClient, Store]) -> None:
    client, store = strategy_client
    created = client.post("/api/v1/strategy-runs", json=payload()).json()
    run_id = UUID(created["run_id"])
    store.signals.append(
        Signal(
            strategy_id=None,
            strategy_version_id=None,
            account_id=None,
            instrument_id=INSTRUMENT,
            signal_type=SignalType.ENTRY,
            side=OrderSide.BUY,
            generated_at=NOW,
            valid_until=NOW + timedelta(hours=1),
            status=SignalStatus.CREATED,
            correlation_id=store.runs[run_id].correlation_id,
            strategy_run_id=run_id,
            sequence_number=1,
            strategy_key="sma_crossover",
            strategy_version="1.0.0",
            bar_timestamp=NOW,
            target_quantity=Decimal("100.25"),
            reference_price=Decimal("12.34"),
            confidence=Decimal("0.8"),
            reason="research",
        )
    )
    item = client.get(f"/api/v1/signals?strategy_run_id={run_id}").json()["items"][0]
    assert item["quantity"] == "100.25"
    assert item["reference_price"] == "12.34"
    assert item["confidence"] == "0.8"
