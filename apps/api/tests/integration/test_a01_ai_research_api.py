import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.database import DatabaseService
from tests.helpers import require_test_database_url
from tests.integration.test_a01_ai_research import seed_information

pytestmark = [pytest.mark.integration, pytest.mark.a01]


class FakeRedis:
    client = None

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@contextmanager
def client() -> Iterator[tuple[TestClient, UUID, UUID]]:
    url = require_test_database_url()
    settings = Settings(
        environment="test",
        postgres_host=str(url.host),
        postgres_port=url.port or 5432,
        postgres_db=str(url.database),
        postgres_user=str(url.username),
        postgres_password=str(url.password),
        redis_host="unused",
        ai_research_provider="fake",
    )
    seed_engine = create_async_engine(url)
    sessions = async_sessionmaker(seed_engine, expire_on_commit=False)

    async def seed() -> tuple[UUID, UUID]:
        result = await seed_information(sessions)
        await seed_engine.dispose()
        return result

    item_id, event_id = asyncio.run(seed())
    database = DatabaseService(settings)
    app = create_app(settings, database=database, redis_service=FakeRedis())
    with TestClient(app) as test_client:
        yield test_client, item_id, event_id


def body(item_id: UUID, event_id: UUID, key: str) -> dict[str, object]:
    return {
        "analysis_type": "EVENT_SUMMARY",
        "event_ids": [str(event_id)],
        "information_item_ids": [str(item_id)],
        "instrument_ids": [],
        "question": None,
        "idempotency_key": key,
    }


def test_ai_api_status_create_replay_queries_evidence_and_integrity() -> None:
    with client() as (test_client, item_id, event_id):
        provider = test_client.get("/api/v1/ai/providers/status")
        assert provider.status_code == 200
        assert provider.json()["provider_key"] == "fake"
        assert provider.json()["real_provider_available"] is False

        request_body = body(item_id, event_id, f"a01-api-{uuid4()}")
        created = test_client.post("/api/v1/ai/analyses", json=request_body)
        assert created.status_code == 201
        payload = created.json()
        assert payload["status"] == "COMPLETED"
        assert payload["insight"]["label"] == "AI生成，仅供研究参考。"  # noqa: RUF001
        assert payload["insight"]["evidence"][0]["information_item_id"] == str(item_id)
        assert payload["capabilities"]["creates_orders"] is False
        analysis_id = payload["analysis_id"]
        insight_id = payload["insight"]["insight_id"]

        replay = test_client.post("/api/v1/ai/analyses", json=request_body)
        assert replay.status_code == 201
        assert replay.json()["replayed"] is True
        assert replay.json()["analysis_id"] == analysis_id
        assert test_client.get("/api/v1/ai/analyses").json()["total"] >= 1
        assert test_client.get(f"/api/v1/ai/analyses/{analysis_id}").status_code == 200
        insight = test_client.get(f"/api/v1/research-insights/{insight_id}")
        assert insight.status_code == 200
        assert insight.json()["evidence"][0]["evidence_text"]
        integrity = test_client.get(f"/api/v1/ai/analyses/{analysis_id}/integrity")
        assert integrity.json() == {
            "analysis_id": analysis_id,
            "valid": True,
            "issues": [],
        }


@pytest.mark.parametrize("forbidden", ["api_key", "provider_secret", "order", "signal", "trade"])
def test_ai_api_forbids_secrets_and_trading_fields(forbidden: str) -> None:
    with client() as (test_client, item_id, event_id):
        request_body = body(item_id, event_id, f"a01-api-invalid-{uuid4()}")
        request_body[forbidden] = "must-not-pass"
        rejected = test_client.post("/api/v1/ai/analyses", json=request_body)
        assert rejected.status_code == 422
        assert rejected.json()["error"]["correlation_id"]
