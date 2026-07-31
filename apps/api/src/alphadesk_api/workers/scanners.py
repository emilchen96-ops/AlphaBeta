"""Independent SC01-R full-market scanner worker."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import cast
from uuid import UUID

from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.miniqmt_market_data import (
    AGENT_STATUS_KEY,
    HISTORY_QUEUE_KEY,
)
from alphadesk_api.application.scanners import FullMarketScannerProcessor
from alphadesk_api.application.screenings import (
    RuleBasedScreeningProcessor,
    ScreeningDataPreparationService,
    ScreeningOrchestrationService,
    UnifiedScannerWorkerProcessor,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.core.logging import configure_logging
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.redis import RedisService
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.scanners import ScannerRegistry, register_builtin_scanners
from alphadesk_domain.screening import builtin_condition_catalog
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
        factory = cast(
            UnitOfWorkFactory,
            lambda: SqlAlchemyUnitOfWork(database.session_factory),
        )
        legacy_processor = FullMarketScannerProcessor(
            factory,
            registry,
            source_code=settings.authoritative_market_source,
            backfill_batch_size=settings.scanner_backfill_batch_size,
            backfill_wait_seconds=settings.scanner_backfill_wait_seconds,
            scan_batch_size=settings.scanner_scan_batch_size,
        )
        screening_processor = RuleBasedScreeningProcessor(
            factory,
            builtin_condition_catalog(),
            source_code=settings.authoritative_market_source,
            batch_size=settings.scanner_scan_batch_size,
        )
        preparation_service = ScreeningDataPreparationService(
            factory,
            builtin_condition_catalog(),
            source_code=settings.authoritative_market_source,
            warmup_buffer=settings.screening_warmup_buffer_sessions,
            maximum_extension_sessions=settings.screening_max_extension_sessions,
            maximum_stale_sessions=settings.screening_max_stale_sessions,
            backfill_batch_size=settings.scanner_backfill_batch_size,
            backfill_wait_seconds=settings.scanner_backfill_wait_seconds,
        )
        self._processor = UnifiedScannerWorkerProcessor(
            factory,
            legacy_processor,
            screening_processor,
            ScreeningOrchestrationService(
                preparation_service,
                screening_processor,
            ),
        )

    async def tick(self) -> int:
        try:
            await self._redis.client.set(
                HEARTBEAT_KEY,
                utc_now().isoformat(),
                ex=max(self._settings.scanner_worker_heartbeat_seconds * 3, 15),
            )
        except Exception:
            LOGGER.warning(
                "Scanner worker heartbeat unavailable; continuing with PostgreSQL tasks",
                exc_info=True,
            )

        async def enqueue(payload: dict[str, object]) -> int:
            raw_status = await self._redis.client.get(AGENT_STATUS_KEY)
            try:
                agent_status = json.loads(str(raw_status)) if raw_status is not None else {}
            except (TypeError, ValueError):
                agent_status = {}
            if agent_status.get("state") != "CONNECTED":
                raise RuntimeError("MINIQMT_AGENT_NOT_CONNECTED")
            return int(
                await self._redis.client.rpush(
                    HISTORY_QUEUE_KEY,
                    json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                )
            )

        async def pending_backfill_batches(scan_run_id: UUID) -> int | None:
            try:
                raw_items = await self._redis.client.lrange(HISTORY_QUEUE_KEY, 0, -1)
            except Exception:
                LOGGER.warning(
                    "MiniQMT history queue status unavailable; using bounded wait fallback",
                    exc_info=True,
                )
                return None
            pending = 0
            for raw in raw_items:
                try:
                    payload = json.loads(
                        raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    )
                except (UnicodeDecodeError, TypeError, ValueError):
                    continue
                if isinstance(payload, dict) and str(payload.get("scan_run_id")) == str(
                    scan_run_id
                ):
                    pending += 1
            return pending

        run_id = await self._processor.process_next(
            enqueue,
            pending_backfill_batches,
        )
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
