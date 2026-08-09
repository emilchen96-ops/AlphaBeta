"""Worker for durable independent per-instrument backtest batches."""

from __future__ import annotations

import asyncio
import logging
from typing import cast

from alphadesk_api.application.backtest_batches import BacktestBatchProcessor
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.miniqmt_market_data import enqueue_history_request
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.core.logging import configure_logging
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.redis import RedisService
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies
from alphadesk_domain.values import utc_now

LOGGER = logging.getLogger(__name__)
HEARTBEAT_KEY = "alphadesk:backtest-batches:v1:worker:heartbeat"


class BacktestBatchWorker:
    def __init__(
        self,
        database: DatabaseService,
        redis: RedisService,
        settings: Settings,
    ) -> None:
        self._redis = redis
        self._settings = settings
        registry = StrategyRegistry()
        register_builtin_strategies(registry)
        factory = cast(
            UnitOfWorkFactory,
            lambda: SqlAlchemyUnitOfWork(database.session_factory),
        )
        async def enqueue(payload: dict[str, object]) -> int:
            return await enqueue_history_request(self._redis.client, payload)

        self._processor = BacktestBatchProcessor(
            factory,
            registry,
            settings,
            enqueue,
        )

    async def tick(self) -> int:
        try:
            await self._redis.client.set(
                HEARTBEAT_KEY,
                utc_now().isoformat(),
                ex=max(15, int(self._settings.backtest_batch_worker_poll_ms / 100)),
            )
        except Exception:
            LOGGER.warning("Backtest batch worker heartbeat unavailable", exc_info=True)
        return 0 if await self._processor.process_next() is None else 1

    async def run_forever(self) -> None:
        LOGGER.info("Backtest batch worker started")
        while True:
            try:
                processed = await self.tick()
            except Exception:
                LOGGER.exception("Backtest batch worker tick failed")
                processed = 0
            if processed == 0:
                await asyncio.sleep(self._settings.backtest_batch_worker_poll_ms / 1000)
            else:
                await asyncio.sleep(0)


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings)
    database = DatabaseService(settings)
    redis = RedisService(settings)
    try:
        await BacktestBatchWorker(database, redis, settings).run_forever()
    finally:
        await redis.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(_main())
