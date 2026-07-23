"""Application services for the MiniQMT read-only market-data gateway."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Awaitable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.infrastructure.free_market_cache import QuoteCache, write_json
from alphadesk_api.infrastructure.models import (
    InstrumentModel,
    MarketActiveSubscriptionModel,
    MarketBarModel,
    MarketDataSourceModel,
    MarketSubscriptionItemModel,
    MarketSubscriptionSetModel,
    MarketSubscriptionSyncRunModel,
    ScanResultModel,
    ScanRunModel,
    WatchlistItemModel,
    WatchlistModel,
)
from alphadesk_domain.enums import (
    MarketDataQualityStatus,
    MarketProviderTier,
    MarketProviderUsage,
    MarketTimeframe,
)
from alphadesk_domain.intraday import IntradaySessionTemplate
from alphadesk_domain.miniqmt_market import (
    DesiredSubscription,
    MarketSubscriptionPlanService,
    QuoteSnapshot,
    SubscriptionOrigin,
)
from alphadesk_domain.realtime_market import MarketQuote

AGENT_STATUS_KEY = "alphadesk:miniqmt:v1:agent:status"
TEMPORARY_SUBSCRIPTIONS_KEY = "alphadesk:miniqmt:v1:temporary"
HISTORY_QUEUE_KEY = "alphadesk:miniqmt:v1:history:requests"
EVENT_CHANNEL = "alphadesk:market:v1:events"


def _version(values: list[dict[str, object]]) -> str:
    canonical = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class MiniQMTSubscriptionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        *,
        max_subscriptions: int,
        benchmark_symbols: list[str],
    ) -> None:
        self._sessions = session_factory
        self._redis = redis
        self._maximum = max_subscriptions
        self._benchmarks = benchmark_symbols
        self._planner = MarketSubscriptionPlanService()

    async def rebuild(self) -> dict[str, object]:
        candidates = await self._candidates()
        async with self._sessions() as session:
            current = tuple(
                await session.scalars(
                    select(MarketActiveSubscriptionModel.instrument_id).where(
                        MarketActiveSubscriptionModel.status == "SUBSCRIBED"
                    )
                )
            )
            source_rows: list[dict[str, object]] = [
                {
                    "instrument_id": str(item.instrument_id),
                    "symbol": item.symbol,
                    "exchange": item.exchange,
                    "origins": [origin.value for origin in item.origins],
                }
                for item in candidates
            ]
            version = _version([*source_rows, {"limit": self._maximum, "planner_schema": 2}])
            plan = self._planner.build(
                candidates=tuple(candidates),
                current_instrument_ids=current,
                max_subscriptions=self._maximum,
                plan_version=version,
            )
            existing = await session.scalar(
                select(MarketSubscriptionSetModel).where(
                    MarketSubscriptionSetModel.version == version
                )
            )
            if existing is None:
                source_summary = Counter(
                    origin.value for item in plan.desired_instruments for origin in item.origins
                )
                existing = MarketSubscriptionSetModel(
                    id=uuid4(),
                    version=version,
                    source_summary=dict(source_summary),
                    desired_count=len(plan.desired_instruments),
                )
                session.add(existing)
                await session.flush()
                session.add_all(
                    [
                        MarketSubscriptionItemModel(
                            id=uuid4(),
                            subscription_set_id=existing.id,
                            instrument_id=item.instrument_id,
                            subscription_reason=[origin.value for origin in item.origins],
                            desired_status="WAITING",
                            provider="MINIQMT",
                        )
                        for item in plan.desired_instruments
                    ]
                )
            else:
                existing.activated_at = datetime.now(UTC)
            await session.commit()
            serialized = await self._serialize_plan(session, existing.id)
            serialized["rejected_items"] = [
                {
                    "instrument_id": str(item.instrument_id),
                    "symbol": item.symbol,
                    "exchange": item.exchange,
                    "name": item.name,
                    "origins": [origin.value for origin in item.origins],
                    "reason": reason,
                }
                for item, reason in plan.rejected_instruments
            ]
            return serialized

    async def desired(self) -> dict[str, object]:
        async with self._sessions() as session:
            set_id = await self._latest_set_id(session)
            if set_id is None:
                return await self.rebuild()
            return await self._serialize_plan(session, set_id)

    async def active(self) -> list[dict[str, object]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(MarketActiveSubscriptionModel, InstrumentModel)
                    .join(
                        InstrumentModel,
                        InstrumentModel.id == MarketActiveSubscriptionModel.instrument_id,
                    )
                    .order_by(InstrumentModel.exchange, InstrumentModel.symbol)
                )
            ).all()
            return [
                {
                    "instrument_id": str(active.instrument_id),
                    "symbol": instrument.symbol,
                    "exchange": instrument.exchange,
                    "name": instrument.name,
                    "provider_symbol": active.provider_symbol,
                    "status": active.status,
                    "last_market_time": active.last_market_time,
                    "last_received_at": active.last_received_at,
                    "last_error_code": active.last_error_code,
                    "last_error_message": active.last_error_message,
                    "is_test_data": active.is_test_data,
                }
                for active, instrument in rows
            ]

    async def diff(self) -> dict[str, object]:
        desired = await self.desired()
        active = await self.active()
        desired_items = cast(list[dict[str, object]], desired["items"])
        desired_ids = {str(item["instrument_id"]) for item in desired_items}
        active_ids = {
            str(item["instrument_id"]) for item in active if item["status"] == "SUBSCRIBED"
        }
        return {
            "plan_version": desired["version"],
            "desired_count": len(desired_ids),
            "active_count": len(active_ids),
            "instruments_to_subscribe": sorted(desired_ids - active_ids),
            "instruments_to_unsubscribe": sorted(active_ids - desired_ids),
        }

    async def begin_sync(self, correlation_id: UUID) -> dict[str, object]:
        desired = await self.desired()
        diff = await self.diff()
        subscribe_ids = cast(list[str], diff["instruments_to_subscribe"])
        unsubscribe_ids = cast(list[str], diff["instruments_to_unsubscribe"])
        fingerprint = _version(
            [
                {"version": desired["version"]},
                {"subscribe": subscribe_ids},
                {"unsubscribe": unsubscribe_ids},
            ]
        )
        async with self._sessions() as session:
            set_id = UUID(str(desired["id"]))
            existing = await session.scalar(
                select(MarketSubscriptionSyncRunModel).where(
                    MarketSubscriptionSyncRunModel.subscription_set_id == set_id,
                    MarketSubscriptionSyncRunModel.operation_fingerprint == fingerprint,
                )
            )
            if existing is None:
                existing = MarketSubscriptionSyncRunModel(
                    id=uuid4(),
                    subscription_set_id=set_id,
                    operation_fingerprint=fingerprint,
                    desired_count=int(str(desired["desired_count"])),
                    attempted_subscribe_count=len(subscribe_ids),
                    subscribed_count=0,
                    attempted_unsubscribe_count=len(unsubscribe_ids),
                    unsubscribed_count=0,
                    failed_count=0,
                    status="PENDING",
                    started_at=datetime.now(UTC),
                    correlation_id=correlation_id,
                )
                session.add(existing)
                await session.commit()
            return {
                "sync_run_id": str(existing.id),
                "status": existing.status,
                "plan": desired,
                "diff": diff,
                "trading_capability": "DISABLED",
                "market_data_capability": "ENABLED",
            }

    async def report_sync(
        self,
        sync_run_id: UUID,
        *,
        subscriptions: list[dict[str, object]],
        unsubscriptions: list[dict[str, object]],
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        failed = 0
        subscribed = 0
        unsubscribed = 0
        async with self._sessions() as session:
            run = await session.get(MarketSubscriptionSyncRunModel, sync_run_id)
            if run is None:
                raise ValueError("MARKET_SUBSCRIPTION_SYNC_RUN_NOT_FOUND")
            for item in subscriptions:
                instrument_id = UUID(str(item["instrument_id"]))
                success = bool(item.get("success"))
                subscribed += int(success)
                failed += int(not success)
                statement = pg_insert(MarketActiveSubscriptionModel).values(
                    instrument_id=instrument_id,
                    provider="MINIQMT",
                    provider_symbol=str(item["provider_symbol"]),
                    provider_subscription_id=(
                        str(item["subscription_id"])
                        if item.get("subscription_id") is not None
                        else None
                    ),
                    status="SUBSCRIBED" if success else "FAILED",
                    last_error_code=item.get("error_code"),
                    last_error_message=item.get("error_message"),
                    is_test_data=False,
                    updated_at=now,
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=["instrument_id"],
                        set_={
                            "provider_symbol": statement.excluded.provider_symbol,
                            "provider_subscription_id": (
                                statement.excluded.provider_subscription_id
                            ),
                            "status": statement.excluded.status,
                            "last_error_code": statement.excluded.last_error_code,
                            "last_error_message": statement.excluded.last_error_message,
                            "is_test_data": False,
                            "updated_at": now,
                        },
                    )
                )
            for item in unsubscriptions:
                instrument_id = UUID(str(item["instrument_id"]))
                success = bool(item.get("success"))
                unsubscribed += int(success)
                failed += int(not success)
                if success:
                    await session.execute(
                        delete(MarketActiveSubscriptionModel).where(
                            MarketActiveSubscriptionModel.instrument_id == instrument_id
                        )
                    )
                else:
                    await session.execute(
                        update(MarketActiveSubscriptionModel)
                        .where(MarketActiveSubscriptionModel.instrument_id == instrument_id)
                        .values(
                            status="FAILED",
                            last_error_code=item.get("error_code"),
                            last_error_message=item.get("error_message"),
                            updated_at=now,
                        )
                    )
            status = (
                "FAILED"
                if failed and not (subscribed or unsubscribed)
                else ("PARTIALLY_SUCCEEDED" if failed else "SUCCEEDED")
            )
            run.subscribed_count = subscribed
            run.unsubscribed_count = unsubscribed
            run.failed_count = failed
            run.status = status
            run.error_summary = "部分订阅操作失败" if failed else None
            run.completed_at = now
            await session.commit()
        await self._redis.publish(
            EVENT_CHANNEL,
            json.dumps(
                {
                    "schema_version": 1,
                    "type": "subscription_status_changed",
                    "event_type": "subscription_status_changed",
                    "instrument_id": None,
                    "market_time": None,
                    "occurred_at": now.isoformat(),
                    "payload": {"sync_run_id": str(sync_run_id), "status": status},
                }
            ),
        )
        return {"sync_run_id": str(sync_run_id), "status": status, "failed_count": failed}

    async def add_temporary(self, instrument_id: UUID) -> None:
        await cast(
            Awaitable[Any],
            self._redis.sadd(TEMPORARY_SUBSCRIPTIONS_KEY, str(instrument_id)),
        )
        await cast(Awaitable[Any], self._redis.expire(TEMPORARY_SUBSCRIPTIONS_KEY, 900))

    async def remove_temporary(self, instrument_id: UUID) -> None:
        await cast(
            Awaitable[Any],
            self._redis.srem(TEMPORARY_SUBSCRIPTIONS_KEY, str(instrument_id)),
        )

    async def _latest_set_id(self, session: AsyncSession) -> UUID | None:
        return cast(
            UUID | None,
            await session.scalar(
                select(MarketSubscriptionSetModel.id)
                .order_by(
                    MarketSubscriptionSetModel.activated_at.desc(),
                    MarketSubscriptionSetModel.created_at.desc(),
                )
                .limit(1)
            ),
        )

    async def _serialize_plan(self, session: AsyncSession, set_id: UUID) -> dict[str, object]:
        subscription_set = await session.get(MarketSubscriptionSetModel, set_id)
        if subscription_set is None:
            raise RuntimeError("subscription set not found")
        rows = (
            await session.execute(
                select(MarketSubscriptionItemModel, InstrumentModel)
                .join(
                    InstrumentModel,
                    InstrumentModel.id == MarketSubscriptionItemModel.instrument_id,
                )
                .where(MarketSubscriptionItemModel.subscription_set_id == set_id)
                .order_by(InstrumentModel.exchange, InstrumentModel.symbol)
            )
        ).all()
        return {
            "id": str(subscription_set.id),
            "version": subscription_set.version,
            "desired_count": subscription_set.desired_count,
            "source_summary": subscription_set.source_summary,
            "created_at": subscription_set.created_at,
            "items": [
                {
                    "instrument_id": str(item.instrument_id),
                    "symbol": instrument.symbol,
                    "exchange": instrument.exchange,
                    "name": instrument.name,
                    "provider_symbol": DesiredSubscription(
                        instrument_id=instrument.id,
                        symbol=instrument.symbol,
                        exchange=instrument.exchange,
                        name=instrument.name,
                        origins=tuple(
                            SubscriptionOrigin(origin) for origin in item.subscription_reason
                        ),
                    ).provider_symbol,
                    "origins": item.subscription_reason,
                    "desired_status": item.desired_status,
                }
                for item, instrument in rows
            ],
        }

    async def _candidates(self) -> list[DesiredSubscription]:
        by_id: dict[UUID, DesiredSubscription] = {}
        async with self._sessions() as session:
            watchlist_rows = (
                await session.execute(
                    select(InstrumentModel)
                    .join(
                        WatchlistItemModel,
                        WatchlistItemModel.instrument_id == InstrumentModel.id,
                    )
                    .join(
                        WatchlistModel,
                        WatchlistModel.id == WatchlistItemModel.watchlist_id,
                    )
                    .where(WatchlistModel.realtime_enabled.is_(True), InstrumentModel.is_active)
                )
            ).scalars()
            self._merge(by_id, list(watchlist_rows), SubscriptionOrigin.WATCHLIST)

            latest_scan = await session.scalar(
                select(ScanRunModel.id)
                .where(ScanRunModel.status == "COMPLETED")
                .order_by(ScanRunModel.completed_at.desc())
                .limit(1)
            )
            if latest_scan is not None:
                scanner_rows = (
                    await session.execute(
                        select(InstrumentModel)
                        .join(
                            ScanResultModel,
                            ScanResultModel.instrument_id == InstrumentModel.id,
                        )
                        .where(
                            ScanResultModel.scan_run_id == latest_scan,
                            InstrumentModel.is_active,
                        )
                    )
                ).scalars()
                self._merge(by_id, list(scanner_rows), SubscriptionOrigin.SCANNER)

            benchmark_conditions = []
            for item in self._benchmarks:
                symbol, _, exchange = item.partition(".")
                benchmark_conditions.append((symbol, exchange))
            if benchmark_conditions:
                instruments = list(
                    await session.scalars(
                        select(InstrumentModel).where(
                            InstrumentModel.is_active,
                            func.concat(InstrumentModel.symbol, ".", InstrumentModel.exchange).in_(
                                [
                                    f"{symbol}.{exchange}"
                                    for symbol, exchange in benchmark_conditions
                                ]
                            ),
                        )
                    )
                )
                self._merge(by_id, instruments, SubscriptionOrigin.BENCHMARK)

            temporary_ids = {
                UUID(str(value))
                for value in await cast(
                    Awaitable[set[Any]],
                    self._redis.smembers(TEMPORARY_SUBSCRIPTIONS_KEY),
                )
            }
            if temporary_ids:
                temporary = list(
                    await session.scalars(
                        select(InstrumentModel).where(
                            InstrumentModel.id.in_(temporary_ids),
                            InstrumentModel.is_active,
                        )
                    )
                )
                self._merge(by_id, temporary, SubscriptionOrigin.TEMPORARY)
        return list(by_id.values())

    @staticmethod
    def _merge(
        target: dict[UUID, DesiredSubscription],
        instruments: list[InstrumentModel],
        origin: SubscriptionOrigin,
    ) -> None:
        for instrument in instruments:
            previous = target.get(instrument.id)
            origins = set(previous.origins if previous is not None else ())
            origins.add(origin)
            target[instrument.id] = DesiredSubscription(
                instrument_id=instrument.id,
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                name=instrument.name,
                origins=tuple(sorted(origins, key=str)),
            )


class MiniQMTQuoteIngestionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cache: QuoteCache,
        redis: Redis,
    ) -> None:
        self._sessions = session_factory
        self._cache = cache
        self._redis = redis

    async def ingest(self, snapshot: QuoteSnapshot) -> tuple[bool, str, int]:
        quote = MarketQuote(
            instrument_id=snapshot.instrument_id,
            source_code="MINIQMT",
            symbol=snapshot.symbol,
            quote_time=snapshot.market_time,
            received_at=snapshot.received_at,
            last_price=snapshot.last_price,
            previous_close=snapshot.previous_close,
            open=snapshot.open_price,
            high=snapshot.high_price,
            low=snapshot.low_price,
            volume=snapshot.volume,
            amount=snapshot.amount,
            bid_price_1=snapshot.bid_price_1,
            bid_volume_1=snapshot.bid_volume_1,
            ask_price_1=snapshot.ask_price_1,
            ask_volume_1=snapshot.ask_volume_1,
            quality_status=MarketDataQualityStatus.NORMAL,
            provider_tier=MarketProviderTier.FREE_BEST_EFFORT,
            usage=(MarketProviderUsage.RESEARCH_ONLY,),
            quality_flags={
                "REAL_PROVIDER": True,
                "exchange": snapshot.exchange,
                "ingested_at": snapshot.ingested_at.isoformat(),
                "upper_limit_price": (
                    str(snapshot.upper_limit_price)
                    if snapshot.upper_limit_price is not None
                    else None
                ),
                "lower_limit_price": (
                    str(snapshot.lower_limit_price)
                    if snapshot.lower_limit_price is not None
                    else None
                ),
                "trading_status": snapshot.trading_status.value,
                "source_sequence": snapshot.source_sequence,
                "schema_version": snapshot.schema_version,
            },
        )
        stored, changed, reason = await self._cache.upsert(quote)
        async with self._sessions() as session:
            await session.execute(
                update(MarketActiveSubscriptionModel)
                .where(MarketActiveSubscriptionModel.instrument_id == snapshot.instrument_id)
                .values(
                    last_market_time=snapshot.market_time,
                    last_received_at=snapshot.received_at,
                    status="SUBSCRIBED",
                    last_error_code=None,
                    last_error_message=None,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.commit()
        return changed, reason, stored.revision.revision


class MiniQMTMinuteBarService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory
        self._template = IntradaySessionTemplate()

    async def ingest(self, items: list[dict[str, object]]) -> dict[str, int]:
        inserted = updated = unchanged = 0
        async with self._sessions() as session:
            source = await session.scalar(
                select(MarketDataSourceModel).where(MarketDataSourceModel.source_code == "MINIQMT")
            )
            if source is None:
                source = MarketDataSourceModel(
                    id=uuid4(),
                    source_code="MINIQMT",
                    name="MiniQMT只读行情",
                    status="ACTIVE",
                    priority=1,
                    supports_realtime=True,
                    provider_tier="FREE_BEST_EFFORT",
                    supports_quotes=True,
                    supports_recent_minute_bars=True,
                    supported_timeframes=["MINUTE_1", "DAY_1"],
                    metadata_json={"trading_capability": "DISABLED"},
                )
                session.add(source)
                await session.flush()
            for item in items:
                bar_time = datetime.fromisoformat(str(item["bar_time"]))
                timeframe = MarketTimeframe(str(item.get("timeframe", "MINUTE_1")))
                if timeframe not in {MarketTimeframe.MINUTE_1, MarketTimeframe.DAY_1}:
                    raise ValueError("MINIQMT_HISTORY_TIMEFRAME_NOT_ALLOWED")
                if timeframe is MarketTimeframe.MINUTE_1 and not self._template.validate_bar_start(
                    bar_time, timeframe
                ):
                    raise ValueError(f"MINIQMT_INVALID_BAR_START:{bar_time.isoformat()}")
                if timeframe is MarketTimeframe.DAY_1:
                    local_date = bar_time.astimezone(UTC).date()
                    bar_time = datetime.combine(local_date, datetime.min.time(), tzinfo=UTC)
                values = {
                    "instrument_id": UUID(str(item["instrument_id"])),
                    "source_id": source.id,
                    "timeframe": timeframe.value,
                    "adjustment_type": "NONE",
                    "bar_time": bar_time,
                    "open": Decimal(str(item["open"])),
                    "high": Decimal(str(item["high"])),
                    "low": Decimal(str(item["low"])),
                    "close": Decimal(str(item["close"])),
                    "volume": Decimal(str(item["volume"])),
                    "amount": (
                        Decimal(str(item["amount"])) if item.get("amount") is not None else None
                    ),
                    "received_at": datetime.now(UTC),
                    "source_updated_at": item.get("source_updated_at"),
                    "quality_status": "NORMAL",
                    "quality_flags": {
                        "source": "MINIQMT",
                        "timestamp_semantics": "BAR_START",
                    },
                    "updated_at": datetime.now(UTC),
                }
                statement = pg_insert(MarketBarModel).values(**values)
                result = await session.execute(
                    statement.on_conflict_do_nothing(
                        constraint="uq_market_bars_identity"
                    ).returning(MarketBarModel.id)
                )
                if result.scalar_one_or_none() is None:
                    unchanged += 1
                else:
                    inserted += 1
            await session.commit()
        return {"inserted": inserted, "updated": updated, "unchanged": unchanged}


async def update_agent_status(redis: Redis, payload: dict[str, object]) -> None:
    safe = {
        "state": payload.get("state", "UNKNOWN"),
        "checked_at": payload.get("checked_at", datetime.now(UTC).isoformat()),
        "agent_version": payload.get("agent_version"),
        "last_market_time": payload.get("last_market_time"),
        "last_received_at": payload.get("last_received_at"),
        "last_minute_bar_time": payload.get("last_minute_bar_time"),
        "error_code": payload.get("error_code"),
        "error_message": payload.get("error_message"),
        "market_data_capability": "ENABLED",
        "trading_capability": "DISABLED",
    }
    await write_json(redis, AGENT_STATUS_KEY, safe, ttl=120)
    await redis.publish(
        EVENT_CHANNEL,
        json.dumps(
            {
                "schema_version": 1,
                "type": "market_data_provider_status_changed",
                "event_type": "market_data_provider_status_changed",
                "instrument_id": None,
                "market_time": payload.get("last_market_time"),
                "occurred_at": datetime.now(UTC).isoformat(),
                "payload": safe,
            }
        ),
    )
