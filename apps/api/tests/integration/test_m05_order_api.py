from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.entities import Instrument, TradingAccount
from tests.helpers import require_test_database_url
from tests.integration.test_m05_order_pipeline import _seed

pytestmark = [pytest.mark.integration, pytest.mark.m05]


class FakeRedis:
    client = None

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@contextmanager
def _client() -> Iterator[tuple[TestClient, TradingAccount, Instrument]]:
    url = require_test_database_url()
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
    seed_sessions = async_sessionmaker(seed_engine, expire_on_commit=False)

    async def seed():
        result = await _seed(seed_sessions)
        await seed_engine.dispose()
        return result

    import asyncio

    account, instrument = asyncio.run(seed())
    database = DatabaseService(settings)
    app = create_app(settings, database=database, redis_service=FakeRedis())
    with TestClient(app) as client:
        yield client, account, instrument


def _body(account_id: str, instrument_id: str, key: str) -> dict[str, object]:
    return {
        "account_id": account_id,
        "instrument_id": instrument_id,
        "side": "BUY",
        "order_type": "LIMIT",
        "time_in_force": "DAY",
        "requested_quantity": "1000",
        "limit_price": "12.34",
        "expires_at": None,
        "idempotency_key": key,
    }


def test_order_api_create_list_detail_timeline_confirm_and_cancel() -> None:
    with _client() as (client, account, instrument):
        first = client.post(
            "/api/v1/orders",
            json=_body(str(account.id), str(instrument.id), f"api-create-{account.id}"),
        )
        assert first.status_code == 201
        order = first.json()
        assert order["status"] == "WAITING_CONFIRMATION"
        assert order["row_version"] == 2

        listing = client.get("/api/v1/orders", params={"account_id": str(account.id)})
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        assert client.get(f"/api/v1/orders/{order['id']}").status_code == 200
        assert len(client.get(f"/api/v1/orders/{order['id']}/timeline").json()) == 4

        confirmed = client.post(
            f"/api/v1/orders/{order['id']}/confirm",
            json={"idempotency_key": f"api-confirm-{order['id']}", "expected_order_version": 2},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "QUEUED"
        assert confirmed.json()["commands"][0]["status"] == "PENDING"
        assert confirmed.json()["outbox"][0]["status"] == "PENDING"

        second = client.post(
            "/api/v1/orders",
            json=_body(str(account.id), str(instrument.id), f"api-cancel-create-{account.id}"),
        ).json()
        cancelled = client.post(
            f"/api/v1/orders/{second['id']}/cancel",
            json={"idempotency_key": f"api-cancel-{second['id']}", "expected_order_version": 2},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"


def test_order_api_rejects_numeric_decimal_and_unsafe_mutation_routes() -> None:
    with _client() as (client, account, instrument):
        body = _body(str(account.id), str(instrument.id), f"api-invalid-{account.id}")
        body["requested_quantity"] = 1000
        invalid = client.post("/api/v1/orders", json=body)
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
        assert (
            client.patch(f"/api/v1/orders/{account.id}", json={"status": "FILLED"}).status_code
            == 405
        )
        assert client.post(f"/api/v1/orders/{account.id}/fills", json={}).status_code == 404
