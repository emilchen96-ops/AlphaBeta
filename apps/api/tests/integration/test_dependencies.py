import os

import pytest

from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.redis import RedisService

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("ALPHADESK_RUN_INTEGRATION") != "true",
    reason="Set ALPHADESK_RUN_INTEGRATION=true with isolated services",
)
async def test_postgresql_and_redis_are_reachable() -> None:
    settings = Settings()
    database = DatabaseService(settings)
    redis = RedisService(settings)
    try:
        assert await database.ping() is True
        assert await redis.ping() is True
    finally:
        await redis.close()
        await database.close()
