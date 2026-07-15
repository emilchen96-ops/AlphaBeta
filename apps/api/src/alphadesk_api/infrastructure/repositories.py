"""SQLAlchemy asynchronous repository adapters for domain ports."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table, case, delete, func, inspect, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from alphadesk_api.infrastructure.mappers import entity_from_model, model_from_entity
from alphadesk_api.infrastructure.models import (
    AuditLogModel,
    DomainEventModel,
    ExecutorDeviceAccountModel,
    ExecutorDeviceModel,
    FillModel,
    InstrumentMappingModel,
    InstrumentModel,
    MarketBarModel,
    MarketDataSourceModel,
    MarketSyncRunModel,
    OrderCommandModel,
    OrderModel,
    OrderStateTransitionModel,
    OutboxMessageModel,
    PositionModel,
    RiskDecisionModel,
    SignalModel,
    StrategyModel,
    StrategyVersionModel,
    TradingAccountModel,
    WatchlistItemModel,
    WatchlistModel,
)
from alphadesk_domain.entities import (
    AuditLog,
    DomainEvent,
    ExecutorDevice,
    ExecutorDeviceAccount,
    Fill,
    Instrument,
    Order,
    OrderCommand,
    OrderStateTransition,
    OutboxMessage,
    Position,
    RiskDecision,
    Signal,
    Strategy,
    StrategyVersion,
    TradingAccount,
    Watchlist,
    WatchlistItem,
)
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataSourceStatus,
    MarketSyncStatus,
    MarketTimeframe,
)
from alphadesk_domain.market import (
    InstrumentMapping,
    MarketBar,
    MarketBarUpsertResult,
    MarketDataSource,
    MarketSyncRun,
)


def model_values(model: DeclarativeBase) -> dict[str, Any]:
    mapper = inspect(model).mapper
    values: dict[str, Any] = {}
    for column in model.__table__.columns:
        attribute_name = mapper.get_property_by_column(column).key
        value = getattr(model, attribute_name, None)
        if value is not None:
            values[column.name] = value
    return values


class SqlAlchemyRepository[EntityT, OrmT: DeclarativeBase]:
    entity_type: type[EntityT]
    model_type: type[OrmT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _add(self, entity: EntityT) -> None:
        self._session.add(model_from_entity(self.model_type, entity))
        await self._session.flush()

    async def _get_by_id(self, entity_id: UUID) -> EntityT | None:
        row = await self._session.get(self.model_type, entity_id)
        return None if row is None else entity_from_model(self.entity_type, row)


class SqlAlchemyInstrumentRepository(SqlAlchemyRepository[Instrument, InstrumentModel]):
    entity_type = Instrument
    model_type = InstrumentModel

    async def add(self, entity: Instrument) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> Instrument | None:
        return await self._get_by_id(entity_id)

    async def get_by_business_key(self, exchange: str, symbol: str) -> Instrument | None:
        statement = select(InstrumentModel).where(
            InstrumentModel.exchange == exchange, InstrumentModel.symbol == symbol
        )
        row = await self._session.scalar(statement)
        return None if row is None else entity_from_model(Instrument, row)

    async def get_many(self, entity_ids: list[UUID]) -> list[Instrument]:
        if not entity_ids:
            return []
        rows = await self._session.scalars(
            select(InstrumentModel).where(InstrumentModel.id.in_(entity_ids))
        )
        return [entity_from_model(Instrument, row) for row in rows]

    async def search(
        self,
        *,
        keyword: str | None,
        exchange: str | None,
        market: str | None,
        asset_type: str | None,
        is_active: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Instrument], int]:
        filters = []
        if keyword:
            escaped = keyword.replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    InstrumentModel.symbol.ilike(pattern, escape="\\"),
                    InstrumentModel.name.ilike(pattern, escape="\\"),
                )
            )
        if exchange:
            filters.append(InstrumentModel.exchange == exchange)
        if market:
            filters.append(InstrumentModel.market == market)
        if asset_type:
            filters.append(InstrumentModel.asset_type == asset_type)
        if is_active is not None:
            filters.append(InstrumentModel.is_active == is_active)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(InstrumentModel).where(*filters)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(InstrumentModel)
            .where(*filters)
            .order_by(InstrumentModel.exchange, InstrumentModel.symbol, InstrumentModel.id)
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(Instrument, row) for row in rows], total

    async def upsert_many(self, entities: list[Instrument]) -> list[Instrument]:
        if not entities:
            return []
        values = [model_values(model_from_entity(InstrumentModel, entity)) for entity in entities]
        table = cast(Table, InstrumentModel.__table__)
        insert_statement = pg_insert(table).values(values)
        excluded = insert_statement.excluded
        upsert_statement = insert_statement.on_conflict_do_update(
            constraint="uq_instruments_exchange_symbol",
            set_={
                "market": excluded.market,
                "name": excluded.name,
                "asset_type": excluded.asset_type,
                "currency": excluded.currency,
                "lot_size": excluded.lot_size,
                "price_tick": excluded.price_tick,
                "timezone": excluded.timezone,
                "is_active": excluded.is_active,
                "metadata": excluded.metadata,
                "updated_at": excluded.updated_at,
            },
        ).returning(InstrumentModel.id)
        ids = list(await self._session.scalars(upsert_statement))
        await self._session.flush()
        return await self.get_many(ids)


class SqlAlchemyWatchlistRepository(SqlAlchemyRepository[Watchlist, WatchlistModel]):
    entity_type = Watchlist
    model_type = WatchlistModel

    async def add(self, entity: Watchlist) -> None:
        await self._add(entity)

    async def add_item(self, entity: WatchlistItem) -> None:
        self._session.add(model_from_entity(WatchlistItemModel, entity))
        await self._session.flush()

    async def get_by_id(self, entity_id: UUID) -> Watchlist | None:
        return await self._get_by_id(entity_id)

    async def get_by_name(self, name: str) -> Watchlist | None:
        row = await self._session.scalar(select(WatchlistModel).where(WatchlistModel.name == name))
        return None if row is None else entity_from_model(Watchlist, row)

    async def list_all(self) -> list[Watchlist]:
        rows = await self._session.scalars(
            select(WatchlistModel).order_by(WatchlistModel.created_at, WatchlistModel.id)
        )
        return [entity_from_model(Watchlist, row) for row in rows]

    async def list_items(self, watchlist_id: UUID) -> list[WatchlistItem]:
        rows = await self._session.scalars(
            select(WatchlistItemModel)
            .where(WatchlistItemModel.watchlist_id == watchlist_id)
            .order_by(WatchlistItemModel.sort_order, WatchlistItemModel.created_at)
        )
        return [entity_from_model(WatchlistItem, row) for row in rows]

    async def get_item(self, item_id: UUID) -> WatchlistItem | None:
        row = await self._session.get(WatchlistItemModel, item_id)
        return None if row is None else entity_from_model(WatchlistItem, row)

    async def update(self, entity: Watchlist) -> None:
        await self._session.execute(
            update(WatchlistModel)
            .where(WatchlistModel.id == entity.id)
            .values(name=entity.name, description=entity.description, updated_at=entity.updated_at)
        )
        await self._session.flush()

    async def update_item(self, entity: WatchlistItem) -> None:
        await self._session.execute(
            update(WatchlistItemModel)
            .where(WatchlistItemModel.id == entity.id)
            .values(note=entity.note, sort_order=entity.sort_order)
        )
        await self._session.flush()

    async def remove_item(self, item_id: UUID) -> None:
        await self._session.execute(
            delete(WatchlistItemModel).where(WatchlistItemModel.id == item_id)
        )
        await self._session.flush()

    async def reorder(self, watchlist_id: UUID, item_ids: list[UUID]) -> None:
        positions = {item_id: position for position, item_id in enumerate(item_ids)}
        await self._session.execute(
            update(WatchlistItemModel)
            .where(
                WatchlistItemModel.watchlist_id == watchlist_id,
                WatchlistItemModel.id.in_(item_ids),
            )
            .values(sort_order=case(positions, value=WatchlistItemModel.id))
        )
        await self._session.flush()

    async def delete(self, watchlist_id: UUID) -> None:
        await self._session.execute(delete(WatchlistModel).where(WatchlistModel.id == watchlist_id))
        await self._session.flush()


class SqlAlchemyTradingAccountRepository(SqlAlchemyRepository[TradingAccount, TradingAccountModel]):
    entity_type = TradingAccount
    model_type = TradingAccountModel

    async def add(self, entity: TradingAccount) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> TradingAccount | None:
        return await self._get_by_id(entity_id)

    async def get_by_business_key(self, account_code: str) -> TradingAccount | None:
        row = await self._session.scalar(
            select(TradingAccountModel).where(TradingAccountModel.account_code == account_code)
        )
        return None if row is None else entity_from_model(TradingAccount, row)


class SqlAlchemyPositionRepository(SqlAlchemyRepository[Position, PositionModel]):
    entity_type = Position
    model_type = PositionModel

    async def add(self, entity: Position) -> None:
        await self._add(entity)

    async def get_for_account_instrument(
        self, account_id: UUID, instrument_id: UUID
    ) -> Position | None:
        row = await self._session.scalar(
            select(PositionModel).where(
                PositionModel.account_id == account_id,
                PositionModel.instrument_id == instrument_id,
            )
        )
        return None if row is None else entity_from_model(Position, row)


class SqlAlchemyStrategyRepository(SqlAlchemyRepository[Strategy, StrategyModel]):
    entity_type = Strategy
    model_type = StrategyModel

    async def add(self, entity: Strategy) -> None:
        await self._add(entity)

    async def add_version(self, entity: StrategyVersion) -> None:
        self._session.add(model_from_entity(StrategyVersionModel, entity))
        await self._session.flush()

    async def get_by_id(self, entity_id: UUID) -> Strategy | None:
        return await self._get_by_id(entity_id)

    async def get_by_business_key(self, strategy_code: str) -> Strategy | None:
        row = await self._session.scalar(
            select(StrategyModel).where(StrategyModel.strategy_code == strategy_code)
        )
        return None if row is None else entity_from_model(Strategy, row)


class SqlAlchemySignalRepository(SqlAlchemyRepository[Signal, SignalModel]):
    entity_type = Signal
    model_type = SignalModel

    async def add(self, entity: Signal) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> Signal | None:
        return await self._get_by_id(entity_id)


class SqlAlchemyOrderRepository(SqlAlchemyRepository[Order, OrderModel]):
    entity_type = Order
    model_type = OrderModel

    async def add(self, entity: Order) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> Order | None:
        return await self._get_by_id(entity_id)

    async def get_by_idempotency_key(self, key: str) -> Order | None:
        row = await self._session.scalar(
            select(OrderModel).where(OrderModel.idempotency_key == key)
        )
        return None if row is None else entity_from_model(Order, row)

    async def append_transition(self, transition: OrderStateTransition) -> None:
        self._session.add(model_from_entity(OrderStateTransitionModel, transition))
        await self._session.flush()


class SqlAlchemyOrderCommandRepository(SqlAlchemyRepository[OrderCommand, OrderCommandModel]):
    entity_type = OrderCommand
    model_type = OrderCommandModel

    async def add(self, entity: OrderCommand) -> None:
        await self._add(entity)

    async def get_by_command_id(self, command_id: UUID) -> OrderCommand | None:
        row = await self._session.scalar(
            select(OrderCommandModel).where(OrderCommandModel.command_id == command_id)
        )
        return None if row is None else entity_from_model(OrderCommand, row)


class SqlAlchemyFillRepository(SqlAlchemyRepository[Fill, FillModel]):
    entity_type = Fill
    model_type = FillModel

    async def append(self, entity: Fill) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> Fill | None:
        return await self._get_by_id(entity_id)


class SqlAlchemyRiskDecisionRepository(SqlAlchemyRepository[RiskDecision, RiskDecisionModel]):
    entity_type = RiskDecision
    model_type = RiskDecisionModel

    async def append(self, entity: RiskDecision) -> None:
        await self._add(entity)


class SqlAlchemyDomainEventRepository(SqlAlchemyRepository[DomainEvent, DomainEventModel]):
    entity_type = DomainEvent
    model_type = DomainEventModel

    async def append(self, entity: DomainEvent) -> None:
        await self._add(entity)

    async def get_by_event_id(self, event_id: UUID) -> DomainEvent | None:
        return await self._get_by_id(event_id)


class SqlAlchemyAuditLogRepository(SqlAlchemyRepository[AuditLog, AuditLogModel]):
    entity_type = AuditLog
    model_type = AuditLogModel

    async def append(self, entity: AuditLog) -> None:
        await self._add(entity)


class SqlAlchemyOutboxRepository(SqlAlchemyRepository[OutboxMessage, OutboxMessageModel]):
    entity_type = OutboxMessage
    model_type = OutboxMessageModel

    async def add(self, entity: OutboxMessage) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> OutboxMessage | None:
        return await self._get_by_id(entity_id)


class SqlAlchemyExecutorDeviceRepository(SqlAlchemyRepository[ExecutorDevice, ExecutorDeviceModel]):
    entity_type = ExecutorDevice
    model_type = ExecutorDeviceModel

    async def add(self, entity: ExecutorDevice) -> None:
        await self._add(entity)

    async def bind_account(self, entity: ExecutorDeviceAccount) -> None:
        self._session.add(model_from_entity(ExecutorDeviceAccountModel, entity))
        await self._session.flush()

    async def get_by_id(self, entity_id: UUID) -> ExecutorDevice | None:
        return await self._get_by_id(entity_id)

    async def get_by_device_code(self, device_code: str) -> ExecutorDevice | None:
        row = await self._session.scalar(
            select(ExecutorDeviceModel).where(ExecutorDeviceModel.device_code == device_code)
        )
        return None if row is None else entity_from_model(ExecutorDevice, row)


class SqlAlchemyMarketDataSourceRepository(
    SqlAlchemyRepository[MarketDataSource, MarketDataSourceModel]
):
    entity_type = MarketDataSource
    model_type = MarketDataSourceModel

    async def add(self, entity: MarketDataSource) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> MarketDataSource | None:
        return await self._get_by_id(entity_id)

    async def get_by_code(self, source_code: str) -> MarketDataSource | None:
        row = await self._session.scalar(
            select(MarketDataSourceModel).where(
                MarketDataSourceModel.source_code == source_code.upper()
            )
        )
        return None if row is None else entity_from_model(MarketDataSource, row)

    async def list_active(self) -> list[MarketDataSource]:
        rows = await self._session.scalars(
            select(MarketDataSourceModel)
            .where(MarketDataSourceModel.status == MarketDataSourceStatus.ACTIVE.value)
            .order_by(MarketDataSourceModel.priority, MarketDataSourceModel.source_code)
        )
        return [entity_from_model(MarketDataSource, row) for row in rows]

    async def list_all(self) -> list[MarketDataSource]:
        rows = await self._session.scalars(
            select(MarketDataSourceModel).order_by(
                MarketDataSourceModel.priority, MarketDataSourceModel.source_code
            )
        )
        return [entity_from_model(MarketDataSource, row) for row in rows]


class SqlAlchemyInstrumentMappingRepository(
    SqlAlchemyRepository[InstrumentMapping, InstrumentMappingModel]
):
    entity_type = InstrumentMapping
    model_type = InstrumentMappingModel

    async def add(self, entity: InstrumentMapping) -> None:
        await self._add(entity)

    async def upsert_many(self, entities: list[InstrumentMapping]) -> None:
        if not entities:
            return
        values = [
            model_values(model_from_entity(InstrumentMappingModel, entity)) for entity in entities
        ]
        table = cast(Table, InstrumentMappingModel.__table__)
        statement = pg_insert(table).values(values)
        excluded = statement.excluded
        await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_instrument_mappings_source_instrument",
                set_={
                    "external_symbol": excluded.external_symbol,
                    "external_exchange": excluded.external_exchange,
                    "is_primary": excluded.is_primary,
                    "metadata": excluded.metadata,
                    "updated_at": excluded.updated_at,
                },
            )
        )
        await self._session.flush()

    async def get_by_source_and_external_symbol(
        self, source_id: UUID, external_symbol: str
    ) -> InstrumentMapping | None:
        row = await self._session.scalar(
            select(InstrumentMappingModel).where(
                InstrumentMappingModel.source_id == source_id,
                InstrumentMappingModel.external_symbol == external_symbol,
            )
        )
        return None if row is None else entity_from_model(InstrumentMapping, row)

    async def get_by_source_and_instrument(
        self, source_id: UUID, instrument_id: UUID
    ) -> InstrumentMapping | None:
        row = await self._session.scalar(
            select(InstrumentMappingModel).where(
                InstrumentMappingModel.source_id == source_id,
                InstrumentMappingModel.instrument_id == instrument_id,
            )
        )
        return None if row is None else entity_from_model(InstrumentMapping, row)

    async def list_for_instrument(self, instrument_id: UUID) -> list[InstrumentMapping]:
        rows = await self._session.scalars(
            select(InstrumentMappingModel).where(
                InstrumentMappingModel.instrument_id == instrument_id
            )
        )
        return [entity_from_model(InstrumentMapping, row) for row in rows]

    async def list_for_source_symbols(
        self, source_id: UUID, external_symbols: list[str]
    ) -> list[InstrumentMapping]:
        if not external_symbols:
            return []
        rows = await self._session.scalars(
            select(InstrumentMappingModel).where(
                InstrumentMappingModel.source_id == source_id,
                InstrumentMappingModel.external_symbol.in_(external_symbols),
            )
        )
        return [entity_from_model(InstrumentMapping, row) for row in rows]


class SqlAlchemyMarketBarRepository(SqlAlchemyRepository[MarketBar, MarketBarModel]):
    entity_type = MarketBar
    model_type = MarketBarModel

    async def upsert_many(self, entities: list[MarketBar]) -> MarketBarUpsertResult:
        if not entities:
            return MarketBarUpsertResult(0, 0, 0)
        values = [model_values(model_from_entity(MarketBarModel, entity)) for entity in entities]
        table = cast(Table, MarketBarModel.__table__)
        statement = pg_insert(table).values(values)
        excluded = statement.excluded
        changed = or_(
            excluded.open.is_distinct_from(MarketBarModel.open),
            excluded.high.is_distinct_from(MarketBarModel.high),
            excluded.low.is_distinct_from(MarketBarModel.low),
            excluded.close.is_distinct_from(MarketBarModel.close),
            excluded.volume.is_distinct_from(MarketBarModel.volume),
            excluded.amount.is_distinct_from(MarketBarModel.amount),
            excluded.vwap.is_distinct_from(MarketBarModel.vwap),
            excluded.open_interest.is_distinct_from(MarketBarModel.open_interest),
            excluded.source_updated_at.is_distinct_from(MarketBarModel.source_updated_at),
            excluded.quality_status.is_distinct_from(MarketBarModel.quality_status),
            excluded.quality_flags.is_distinct_from(MarketBarModel.quality_flags),
        )
        result: Result[Any] = await self._session.execute(
            statement.on_conflict_do_update(
                constraint="uq_market_bars_identity",
                set_={
                    "open": excluded.open,
                    "high": excluded.high,
                    "low": excluded.low,
                    "close": excluded.close,
                    "volume": excluded.volume,
                    "amount": excluded.amount,
                    "vwap": excluded.vwap,
                    "open_interest": excluded.open_interest,
                    "received_at": excluded.received_at,
                    "source_updated_at": excluded.source_updated_at,
                    "quality_status": excluded.quality_status,
                    "quality_flags": excluded.quality_flags,
                    "updated_at": excluded.updated_at,
                },
                where=changed,
            ).returning(literal_column("xmax = 0").label("inserted"))
        )
        inserted_flags = [bool(row.inserted) for row in result]
        inserted = sum(inserted_flags)
        updated = len(inserted_flags) - inserted
        await self._session.flush()
        return MarketBarUpsertResult(inserted, updated, len(entities) - len(inserted_flags))

    async def get_bars(
        self,
        *,
        instrument_id: UUID,
        source_id: UUID,
        timeframe: MarketTimeframe,
        adjustment_type: AdjustmentType,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[MarketBar]:
        rows = await self._session.scalars(
            select(MarketBarModel)
            .where(
                MarketBarModel.instrument_id == instrument_id,
                MarketBarModel.source_id == source_id,
                MarketBarModel.timeframe == timeframe.value,
                MarketBarModel.adjustment_type == adjustment_type.value,
                MarketBarModel.bar_time >= start,
                MarketBarModel.bar_time <= end,
            )
            .order_by(MarketBarModel.bar_time)
            .limit(limit)
        )
        return [entity_from_model(MarketBar, row) for row in rows]

    async def get_latest_bar(
        self,
        *,
        instrument_id: UUID,
        source_id: UUID,
        timeframe: MarketTimeframe,
        adjustment_type: AdjustmentType,
    ) -> MarketBar | None:
        row = await self._session.scalar(
            select(MarketBarModel)
            .where(
                MarketBarModel.instrument_id == instrument_id,
                MarketBarModel.source_id == source_id,
                MarketBarModel.timeframe == timeframe.value,
                MarketBarModel.adjustment_type == adjustment_type.value,
            )
            .order_by(MarketBarModel.bar_time.desc())
            .limit(1)
        )
        return None if row is None else entity_from_model(MarketBar, row)

    async def get_latest_for_instruments(
        self,
        *,
        instrument_ids: list[UUID],
        source_id: UUID,
        timeframe: MarketTimeframe,
        adjustment_type: AdjustmentType,
    ) -> list[MarketBar]:
        if not instrument_ids:
            return []
        rows = await self._session.scalars(
            select(MarketBarModel)
            .where(
                MarketBarModel.instrument_id.in_(instrument_ids),
                MarketBarModel.source_id == source_id,
                MarketBarModel.timeframe == timeframe.value,
                MarketBarModel.adjustment_type == adjustment_type.value,
            )
            .distinct(MarketBarModel.instrument_id)
            .order_by(MarketBarModel.instrument_id, MarketBarModel.bar_time.desc())
        )
        return [entity_from_model(MarketBar, row) for row in rows]


class SqlAlchemyMarketSyncRunRepository(SqlAlchemyRepository[MarketSyncRun, MarketSyncRunModel]):
    entity_type = MarketSyncRun
    model_type = MarketSyncRunModel

    async def add(self, entity: MarketSyncRun) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> MarketSyncRun | None:
        return await self._get_by_id(entity_id)

    async def list_recent(self, limit: int) -> list[MarketSyncRun]:
        rows = await self._session.scalars(
            select(MarketSyncRunModel).order_by(MarketSyncRunModel.started_at.desc()).limit(limit)
        )
        return [entity_from_model(MarketSyncRun, row) for row in rows]

    async def update_status(
        self,
        entity_id: UUID,
        *,
        status: MarketSyncStatus,
        completed_at: datetime,
        total_received: int,
        total_inserted: int,
        total_updated: int,
        total_rejected: int,
        error_summary: str | None,
    ) -> None:
        await self._session.execute(
            update(MarketSyncRunModel)
            .where(MarketSyncRunModel.id == entity_id)
            .values(
                status=status.value,
                completed_at=completed_at,
                total_received=total_received,
                total_inserted=total_inserted,
                total_updated=total_updated,
                total_rejected=total_rejected,
                error_summary=error_summary,
                updated_at=completed_at,
            )
        )
        await self._session.flush()
