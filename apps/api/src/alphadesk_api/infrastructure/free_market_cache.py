"""Redis-only quote cache, worker coordination and realtime pub/sub."""

import hashlib
import json
from collections.abc import Awaitable
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis

from alphadesk_domain.enums import (
    MarketDataQualityStatus,
    MarketProviderTier,
    MarketProviderUsage,
)
from alphadesk_domain.realtime_market import MarketQuote, MarketQuoteSnapshot, QuoteRevision

QUOTE_CHANNEL = "alphadesk:market:v1:events"
LEADER_KEY = "alphadesk:market:v1:worker:leader"
HEARTBEAT_KEY = "alphadesk:market:v1:worker:heartbeat"
STATUS_KEY = "alphadesk:market:v1:source:status"
SUBSCRIPTIONS_KEY = "alphadesk:market:v1:subscriptions"

UPSERT_QUOTE_LUA = """
local current = redis.call('GET', KEYS[1])
if current then
  local old = cjson.decode(current)
  if ARGV[2] ~= '' and old.quote_time ~= cjson.null and old.quote_time > ARGV[2] then
    return {0, tonumber(old.revision), 'older'}
  end
  if old.payload_hash == ARGV[1] then
    local refreshed = cjson.decode(ARGV[3])
    refreshed.revision = tonumber(old.revision)
    refreshed.payload_hash = ARGV[1]
    redis.call('SET', KEYS[1], cjson.encode(refreshed), 'EX', tonumber(ARGV[4]))
    return {0, tonumber(old.revision), 'unchanged'}
  end
  local next_revision = tonumber(old.revision) + 1
  local payload = cjson.decode(ARGV[3])
  payload.revision = next_revision
  payload.payload_hash = ARGV[1]
  redis.call('SET', KEYS[1], cjson.encode(payload), 'EX', tonumber(ARGV[4]))
  return {1, next_revision, 'updated'}
end
local payload = cjson.decode(ARGV[3])
payload.revision = 1
payload.payload_hash = ARGV[1]
redis.call('SET', KEYS[1], cjson.encode(payload), 'EX', tonumber(ARGV[4]))
return {1, 1, 'created'}
"""

RENEW_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return 0
"""

RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def _json_default(value: object) -> str:
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if hasattr(value, "value"):
        return str(value.value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def quote_payload(quote: MarketQuote) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(json.dumps(asdict(quote), default=_json_default, sort_keys=True)),
    )


class QuoteCache:
    def __init__(self, client: Redis, ttl_seconds: int = 120) -> None:
        self._client = client
        self._ttl = ttl_seconds

    @staticmethod
    def key(instrument_id: UUID) -> str:
        return f"market:quote:{instrument_id}"

    async def upsert(self, quote: MarketQuote) -> tuple[MarketQuoteSnapshot, bool, str]:
        payload = quote_payload(quote)
        stable_payload = {key: value for key, value in payload.items() if key != "received_at"}
        stable_canonical = json.dumps(
            stable_payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        payload_hash = hashlib.sha256(stable_canonical.encode()).hexdigest()
        canonical = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        quote_time = "" if quote.quote_time is None else quote.quote_time.isoformat()
        result = await cast(
            Awaitable[Any],
            self._client.eval(
                UPSERT_QUOTE_LUA,
                1,
                self.key(quote.instrument_id),
                payload_hash,
                quote_time,
                canonical,
                str(self._ttl),
            ),
        )
        changed, revision, reason = int(result[0]), int(result[1]), str(result[2])
        snapshot = MarketQuoteSnapshot(
            quote=quote,
            revision=QuoteRevision(
                instrument_id=quote.instrument_id,
                revision=revision,
                payload_hash=payload_hash,
                quote_time=quote.quote_time,
            ),
        )
        if changed:
            event = {
                "schema_version": 1,
                "type": "quote_update",
                "event_type": "quote_updated",
                "instrument_id": str(quote.instrument_id),
                "market_time": quote.quote_time,
                "occurred_at": datetime.now(UTC),
                **payload,
                "revision": revision,
            }
            await self._client.publish(QUOTE_CHANNEL, json.dumps(event, default=_json_default))
        return snapshot, bool(changed), reason

    async def get(self, instrument_id: UUID) -> MarketQuoteSnapshot | None:
        raw = await self._client.get(self.key(instrument_id))
        return None if raw is None else self._decode(str(raw))

    async def get_many(self, instrument_ids: list[UUID]) -> list[MarketQuoteSnapshot]:
        if not instrument_ids:
            return []
        raws = await self._client.mget([self.key(item) for item in instrument_ids])
        return [self._decode(str(raw)) for raw in raws if raw is not None]

    @staticmethod
    def _decode(raw: str) -> MarketQuoteSnapshot:
        data = json.loads(raw)
        quote_time = data.get("quote_time")
        quote = MarketQuote(
            instrument_id=UUID(data["instrument_id"]),
            source_code=data["source_code"],
            symbol=data["symbol"],
            quote_time=None if quote_time is None else datetime.fromisoformat(quote_time),
            received_at=datetime.fromisoformat(data["received_at"]),
            last_price=Decimal(data["last_price"]),
            previous_close=Decimal(data["previous_close"]) if data.get("previous_close") else None,
            open=Decimal(data["open"]) if data.get("open") else None,
            high=Decimal(data["high"]) if data.get("high") else None,
            low=Decimal(data["low"]) if data.get("low") else None,
            volume=Decimal(data["volume"]) if data.get("volume") else None,
            amount=Decimal(data["amount"]) if data.get("amount") else None,
            bid_price_1=Decimal(data["bid_price_1"]) if data.get("bid_price_1") else None,
            bid_volume_1=Decimal(data["bid_volume_1"]) if data.get("bid_volume_1") else None,
            ask_price_1=Decimal(data["ask_price_1"]) if data.get("ask_price_1") else None,
            ask_volume_1=Decimal(data["ask_volume_1"]) if data.get("ask_volume_1") else None,
            quality_status=MarketDataQualityStatus(data["quality_status"]),
            provider_tier=MarketProviderTier(data["provider_tier"]),
            usage=tuple(MarketProviderUsage(item) for item in data["usage"]),
            quality_flags=data.get("quality_flags", {}),
        )
        return MarketQuoteSnapshot(
            quote=quote,
            revision=QuoteRevision(
                instrument_id=quote.instrument_id,
                revision=int(data["revision"]),
                payload_hash=data["payload_hash"],
                quote_time=quote.quote_time,
            ),
        )


class WorkerLeaderLock:
    def __init__(self, client: Redis, owner: str, ttl_seconds: int) -> None:
        self._client = client
        self.owner = owner
        self._ttl = ttl_seconds

    async def acquire(self) -> bool:
        return bool(await self._client.set(LEADER_KEY, self.owner, nx=True, ex=self._ttl))

    async def renew(self) -> bool:
        return bool(
            await cast(
                Awaitable[Any],
                self._client.eval(RENEW_LOCK_LUA, 1, LEADER_KEY, self.owner, str(self._ttl)),
            )
        )

    async def release(self) -> bool:
        return bool(
            await cast(
                Awaitable[Any],
                self._client.eval(RELEASE_LOCK_LUA, 1, LEADER_KEY, self.owner),
            )
        )


async def write_json(
    client: Redis, key: str, value: dict[str, Any], ttl: int | None = None
) -> None:
    payload = json.dumps(value, default=_json_default, separators=(",", ":"))
    if ttl is None:
        await client.set(key, payload)
    else:
        await client.set(key, payload, ex=ttl)


async def read_json(client: Redis, key: str) -> dict[str, Any] | None:
    raw = await client.get(key)
    return None if raw is None else dict(json.loads(str(raw)))
