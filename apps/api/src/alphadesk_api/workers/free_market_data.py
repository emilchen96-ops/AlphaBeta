"""Independent free market-data worker; never started by FastAPI lifespan."""

import asyncio
import json
import logging
import os
import socket
from datetime import UTC, datetime, time, timedelta
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from alphadesk_api.application.catalog import InstrumentCatalogService
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.free_market_data import (
    FreeQuoteIngestionService,
    MarketSubscriptionService,
)
from alphadesk_api.application.market_data import MarketDataIngestionService
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.free_market_cache import (
    HEARTBEAT_KEY,
    QUOTE_CHANNEL,
    STATUS_KEY,
    SUBSCRIPTIONS_KEY,
    QuoteCache,
    WorkerLeaderLock,
    write_json,
)
from alphadesk_api.infrastructure.market_data.akshare_eastmoney import (
    AkShareEastMoneyRealtimeAdapter,
)
from alphadesk_api.infrastructure.provider_resilience import ProviderCallGuard
from alphadesk_api.infrastructure.redis import RedisService
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketSyncStatus,
    MarketTimeframe,
    SubscriptionReason,
    SyncTriggerType,
)
from alphadesk_domain.market import MarketSyncRun
from alphadesk_domain.realtime_market import MarketSubscriptionSet

LOGGER = logging.getLogger("alphadesk.free_market_worker")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def is_cn_a_active_session(now: datetime) -> bool:
    """Return whether ``now`` is inside the regular CN A-share sessions.

    Public holidays require a future calendar adapter; weekends and the lunch
    break are still handled locally so a disabled market cannot trigger a
    high-frequency free-source loop.
    """

    local = now.astimezone(SHANGHAI)
    if local.weekday() >= 5:
        return False
    current = local.timetz().replace(tzinfo=None)
    return time(9, 30) <= current < time(11, 30) or time(13, 0) <= current < time(15, 0)


class FreeMarketDataWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = DatabaseService(settings)
        self.redis = RedisService(settings)
        self.adapter = AkShareEastMoneyRealtimeAdapter()
        self.guard = ProviderCallGuard(
            min_interval_seconds=settings.free_market_provider_min_interval_seconds,
            max_retries=settings.free_market_provider_max_retries,
            failure_threshold=settings.free_market_circuit_failure_threshold,
            open_seconds=settings.free_market_circuit_open_seconds,
        )
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
        self.lock = WorkerLeaderLock(
            self.redis.client, self.owner, settings.free_market_worker_lock_ttl_seconds
        )
        self.quote_cache = QuoteCache(self.redis.client, settings.free_market_quote_ttl_seconds)
        self._last_minute_sync_at: datetime | None = None
        self._renewal_task: asyncio.Task[None] | None = None

    async def prepare(self) -> None:
        uow_factory = cast(UnitOfWorkFactory, self.database.unit_of_work)
        catalog = InstrumentCatalogService(uow_factory)
        await catalog.ensure_source(
            source_code=self.adapter.source_code,
            name="AKShare EastMoney free snapshot",
            status=MarketDataSourceStatus.ACTIVE,
            priority=20,
            supports_realtime=True,
            supported_timeframes=(MarketTimeframe.MINUTE_1,),
            provider_tier=MarketProviderTier.FREE_BEST_EFFORT,
            supports_quotes=True,
            supports_recent_minute_bars=True,
        )
        await catalog.ensure_source(
            source_code="BAOSTOCK",
            name="BaoStock free historical data",
            status=MarketDataSourceStatus.ACTIVE,
            priority=30,
            supports_realtime=False,
            supported_timeframes=(
                MarketTimeframe.DAY_1,
                MarketTimeframe.MINUTE_5,
                MarketTimeframe.MINUTE_15,
                MarketTimeframe.MINUTE_30,
                MarketTimeframe.MINUTE_60,
            ),
            provider_tier=MarketProviderTier.FREE_BEST_EFFORT,
            supports_quotes=False,
            supports_recent_minute_bars=False,
        )

    async def _renew_leader_lock(self) -> None:
        interval = max(5.0, self.settings.free_market_worker_lock_ttl_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            if not await self.lock.renew():
                raise RuntimeError("free market worker lost the leader lock")

    def _assert_leader_held(self) -> None:
        if self._renewal_task is not None and self._renewal_task.done():
            self._renewal_task.result()

    async def _sync_recent_minute_bars(
        self,
        uow_factory: UnitOfWorkFactory,
        subscriptions: MarketSubscriptionSet,
        now: datetime,
    ) -> dict[str, int] | None:
        if (
            self._last_minute_sync_at is not None
            and (now - self._last_minute_sync_at).total_seconds()
            < self.settings.free_market_minute_sync_seconds
        ):
            return None

        focused = sorted(
            subscriptions.items,
            key=lambda item: (
                SubscriptionReason.POSITION not in item.reasons,
                item.symbol,
            ),
        )[: self.settings.free_market_minute_max_symbols]
        if not focused:
            return None

        completed_minute = now.astimezone(SHANGHAI).replace(second=0, microsecond=0) - timedelta(
            minutes=1
        )
        end = completed_minute.astimezone(UTC)
        start = end - timedelta(minutes=self.settings.free_market_minute_lookback_minutes)
        ingestion = MarketDataIngestionService(uow_factory)
        received = inserted = updated = rejected = 0

        for subscription in focused:
            self._assert_leader_held()
            symbol = subscription.symbol

            async def sync_one(symbol: str = symbol) -> MarketSyncRun:
                run = await ingestion.sync_bars(
                    adapter=self.adapter,
                    symbols=[symbol],
                    timeframe=MarketTimeframe.MINUTE_1,
                    adjustment=AdjustmentType.NONE,
                    start=start,
                    end=end,
                    trigger_type=SyncTriggerType.SCHEDULED,
                    correlation_id=uuid4(),
                )
                if run.status is MarketSyncStatus.FAILED:
                    raise RuntimeError(run.error_summary or "minute-bar sync failed")
                return run

            run = await self.guard.call(sync_one)
            received += run.total_received
            inserted += run.total_inserted
            updated += run.total_updated
            rejected += run.total_rejected

        self._last_minute_sync_at = now
        await self.redis.client.publish(
            QUOTE_CHANNEL,
            json.dumps(
                {
                    "schema_version": 1,
                    "type": "minute_bar_updated",
                    "symbols": [item.symbol for item in focused],
                    "received": received,
                    "inserted": inserted,
                    "updated": updated,
                    "rejected": rejected,
                    "completed_at": now.isoformat(),
                }
            ),
        )
        return {
            "received": received,
            "inserted": inserted,
            "updated": updated,
            "rejected": rejected,
        }

    async def run_once(self) -> dict[str, object]:
        now = datetime.now(UTC)
        if not self.settings.free_market_data_enabled:
            status = {"enabled": False, "state": "DISABLED", "checked_at": now.isoformat()}
            await write_json(self.redis.client, STATUS_KEY, status)
            await self.redis.client.publish(
                QUOTE_CHANNEL,
                json.dumps({"schema_version": 1, "type": "source_status", **status}),
            )
            return status
        if not await self.lock.acquire():
            return {"enabled": True, "state": "SKIPPED_NOT_LEADER", "checked_at": now.isoformat()}
        renewal_task = asyncio.create_task(self._renew_leader_lock())
        self._renewal_task = renewal_task
        try:
            await self.prepare()
            uow_factory = cast(UnitOfWorkFactory, self.database.unit_of_work)
            subscriptions = await MarketSubscriptionService(uow_factory).resolve()
            await write_json(
                self.redis.client,
                SUBSCRIPTIONS_KEY,
                {
                    "revision": subscriptions.revision,
                    "generated_at": subscriptions.generated_at.isoformat(),
                    "count": len(subscriptions.items),
                    "items": [
                        {
                            "instrument_id": str(item.instrument_id),
                            "symbol": item.symbol,
                            "reasons": [reason.value for reason in item.reasons],
                        }
                        for item in subscriptions.items
                    ],
                },
            )
            if not subscriptions.items:
                status = {
                    "enabled": True,
                    "state": "IDLE_NO_SUBSCRIPTIONS",
                    "source_code": self.adapter.source_code,
                    "circuit_state": self.guard.state.value,
                    "consecutive_failures": self.guard.consecutive_failures,
                    "requested_count": 0,
                    "received_count": 0,
                    "changed_count": 0,
                    "rejected_count": 0,
                    "checked_at": datetime.now(UTC).isoformat(),
                    "error_summary": None,
                }
                await write_json(self.redis.client, STATUS_KEY, status)
                await self.redis.client.publish(
                    QUOTE_CHANNEL,
                    json.dumps({"schema_version": 1, "type": "source_status", **status}),
                )
                return status
            if not is_cn_a_active_session(now):
                status = {
                    "enabled": True,
                    "state": "MARKET_CLOSED",
                    "source_code": self.adapter.source_code,
                    "circuit_state": self.guard.state.value,
                    "consecutive_failures": self.guard.consecutive_failures,
                    "requested_count": 0,
                    "received_count": 0,
                    "changed_count": 0,
                    "rejected_count": 0,
                    "checked_at": datetime.now(UTC).isoformat(),
                    "error_summary": None,
                }
                await write_json(self.redis.client, STATUS_KEY, status)
                await self.redis.client.publish(
                    QUOTE_CHANNEL,
                    json.dumps({"schema_version": 1, "type": "source_status", **status}),
                )
                return status
            ingestion = FreeQuoteIngestionService(uow_factory, self.adapter, self.quote_cache)
            try:
                self._assert_leader_held()
                run = await self.guard.call(lambda: ingestion.run(subscriptions))
                self._assert_leader_held()
                minute_summary = await self._sync_recent_minute_bars(
                    uow_factory, subscriptions, now
                )
            except Exception as exc:
                status = {
                    "enabled": True,
                    "state": "FAILED",
                    "source_code": self.adapter.source_code,
                    "circuit_state": self.guard.state.value,
                    "consecutive_failures": self.guard.consecutive_failures,
                    "checked_at": datetime.now(UTC).isoformat(),
                    "error_summary": f"{type(exc).__name__}: {exc}"[:1000],
                }
                await write_json(self.redis.client, STATUS_KEY, status)
                await self.redis.client.publish(
                    QUOTE_CHANNEL,
                    json.dumps({"schema_version": 1, "type": "source_status", **status}),
                )
                return status
            status = {
                "enabled": True,
                "state": run.status.value,
                "source_code": self.adapter.source_code,
                "circuit_state": self.guard.state.value,
                "consecutive_failures": self.guard.consecutive_failures,
                "requested_count": run.requested_count,
                "received_count": run.received_count,
                "changed_count": run.changed_count,
                "rejected_count": run.rejected_count,
                "checked_at": datetime.now(UTC).isoformat(),
                "error_summary": run.error_summary,
            }
            if minute_summary is not None:
                status["minute_bars"] = minute_summary
            await write_json(self.redis.client, STATUS_KEY, status)
            return status
        finally:
            renewal_task.cancel()
            await asyncio.gather(renewal_task, return_exceptions=True)
            self._renewal_task = None
            await self.lock.release()

    async def run_forever(self) -> None:
        while True:
            status: dict[str, object] = {"state": "FAILED"}
            try:
                status = await self.run_once()
                LOGGER.info("free market cycle: %s", json.dumps(status, ensure_ascii=False))
                await write_json(
                    self.redis.client,
                    HEARTBEAT_KEY,
                    {"owner": self.owner, "at": datetime.now(UTC).isoformat()},
                    ttl=self.settings.free_market_worker_lock_ttl_seconds * 2,
                )
            except Exception:
                LOGGER.exception("free market worker cycle failed")
            delay = (
                self.settings.free_market_idle_poll_seconds
                if status.get("state") == "IDLE_NO_SUBSCRIPTIONS"
                else self.settings.free_market_closed_poll_seconds
                if status.get("state") == "MARKET_CLOSED"
                else self.settings.free_market_poll_seconds
            )
            await asyncio.sleep(delay)

    async def close(self) -> None:
        await self.database.close()
        await self.redis.close()


async def async_main(*, once: bool = False) -> int:
    settings = get_settings()
    worker = FreeMarketDataWorker(settings)
    try:
        if once:
            print(json.dumps(await worker.run_once(), ensure_ascii=False, indent=2))
        else:
            await worker.run_forever()
        return 0
    finally:
        await worker.close()


def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
