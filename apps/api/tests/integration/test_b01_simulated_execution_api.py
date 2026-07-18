import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.entities import Instrument, Order, TradingAccount
from tests.helpers import require_b01_test_database_url
from tests.integration.test_b01_simulated_execution_pipeline import _queued_order, _seed

pytestmark = [pytest.mark.integration, pytest.mark.b01]


class FakeRedis:
    client = None

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@contextmanager
def _client() -> Iterator[tuple[TestClient, TradingAccount, Instrument, Order]]:
    url = require_b01_test_database_url()
    settings = Settings(
        environment="test",
        postgres_host=str(url.host),
        postgres_port=url.port or 5432,
        postgres_db=str(url.database),
        postgres_user=str(url.username),
        postgres_password=str(url.password),
        redis_host="unused",
    )
    seed_engine = create_async_engine(url)
    sessions = async_sessionmaker(seed_engine, expire_on_commit=False)

    async def seed() -> tuple[TradingAccount, Instrument, Order]:
        account, instrument = await _seed(sessions)
        from tests.integration.test_b01_simulated_execution_pipeline import _factory

        order = await _queued_order(_factory(sessions), account, instrument)
        await seed_engine.dispose()
        return account, instrument, order

    account, instrument, order = asyncio.run(seed())
    database = DatabaseService(settings)
    app = create_app(settings, database=database, redis_service=FakeRedis())
    with TestClient(app) as client:
        yield client, account, instrument, order


def _body(key: str) -> dict[str, object]:
    return {
        "idempotency_key": key,
        "timestamp": datetime.now(UTC).isoformat(),
        "trading_status": "TRADING",
        "last_price": "10.00",
        "bid_price": "10.00",
        "ask_price": "10.00",
        "available_volume": "100",
        "source": "B01_API_TEST",
        "is_stale": False,
    }


def test_b01_api_executes_queries_fills_and_replays_idempotently() -> None:
    with _client() as (client, account, instrument, order):
        body = _body(f"b01-api-{order.id}")
        first = client.post(f"/api/v1/orders/{order.id}/simulated-executions", json=body)
        assert first.status_code == 200
        result = first.json()
        assert result["result_status"] == "FILLED"
        assert isinstance(result["filled_quantity"], str)
        assert len(result["fill_ids"]) == 1

        replay = client.post(f"/api/v1/orders/{order.id}/simulated-executions", json=body)
        assert replay.status_code == 200
        assert replay.json()["idempotent"] is True
        assert replay.json()["execution_attempt_id"] == result["execution_attempt_id"]

        attempts = client.get(f"/api/v1/orders/{order.id}/execution-attempts").json()
        assert attempts["total"] == 1
        assert attempts["items"][0]["attempt_number"] == 1
        fills = client.get(
            "/api/v1/fills",
            params={"account_id": str(account.id), "instrument_id": str(instrument.id)},
        ).json()
        assert fills["total"] == 1
        assert fills["items"][0]["fill_id"] == result["fill_ids"][0]
        assert client.get(f"/api/v1/fills/{result['fill_ids'][0]}").status_code == 200
        integrity = client.get(f"/api/v1/orders/{order.id}/simulated-execution-integrity").json()
        assert integrity == {"order_id": str(order.id), "valid": True, "issues": []}


def test_b01_api_rejects_numeric_decimal_and_has_no_fill_write_route() -> None:
    with _client() as (client, _account, _instrument, order):
        body = _body(f"b01-api-invalid-{order.id}")
        body["last_price"] = 10.0
        invalid = client.post(f"/api/v1/orders/{order.id}/simulated-executions", json=body)
        assert invalid.status_code == 422
        assert invalid.json()["error"]["correlation_id"]
        assert client.post("/api/v1/fills", json={}).status_code == 405
        assert client.patch(f"/api/v1/fills/{order.id}", json={}).status_code == 405
