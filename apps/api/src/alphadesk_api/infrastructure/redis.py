"""Asynchronous Redis client infrastructure."""

import asyncio

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from alphadesk_api.core.config import Settings


class RedisService:
    """Own a replaceable async Redis client for M01 connectivity checks."""

    def __init__(self, settings: Settings, client: Redis | None = None) -> None:
        self._timeout = settings.dependency_timeout_seconds
        self.client = client or Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=self._timeout,
            socket_timeout=self._timeout,
            health_check_interval=30,
        )

    async def ping(self) -> bool:
        try:
            async with asyncio.timeout(self._timeout):
                return bool(await self.client.ping())
        except (TimeoutError, OSError, RedisConnectionError, RedisTimeoutError):
            return False
        except RedisError:
            return False

    async def close(self) -> None:
        await self.client.aclose()
