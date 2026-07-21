import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.ai_research_provider import (
    OpenAICompatibleResearchProvider,
)

pytestmark = [pytest.mark.unit, pytest.mark.a01]


class Probe:
    client = None

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def real_settings(*, api_key: str | None) -> Settings:
    return Settings(
        environment="test",
        postgres_host="unused",
        redis_host="unused",
        ai_research_provider="openai_compatible",
        ai_base_url="https://ai.example.test/secret-deployment/v1",
        ai_api_key=api_key,
        ai_model="research-model",
    )


def test_unavailable_provider_status_and_test_are_safe() -> None:
    app = create_app(real_settings(api_key=None), database=Probe(), redis_service=Probe())
    with TestClient(app) as client:
        status = client.get("/api/v1/ai/providers/status")
        tested = client.post("/api/v1/ai/providers/test", json={})
        rejected = client.post(
            "/api/v1/ai/providers/test",
            json={"base_url": "https://attacker.test", "api_key": "injected"},
        )
    assert status.status_code == 200
    assert status.json()["mode"] == "REAL_UNAVAILABLE"
    assert status.json()["base_url_summary"] == "https://ai.example.test"
    assert tested.status_code == 200
    assert tested.json()["error_code"] == "AI_PROVIDER_NOT_CONFIGURED"
    assert rejected.status_code == 422
    assert rejected.json()["error"]["correlation_id"]
    assert "secret-deployment" not in status.text


def test_successful_provider_connectivity_updates_status_without_returning_output() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "connected"}}]},
        )

    configured = real_settings(api_key="never-return-this-key")
    provider = OpenAICompatibleResearchProvider(
        configured,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_delay_seconds=0,
    )
    app = create_app(configured, database=Probe(), redis_service=Probe())
    app.state.ai_research_provider = provider
    try:
        with TestClient(app) as client:
            before = client.get("/api/v1/ai/providers/status")
            tested = client.post("/api/v1/ai/providers/test", json={})
            after = client.get("/api/v1/ai/providers/status")
    finally:
        asyncio.run(provider.close())
    assert before.json()["mode"] == "REAL_CONFIGURED"
    assert tested.json()["success"] is True
    assert "connected" not in tested.text
    assert after.json()["mode"] == "REAL_AVAILABLE"
    assert "never-return-this-key" not in before.text + tested.text + after.text
