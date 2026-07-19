"""Instrument catalog import and query service."""

from decimal import Decimal
from uuid import UUID

from alphadesk_api.application.common import (
    ApplicationError,
    UnitOfWorkFactory,
    append_event_and_audit,
)
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketDataSourceStatus, MarketProviderTier, MarketTimeframe
from alphadesk_domain.market import InstrumentMapping, MarketDataSource
from alphadesk_domain.market_adapters import ExternalInstrument, MarketDataAdapter


class InstrumentCatalogService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def ensure_source(
        self,
        *,
        source_code: str,
        name: str,
        status: MarketDataSourceStatus,
        priority: int,
        supports_realtime: bool,
        supported_timeframes: tuple[MarketTimeframe, ...],
        provider_tier: MarketProviderTier = MarketProviderTier.DEMO,
        supports_quotes: bool = False,
        supports_recent_minute_bars: bool = False,
    ) -> MarketDataSource:
        async with self._uow_factory() as uow:
            existing = await uow.market_data_sources.get_by_code(source_code)
            if existing is not None:
                return existing
            source = MarketDataSource(
                source_code=source_code,
                name=name,
                status=status,
                priority=priority,
                supports_realtime=supports_realtime,
                supported_timeframes=supported_timeframes,
                provider_tier=provider_tier,
                supports_quotes=supports_quotes,
                supports_recent_minute_bars=supports_recent_minute_bars,
                metadata={"classification": "DEMO" if source_code == "DEMO" else "EXTERNAL"},
            )
            await uow.market_data_sources.add(source)
            await uow.commit()
            return source

    async def import_from_adapter(
        self, adapter: MarketDataAdapter, correlation_id: UUID
    ) -> tuple[int, int]:
        external = await adapter.list_instruments()
        return await self.import_external(adapter.source_code, external, correlation_id)

    async def import_external(
        self,
        source_code: str,
        external: list[ExternalInstrument],
        correlation_id: UUID,
        batch_size: int = 500,
    ) -> tuple[int, int]:
        if not 1 <= batch_size <= 5_000:
            raise ApplicationError("MARKET_DATA_VALIDATION_FAILED", "batch_size 超出安全范围")
        async with self._uow_factory() as uow:
            source = await uow.market_data_sources.get_by_code(source_code)
            if source is None:
                raise ApplicationError("MARKET_SOURCE_NOT_FOUND", "行情源不存在")
            instruments = [
                Instrument(
                    symbol=item.symbol.upper(),
                    exchange=item.exchange.upper(),
                    market=item.market.upper(),
                    name=item.name,
                    asset_type=item.asset_type.upper(),
                    currency=item.currency.upper(),
                    lot_size=Decimal(item.lot_size),
                    price_tick=Decimal(item.price_tick),
                    timezone=item.timezone,
                    is_active=item.is_active,
                    metadata={
                        "source": source_code,
                        "demo": source_code == "DEMO",
                        **(item.metadata or {}),
                    },
                )
                for item in external
            ]
            persisted: list[Instrument] = []
            for offset in range(0, len(instruments), batch_size):
                persisted.extend(
                    await uow.instruments.upsert_many(instruments[offset : offset + batch_size])
                )
            by_key = {(item.exchange, item.symbol): item for item in persisted}
            mappings = [
                InstrumentMapping(
                    instrument_id=by_key[(item.exchange.upper(), item.symbol.upper())].id,
                    source_id=source.id,
                    external_symbol=item.symbol,
                    external_exchange=item.exchange,
                    is_primary=True,
                    metadata={
                        "demo": source_code == "DEMO",
                        **(item.metadata or {}),
                    },
                )
                for item in external
            ]
            for offset in range(0, len(mappings), batch_size):
                await uow.instrument_mappings.upsert_many(mappings[offset : offset + batch_size])
            if persisted:
                await append_event_and_audit(
                    uow,
                    event_type="INSTRUMENT_IMPORTED",
                    entity_type="MarketDataSource",
                    entity_id=source.id,
                    correlation_id=correlation_id,
                    payload={"source_code": source.source_code, "count": len(persisted)},
                )
                await append_event_and_audit(
                    uow,
                    event_type="INSTRUMENT_MAPPING_CREATED",
                    entity_type="MarketDataSource",
                    entity_id=source.id,
                    correlation_id=correlation_id,
                    payload={"source_code": source.source_code, "count": len(mappings)},
                )
            await uow.commit()
            return len(persisted), len(mappings)

    async def search(
        self,
        *,
        keyword: str | None,
        exchange: str | None,
        market: str | None,
        asset_type: str | None,
        is_active: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Instrument], int]:
        async with self._uow_factory() as uow:
            return await uow.instruments.search(
                keyword=keyword,
                exchange=exchange,
                market=market,
                asset_type=asset_type,
                is_active=is_active,
                offset=(page - 1) * page_size,
                limit=page_size,
            )

    async def get(self, instrument_id: UUID) -> tuple[Instrument, list[InstrumentMapping]]:
        async with self._uow_factory() as uow:
            instrument = await uow.instruments.get_by_id(instrument_id)
            if instrument is None:
                raise ApplicationError("INSTRUMENT_NOT_FOUND", "金融标的不存在")
            mappings = await uow.instrument_mappings.list_for_instrument(instrument_id)
            return instrument, mappings
