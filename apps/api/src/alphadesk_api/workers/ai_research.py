"""Durable TA01 multi-agent AI research worker."""

from __future__ import annotations

import asyncio
import logging
from typing import cast

from alphadesk_api.application.ai_workbench import AIResearchTaskProcessor
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.core.logging import configure_logging
from alphadesk_api.infrastructure.ai_research_provider import (
    OpenAICompatibleResearchProvider,
    build_ai_research_provider,
)
from alphadesk_api.infrastructure.ai_workbench_provider import (
    build_ai_workbench_provider,
)
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.redis import RedisService
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.values import utc_now

LOGGER = logging.getLogger(__name__)
HEARTBEAT_KEY = "alphadesk:ai-research:v1:worker:heartbeat"


class AIResearchWorker:
    def __init__(
        self,
        database: DatabaseService,
        redis: RedisService,
        settings: Settings,
    ) -> None:
        self._redis = redis
        self._settings = settings
        self._base_provider = build_ai_research_provider(settings)
        provider = build_ai_workbench_provider(self._base_provider)
        factory = cast(
            UnitOfWorkFactory,
            lambda: SqlAlchemyUnitOfWork(database.session_factory),
        )
        self._processor = AIResearchTaskProcessor(
            factory,
            provider,
            stale_seconds=settings.ai_research_task_stale_seconds,
        )

    async def tick(self) -> int:
        try:
            await self._redis.client.set(
                HEARTBEAT_KEY,
                utc_now().isoformat(),
                ex=max(15, int(self._settings.ai_research_worker_poll_ms / 100)),
            )
        except Exception:
            LOGGER.warning("AI research worker heartbeat unavailable", exc_info=True)
        return 0 if await self._processor.run_once() is None else 1

    async def run_forever(self) -> None:
        LOGGER.info("AI research worker started")
        while True:
            try:
                processed = await self.tick()
            except Exception:
                LOGGER.exception("AI research worker tick failed")
                processed = 0
            if processed == 0:
                await asyncio.sleep(self._settings.ai_research_worker_poll_ms / 1000)
            else:
                await asyncio.sleep(0)

    async def close(self) -> None:
        if isinstance(self._base_provider, OpenAICompatibleResearchProvider):
            await self._base_provider.close()


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings)
    database = DatabaseService(settings)
    redis = RedisService(settings)
    worker = AIResearchWorker(database, redis, settings)
    try:
        await worker.run_forever()
    finally:
        await worker.close()
        await redis.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(_main())
