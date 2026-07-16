import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.free_market_cache import QuoteCache
from alphadesk_api.infrastructure.redis import RedisService
from alphadesk_domain.enums import MarketDataQualityStatus
from alphadesk_domain.realtime_market import MarketQuote

pytestmark = pytest.mark.skipif(
    os.getenv("ALPHADESK_RUN_M04_1_INTEGRATION") != "true",
    reason="M04.1 realtime API tests require explicit opt-in",
)


class FakeDatabase:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


def test_latest_quote_http_and_websocket_snapshot_contract() -> None:
    settings = Settings(
        environment="test",
        postgres_host="unused",
        redis_host="redis",
        redis_db=14,
        dependency_timeout_seconds=2,
    )
    instrument_id = uuid4()

    async def prepare() -> None:
        client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        await client.flushdb()
        await QuoteCache(client, 60).upsert(
            MarketQuote(
                instrument_id=instrument_id,
                source_code="AKSHARE_EASTMONEY",
                symbol="600000",
                quote_time=None,
                received_at=datetime.now(UTC),
                last_price=Decimal("10.25"),
                quality_status=MarketDataQualityStatus.INCOMPLETE,
                quality_flags={"MISSING_UPSTREAM_QUOTE_TIME": True},
            )
        )
        await client.aclose()

    asyncio.run(prepare())
    app = create_app(settings, database=FakeDatabase(), redis_service=RedisService(settings))
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/market-data/quotes/latest",
            params=[("instrument_ids", str(instrument_id))],
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["schema_version"] == 1
        assert payload["items"][0]["last_price"] == "10.25"
        assert payload["items"][0]["quote_time"] is None

        with client.websocket_connect("/ws/v1/market-data") as websocket:
            assert websocket.receive_json()["type"] == "connected"
            websocket.send_json(
                {
                    "schema_version": 1,
                    "type": "hello",
                    "instrument_ids": [str(instrument_id)],
                }
            )
            assert websocket.receive_json()["type"] == "subscription_ack"
            snapshot = websocket.receive_json()
            assert snapshot["type"] == "quote_snapshot"
            assert snapshot["items"][0]["revision"] == 1
            websocket.send_json({"schema_version": 1, "type": "ping"})
            assert websocket.receive_json()["type"] == "pong"
