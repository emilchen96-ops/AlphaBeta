import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from alphadesk_api.infrastructure.free_market_cache import QuoteCache, WorkerLeaderLock
from alphadesk_domain.enums import MarketDataQualityStatus
from alphadesk_domain.realtime_market import MarketQuote

pytestmark = pytest.mark.skipif(
    os.getenv("ALPHADESK_RUN_M04_1_INTEGRATION") != "true",
    reason="M04.1 Redis integration tests require explicit opt-in",
)


def quote(instrument_id, *, price: str, at: datetime, received_at: datetime) -> MarketQuote:
    return MarketQuote(
        instrument_id=instrument_id,
        source_code="AKSHARE_EASTMONEY",
        symbol="600000",
        quote_time=at,
        received_at=received_at,
        last_price=Decimal(price),
        quality_status=MarketDataQualityStatus.NORMAL,
    )


@pytest.mark.asyncio
async def test_quote_cache_revision_dedup_ordering_and_lock_ownership() -> None:
    client = Redis.from_url("redis://redis:6379/15", encoding="utf-8", decode_responses=True)
    await client.flushdb()
    try:
        cache = QuoteCache(client, ttl_seconds=60)
        instrument_id = uuid4()
        now = datetime.now(UTC)
        first, changed, reason = await cache.upsert(
            quote(instrument_id, price="10.00", at=now, received_at=now)
        )
        assert (first.revision.revision, changed, reason) == (1, True, "created")
        duplicate, changed, reason = await cache.upsert(
            quote(
                instrument_id,
                price="10.00",
                at=now,
                received_at=now + timedelta(seconds=1),
            )
        )
        assert (duplicate.revision.revision, changed, reason) == (1, False, "unchanged")
        older, changed, reason = await cache.upsert(
            quote(
                instrument_id,
                price="9.00",
                at=now - timedelta(seconds=1),
                received_at=now + timedelta(seconds=2),
            )
        )
        assert (older.revision.revision, changed, reason) == (1, False, "older")
        updated, changed, reason = await cache.upsert(
            quote(
                instrument_id,
                price="10.01",
                at=now + timedelta(seconds=1),
                received_at=now + timedelta(seconds=3),
            )
        )
        assert (updated.revision.revision, changed, reason) == (2, True, "updated")
        assert (await cache.get(instrument_id)).quote.last_price == Decimal("10.01")  # type: ignore[union-attr]

        owner = WorkerLeaderLock(client, "owner-a", 30)
        contender = WorkerLeaderLock(client, "owner-b", 30)
        assert await owner.acquire()
        assert not await contender.acquire()
        assert not await contender.release()
        assert await owner.renew()
        assert await owner.release()
    finally:
        await client.aclose()
