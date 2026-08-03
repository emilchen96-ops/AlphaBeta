"""Durable TA01 multi-agent AI research worker."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
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
from alphadesk_api.infrastructure.tradingagents_adapter import build_tradingagents_engine
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
        engine = (
            build_tradingagents_engine(settings)
            if settings.ai_research_engine == "tradingagents"
            else None
        )
        factory = cast(
            UnitOfWorkFactory,
            lambda: SqlAlchemyUnitOfWork(database.session_factory),
        )
        self._processor = AIResearchTaskProcessor(
            factory,
            provider,
            engine=engine,
            stale_seconds=settings.ai_research_task_stale_seconds,
        )

    async def tick(self) -> int:
        return 0 if await self._processor.run_once() is None else 1

    async def _heartbeat_forever(self) -> None:
        """Keep liveness independent from a long blocking Graph execution."""

        interval = max(
            5,
            min(30, int(self._settings.ai_research_worker_poll_ms / 1000) or 5),
        )
        while True:
            try:
                await self._redis.client.set(
                    HEARTBEAT_KEY,
                    utc_now().isoformat(),
                    ex=max(45, interval * 3),
                )
            except Exception:
                LOGGER.warning("AI research worker heartbeat unavailable", exc_info=True)
            await asyncio.sleep(interval)

    async def run_forever(self) -> None:
        LOGGER.info("AI research worker started")
        heartbeat = asyncio.create_task(self._heartbeat_forever())
        try:
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
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

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
