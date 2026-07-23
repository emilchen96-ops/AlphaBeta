"""Independent SC01-R full-market scanner worker."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import cast

from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.miniqmt_market_data import HISTORY_QUEUE_KEY
from alphadesk_api.application.scanners import FullMarketScannerProcessor
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.core.logging import configure_logging
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.redis import RedisService
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.scanners import ScannerRegistry, register_builtin_scanners
from alphadesk_domain.values import utc_now

LOGGER = logging.getLogger(__name__)
HEARTBEAT_KEY = "alphadesk:scanners:v1:worker:heartbeat"


class ScannerWorker:
    def __init__(
        self,
        database: DatabaseService,
        redis: RedisService,
        settings: Settings,
    ) -> None:
        self._database = database
        self._redis = redis
        self._settings = settings
        registry = ScannerRegistry()
        register_builtin_scanners(registry)
        self._processor = FullMarketScannerProcessor(
            cast(
                UnitOfWorkFactory,
                lambda: SqlAlchemyUnitOfWork(database.session_factory),
            ),
            registry,
            source_code=settings.authoritative_market_source,
            backfill_batch_size=settings.scanner_backfill_batch_size,
            backfill_wait_seconds=settings.scanner_backfill_wait_seconds,
            scan_batch_size=settings.scanner_scan_batch_size,
        )

    async def tick(self) -> int:
        await self._redis.client.set(
            HEARTBEAT_KEY,
            utc_now().isoformat(),
            ex=max(self._settings.scanner_worker_heartbeat_seconds * 3, 15),
        )

        async def enqueue(payload: dict[str, object]) -> None:
            await self._redis.client.rpush(
                HISTORY_QUEUE_KEY,
                json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
            )

        run_id = await self._processor.process_next(enqueue)
        return 0 if run_id is None else 1

    async def run_forever(self) -> None:
        LOGGER.info("Scanner worker started")
        while True:
            try:
                await self.tick()
            except Exception:
                LOGGER.exception("Scanner worker tick failed")
            await asyncio.sleep(self._settings.scanner_worker_poll_ms / 1000)


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings)
    database = DatabaseService(settings)
    redis = RedisService(settings)
    try:
        await ScannerWorker(database, redis, settings).run_forever()
    finally:
        await redis.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(_main())
