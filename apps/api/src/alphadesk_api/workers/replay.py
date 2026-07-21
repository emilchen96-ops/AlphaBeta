"""Independent RT01 replay worker with PostgreSQL lease coordination."""

from __future__ import annotations

import asyncio
import logging
import socket
from datetime import timedelta
from typing import cast
from uuid import uuid4

from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.replays import (
    ReplayEventPublisher,
    ReplayService,
    ReplaySessionProcessor,
    replay_interval_seconds,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.core.logging import configure_logging
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.redis import RedisService
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.replay import ReplayEventType, ReplayRunStatus, ReplaySpeedMode
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies
from alphadesk_domain.values import utc_now

LOGGER = logging.getLogger(__name__)
HEARTBEAT_KEY = "alphadesk:replays:v1:worker:heartbeat"


class ReplayWorker:
    def __init__(
        self,
        database: DatabaseService,
        redis: RedisService,
        settings: Settings,
        *,
        owner: str | None = None,
    ) -> None:
        self._database = database
        self._redis = redis
        self._settings = settings
        self.owner = owner or f"{socket.gethostname()}:{uuid4()}"
        self._registry = StrategyRegistry()
        register_builtin_strategies(self._registry)
        self._uow_factory = cast(
            UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(database.session_factory)
        )
        self._publisher = ReplayEventPublisher(redis.client)
        self._processor = ReplaySessionProcessor(
            self._uow_factory, self._registry, settings, self._publisher
        )

    async def tick(self) -> int:
        await self._heartbeat()
        async with self._uow_factory() as uow:
            runs, _ = await uow.replay_runs.list(
                status=ReplayRunStatus.RUNNING.value, offset=0, limit=100
            )
        processed = 0
        for candidate in runs:
            if candidate.speed_mode is ReplaySpeedMode.MANUAL:
                continue
            now = utc_now()
            if (
                candidate.lease_owner is not None
                and candidate.lease_owner != self.owner
                and candidate.lease_expires_at is not None
                and candidate.lease_expires_at < now
            ):
                await self._pause_for_recovery(candidate.id)
                continue
            expires_at = now + timedelta(seconds=self._settings.replay_worker_lease_seconds)
            async with self._uow_factory() as uow:
                acquired = await uow.replay_runs.acquire_lease(
                    candidate.id, self.owner, now, expires_at
                )
                await uow.commit()
            if not acquired:
                continue
            try:
                await self._processor.process_next_session(candidate.id)
                processed += 1
            except Exception as exc:
                LOGGER.exception("Replay session failed", extra={"replay_id": str(candidate.id)})
                await self._fail(candidate.id, exc)
            interval = replay_interval_seconds(self._settings, candidate.speed_mode)
            if interval is not None:
                await asyncio.sleep(interval)
        return processed

    async def run_forever(self) -> None:
        LOGGER.info("Replay worker started", extra={"owner": self.owner})
        while True:
            try:
                await self.tick()
            except Exception:
                LOGGER.exception("Replay worker tick failed")
            await asyncio.sleep(self._settings.replay_worker_poll_ms / 1000)

    async def _heartbeat(self) -> None:
        await self._redis.client.set(
            HEARTBEAT_KEY,
            utc_now().isoformat(),
            ex=max(self._settings.replay_worker_heartbeat_seconds * 3, 15),
        )

    async def _pause_for_recovery(self, replay_id: object) -> None:
        from uuid import UUID

        if not isinstance(replay_id, UUID):
            return
        async with self._uow_factory() as uow:
            run = await uow.replay_runs.get_for_update(replay_id)
            if run is None or run.status is not ReplayRunStatus.RUNNING:
                return
            now = utc_now()
            run.transition(ReplayRunStatus.PAUSED, now)
            run.lease_owner = None
            run.lease_expires_at = None
            await uow.replay_runs.update(run)
            event = await ReplayService._append_event_in_uow(
                uow,
                run,
                ReplayEventType.RECOVERY_REQUIRED,
                ReplayService._business_time(run),
                "Worker lease expired; manual resume is required",
                {"reason": "LEASE_EXPIRED"},
            )
            await uow.commit()
        await self._publisher.publish(event)

    async def _fail(self, replay_id: object, exc: Exception) -> None:
        from uuid import UUID

        if not isinstance(replay_id, UUID):
            return
        async with self._uow_factory() as uow:
            run = await uow.replay_runs.get_for_update(replay_id)
            if run is None or run.status is not ReplayRunStatus.RUNNING:
                return
            now = utc_now()
            run.transition(ReplayRunStatus.FAILED, now)
            run.error_code = "REPLAY_SESSION_FAILED"
            run.error_message = "historical replay session failed"
            run.lease_owner = None
            run.lease_expires_at = None
            await uow.replay_runs.update(run)
            event = await ReplayService._append_event_in_uow(
                uow,
                run,
                ReplayEventType.RUN_FAILED,
                ReplayService._business_time(run),
                "Historical replay failed",
                {"error_code": run.error_code},
            )
            await uow.commit()
        del exc
        await self._publisher.publish(event)


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings)
    database = DatabaseService(settings)
    redis = RedisService(settings)
    try:
        await ReplayWorker(database, redis, settings).run_forever()
    finally:
        await redis.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(_main())
