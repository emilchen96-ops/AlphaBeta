"""Use cases for free best-effort realtime market data."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.infrastructure.free_market_cache import QuoteCache
from alphadesk_domain.enums import (
    MarketDataQualityStatus,
    MarketProviderTier,
    RealtimeRunStatus,
    SubscriptionReason,
)
from alphadesk_domain.market_adapters import ExternalMarketQuote, RealtimeMarketDataAdapter
from alphadesk_domain.realtime_market import (
    MarketQuote,
    MarketRealtimeRun,
    MarketSubscription,
    MarketSubscriptionSet,
)


class FreeMarketIngestionError(RuntimeError):
    """A provider cycle failed after its audit run was persisted."""


def strict_decimal(value: str | None, name: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must cross the provider boundary as a string")
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} is not a valid decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    return parsed


class MarketSubscriptionService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def resolve(self, revision: int | None = None) -> MarketSubscriptionSet:
        reasons: dict[UUID, set[SubscriptionReason]] = {}
        async with self._uow_factory() as uow:
            for watchlist in await uow.watchlists.list_all():
                for item in await uow.watchlists.list_items(watchlist.id):
                    reasons.setdefault(item.instrument_id, set()).add(SubscriptionReason.WATCHLIST)
            for account in await uow.accounts.list_all():
                for position in await uow.positions.list_for_account(account.id):
                    if position.total_quantity > 0:
                        reasons.setdefault(position.instrument_id, set()).add(
                            SubscriptionReason.POSITION
                        )
            instruments = await uow.instruments.get_many(list(reasons))
        by_id = {instrument.id: instrument for instrument in instruments}
        return MarketSubscriptionSet(
            items=tuple(
                MarketSubscription(
                    instrument_id=instrument_id,
                    symbol=by_id[instrument_id].symbol,
                    reasons=tuple(sorted(items, key=lambda item: item.value)),
                )
                for instrument_id, items in sorted(reasons.items(), key=lambda item: str(item[0]))
                if instrument_id in by_id
            ),
            revision=(
                revision if revision is not None else int(datetime.now(UTC).timestamp() * 1000)
            ),
            generated_at=datetime.now(UTC),
        )


class FreeQuoteIngestionService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        adapter: RealtimeMarketDataAdapter,
        quote_cache: QuoteCache,
    ) -> None:
        self._uow_factory = uow_factory
        self._adapter = adapter
        self._quote_cache = quote_cache

    async def run(self, subscriptions: MarketSubscriptionSet) -> MarketRealtimeRun:
        started_at = datetime.now(UTC)
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(self._adapter.source_code)
            if source is None:
                raise RuntimeError(f"market source {self._adapter.source_code} is not registered")
            run = MarketRealtimeRun(
                source_id=source.id,
                status=RealtimeRunStatus.RUNNING,
                started_at=started_at,
                requested_count=len(subscriptions.items),
                metadata={"subscription_revision": subscriptions.revision},
            )
            await uow.market_realtime_runs.add(run)
            await uow.commit()

        received = changed = rejected = 0
        errors: list[str] = []
        try:
            external = (
                await self._adapter.fetch_quotes(
                    [subscription.symbol for subscription in subscriptions.items]
                )
                if subscriptions.items
                else []
            )
            received = len(external)
            ids_by_symbol = {
                item.symbol.upper(): item.instrument_id for item in subscriptions.items
            }
            now = datetime.now(UTC)
            for item in external:
                instrument_id = ids_by_symbol.get(item.symbol.upper())
                if instrument_id is None:
                    rejected += 1
                    continue
                try:
                    quote = self._normalize(item, instrument_id, now)
                    _, was_changed, _ = await self._quote_cache.upsert(quote)
                    changed += int(was_changed)
                except (ValueError, InvalidOperation) as exc:
                    rejected += 1
                    errors.append(f"{item.symbol}: {exc}")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

        if errors and received == 0:
            status = RealtimeRunStatus.FAILED
        elif errors or rejected:
            status = RealtimeRunStatus.PARTIALLY_SUCCEEDED
        else:
            status = RealtimeRunStatus.SUCCEEDED
        completed = datetime.now(UTC)
        summary = "; ".join(errors)[:1000] or None
        async with self._uow_factory() as uow:
            await uow.market_realtime_runs.complete(
                run.id,
                status=status,
                completed_at=completed,
                received_count=received,
                changed_count=changed,
                rejected_count=rejected,
                error_summary=summary,
            )
            await uow.commit()
        run.status = status
        run.completed_at = completed
        run.received_count = received
        run.changed_count = changed
        run.rejected_count = rejected
        run.error_summary = summary
        if status is RealtimeRunStatus.FAILED:
            raise FreeMarketIngestionError(summary or "free quote ingestion failed")
        return run

    def _normalize(
        self, item: ExternalMarketQuote, instrument_id: UUID, received_at: datetime
    ) -> MarketQuote:
        last_price = strict_decimal(item.last_price, "last_price")
        if last_price is None:
            raise ValueError("last_price is required")
        flags: dict[str, object] = {
            "FREE_BEST_EFFORT": True,
            "RESEARCH_ONLY": True,
            "NON_TRADING_GRADE": True,
        }
        status = MarketDataQualityStatus.NORMAL
        if item.quote_time is None:
            flags["MISSING_UPSTREAM_QUOTE_TIME"] = True
            status = MarketDataQualityStatus.INCOMPLETE
        return MarketQuote(
            instrument_id=instrument_id,
            source_code=self._adapter.source_code,
            symbol=item.symbol,
            quote_time=item.quote_time,
            received_at=received_at,
            last_price=last_price,
            previous_close=strict_decimal(item.previous_close, "previous_close"),
            open=strict_decimal(item.open, "open"),
            high=strict_decimal(item.high, "high"),
            low=strict_decimal(item.low, "low"),
            volume=strict_decimal(item.volume, "volume"),
            amount=strict_decimal(item.amount, "amount"),
            bid_price_1=strict_decimal(item.bid_price_1, "bid_price_1"),
            bid_volume_1=strict_decimal(item.bid_volume_1, "bid_volume_1"),
            ask_price_1=strict_decimal(item.ask_price_1, "ask_price_1"),
            ask_volume_1=strict_decimal(item.ask_volume_1, "ask_volume_1"),
            quality_status=status,
            provider_tier=MarketProviderTier.FREE_BEST_EFFORT,
            quality_flags=flags,
        )
