"""SQLAlchemy asynchronous repository adapters for domain ports."""

import builtins
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
    AccountCashBalanceModel,
    AccountReconciliationRunModel,
    AccountSnapshotModel,
    AuditLogModel,
    CashLedgerEntryModel,
    DomainEventModel,
    ExecutorDeviceAccountModel,
    ExecutorDeviceModel,
    FillModel,
    InstrumentMappingModel,
    InstrumentModel,
    LedgerTransactionModel,
    MarketBarModel,
    MarketDataSourceModel,
    MarketRealtimeRunModel,
    MarketSyncRunModel,
    OrderActionModel,
    OrderCommandModel,
    OrderModel,
    OrderStateTransitionModel,
    OutboxMessageModel,
    PositionLedgerEntryModel,
    PositionModel,
    RiskDecisionModel,
    SignalModel,
    StrategyExperimentModel,
    StrategyExperimentRunModel,
    StrategyModel,
    StrategyRunModel,
    StrategyVersionModel,
    TradingAccountModel,
    WatchlistItemModel,
    WatchlistModel,
)
from alphadesk_domain.accounting import (
    AccountReconciliationRun,
    AccountSnapshot,
    CashBalance,
    CashLedgerEntry,
    LedgerTransaction,
    PositionLedgerEntry,
)
from alphadesk_domain.entities import (
    AuditLog,
    DomainEvent,
    ExecutorDevice,
    ExecutorDeviceAccount,
    Fill,
    Instrument,
    Order,
    OrderAction,
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
    CommandType,
    MarketDataSourceStatus,
    MarketSyncStatus,
    MarketTimeframe,
    OutboxStatus,
    RealtimeRunStatus,
)
from alphadesk_domain.market import (
    InstrumentMapping,
    MarketBar,
    MarketBarUpsertResult,
    MarketDataSource,
    MarketSyncRun,
)
from alphadesk_domain.realtime_market import MarketRealtimeRun
from alphadesk_domain.strategy import StrategyBar, StrategyError
from alphadesk_domain.strategy_experiments import StrategyExperiment, StrategyExperimentRun
from alphadesk_domain.strategy_runs import StrategyRun


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

    async def get_by_creation_idempotency_key(self, key: str) -> TradingAccount | None:
        row = await self._session.scalar(
            select(TradingAccountModel).where(TradingAccountModel.creation_idempotency_key == key)
        )
        return None if row is None else entity_from_model(TradingAccount, row)

    async def list_all(self) -> list[TradingAccount]:
        rows = await self._session.scalars(
            select(TradingAccountModel).order_by(
                TradingAccountModel.created_at, TradingAccountModel.id
            )
        )
        return [entity_from_model(TradingAccount, row) for row in rows]

    async def update(self, entity: TradingAccount) -> None:
        await self._session.execute(
            update(TradingAccountModel)
            .where(TradingAccountModel.id == entity.id)
            .values(
                name=entity.name,
                status=entity.status.value,
                settlement_policy=entity.settlement_policy.value,
                metadata_json=entity.metadata,
                updated_at=entity.updated_at,
            )
        )
        await self._session.flush()


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

    async def get_for_update(self, account_id: UUID, instrument_id: UUID) -> Position | None:
        row = await self._session.scalar(
            select(PositionModel)
            .where(
                PositionModel.account_id == account_id,
                PositionModel.instrument_id == instrument_id,
            )
            .with_for_update()
        )
        return None if row is None else entity_from_model(Position, row)

    async def list_for_account(self, account_id: UUID) -> list[Position]:
        rows = await self._session.scalars(
            select(PositionModel)
            .where(PositionModel.account_id == account_id)
            .order_by(PositionModel.created_at, PositionModel.id)
        )
        return [entity_from_model(Position, row) for row in rows]

    async def update(self, entity: Position) -> None:
        await self._session.execute(
            update(PositionModel)
            .where(PositionModel.id == entity.id)
            .values(
                total_quantity=entity.total_quantity,
                available_quantity=entity.available_quantity,
                frozen_quantity=entity.frozen_quantity,
                unsettled_quantity=entity.unsettled_quantity,
                cost_basis=entity.cost_basis,
                average_cost=entity.average_cost,
                market_value=entity.market_value,
                realized_pnl=entity.realized_pnl,
                unrealized_pnl=entity.unrealized_pnl,
                last_price=entity.last_price,
                last_price_at=entity.last_price_at,
                valuation_status=entity.valuation_status.value,
                as_of=entity.as_of,
                row_version=entity.row_version,
                updated_at=entity.updated_at,
            )
        )
        await self._session.flush()


class SqlAlchemyCashBalanceRepository(SqlAlchemyRepository[CashBalance, AccountCashBalanceModel]):
    entity_type = CashBalance
    model_type = AccountCashBalanceModel

    async def add(self, entity: CashBalance) -> None:
        await self._add(entity)

    async def get(self, account_id: UUID, currency: str) -> CashBalance | None:
        row = await self._session.scalar(
            select(AccountCashBalanceModel).where(
                AccountCashBalanceModel.account_id == account_id,
                AccountCashBalanceModel.currency == currency,
            )
        )
        return None if row is None else entity_from_model(CashBalance, row)

    async def get_for_update(self, account_id: UUID, currency: str) -> CashBalance | None:
        row = await self._session.scalar(
            select(AccountCashBalanceModel)
            .where(
                AccountCashBalanceModel.account_id == account_id,
                AccountCashBalanceModel.currency == currency,
            )
            .with_for_update()
        )
        return None if row is None else entity_from_model(CashBalance, row)

    async def list_for_account(self, account_id: UUID) -> list[CashBalance]:
        rows = await self._session.scalars(
            select(AccountCashBalanceModel)
            .where(AccountCashBalanceModel.account_id == account_id)
            .order_by(AccountCashBalanceModel.currency)
        )
        return [entity_from_model(CashBalance, row) for row in rows]

    async def update(self, entity: CashBalance) -> None:
        await self._session.execute(
            update(AccountCashBalanceModel)
            .where(AccountCashBalanceModel.id == entity.id)
            .values(
                total_cash=entity.total_cash,
                available_cash=entity.available_cash,
                frozen_cash=entity.frozen_cash,
                row_version=entity.row_version,
                as_of=entity.as_of,
                updated_at=entity.updated_at,
            )
        )
        await self._session.flush()


class SqlAlchemyLedgerTransactionRepository(
    SqlAlchemyRepository[LedgerTransaction, LedgerTransactionModel]
):
    entity_type = LedgerTransaction
    model_type = LedgerTransactionModel

    async def add(self, entity: LedgerTransaction) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> LedgerTransaction | None:
        return await self._get_by_id(entity_id)

    async def get_by_business_key(self, business_key: str) -> LedgerTransaction | None:
        row = await self._session.scalar(
            select(LedgerTransactionModel).where(
                LedgerTransactionModel.business_key == business_key
            )
        )
        return None if row is None else entity_from_model(LedgerTransaction, row)

    async def get_by_fill_id(self, fill_id: UUID) -> LedgerTransaction | None:
        row = await self._session.scalar(
            select(LedgerTransactionModel).where(LedgerTransactionModel.related_fill_id == fill_id)
        )
        return None if row is None else entity_from_model(LedgerTransaction, row)

    async def list_for_account(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[LedgerTransaction], int]:
        return await self._paged(account_id, offset, limit)

    async def _paged(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[LedgerTransaction], int]:
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(LedgerTransactionModel)
                .where(LedgerTransactionModel.account_id == account_id)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(LedgerTransactionModel)
            .where(LedgerTransactionModel.account_id == account_id)
            .order_by(LedgerTransactionModel.occurred_at.desc(), LedgerTransactionModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(LedgerTransaction, row) for row in rows], total


class SqlAlchemyCashLedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, entity: CashLedgerEntry) -> None:
        self._session.add(model_from_entity(CashLedgerEntryModel, entity))
        await self._session.flush()

    async def list_for_account(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[CashLedgerEntry], int]:
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(CashLedgerEntryModel)
                .where(CashLedgerEntryModel.account_id == account_id)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(CashLedgerEntryModel)
            .where(CashLedgerEntryModel.account_id == account_id)
            .order_by(CashLedgerEntryModel.occurred_at.desc(), CashLedgerEntryModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(CashLedgerEntry, row) for row in rows], total

    async def list_all_for_account(self, account_id: UUID) -> list[CashLedgerEntry]:
        rows = await self._session.scalars(
            select(CashLedgerEntryModel)
            .where(CashLedgerEntryModel.account_id == account_id)
            .order_by(CashLedgerEntryModel.id)
        )
        return [entity_from_model(CashLedgerEntry, row) for row in rows]

    async def get_for_transaction(self, transaction_id: UUID) -> CashLedgerEntry | None:
        row = await self._session.scalar(
            select(CashLedgerEntryModel).where(
                CashLedgerEntryModel.ledger_transaction_id == transaction_id
            )
        )
        return None if row is None else entity_from_model(CashLedgerEntry, row)


class SqlAlchemyPositionLedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, entity: PositionLedgerEntry) -> None:
        self._session.add(model_from_entity(PositionLedgerEntryModel, entity))
        await self._session.flush()

    async def list_for_account(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[PositionLedgerEntry], int]:
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(PositionLedgerEntryModel)
                .where(PositionLedgerEntryModel.account_id == account_id)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(PositionLedgerEntryModel)
            .where(PositionLedgerEntryModel.account_id == account_id)
            .order_by(
                PositionLedgerEntryModel.occurred_at.desc(), PositionLedgerEntryModel.id.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(PositionLedgerEntry, row) for row in rows], total

    async def list_all_for_account(self, account_id: UUID) -> list[PositionLedgerEntry]:
        rows = await self._session.scalars(
            select(PositionLedgerEntryModel)
            .where(PositionLedgerEntryModel.account_id == account_id)
            .order_by(PositionLedgerEntryModel.id)
        )
        return [entity_from_model(PositionLedgerEntry, row) for row in rows]

    async def get_for_transaction(self, transaction_id: UUID) -> PositionLedgerEntry | None:
        row = await self._session.scalar(
            select(PositionLedgerEntryModel).where(
                PositionLedgerEntryModel.ledger_transaction_id == transaction_id
            )
        )
        return None if row is None else entity_from_model(PositionLedgerEntry, row)


class SqlAlchemyAccountSnapshotRepository(
    SqlAlchemyRepository[AccountSnapshot, AccountSnapshotModel]
):
    entity_type = AccountSnapshot
    model_type = AccountSnapshotModel

    async def append(self, entity: AccountSnapshot) -> None:
        await self._add(entity)

    async def latest(self, account_id: UUID) -> AccountSnapshot | None:
        row = await self._session.scalar(
            select(AccountSnapshotModel)
            .where(AccountSnapshotModel.account_id == account_id)
            .order_by(AccountSnapshotModel.as_of.desc(), AccountSnapshotModel.id.desc())
            .limit(1)
        )
        return None if row is None else entity_from_model(AccountSnapshot, row)

    async def list_for_account(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[AccountSnapshot], int]:
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(AccountSnapshotModel)
                .where(AccountSnapshotModel.account_id == account_id)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(AccountSnapshotModel)
            .where(AccountSnapshotModel.account_id == account_id)
            .order_by(AccountSnapshotModel.as_of.desc(), AccountSnapshotModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(AccountSnapshot, row) for row in rows], total


class SqlAlchemyAccountReconciliationRepository(
    SqlAlchemyRepository[AccountReconciliationRun, AccountReconciliationRunModel]
):
    entity_type = AccountReconciliationRun
    model_type = AccountReconciliationRunModel

    async def append(self, entity: AccountReconciliationRun) -> None:
        await self._add(entity)

    async def latest(self, account_id: UUID) -> AccountReconciliationRun | None:
        row = await self._session.scalar(
            select(AccountReconciliationRunModel)
            .where(AccountReconciliationRunModel.account_id == account_id)
            .order_by(
                AccountReconciliationRunModel.started_at.desc(),
                AccountReconciliationRunModel.id.desc(),
            )
            .limit(1)
        )
        return None if row is None else entity_from_model(AccountReconciliationRun, row)

    async def list_for_account(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[AccountReconciliationRun], int]:
        total = int(
            await self._session.scalar(
                select(func.count())
                .select_from(AccountReconciliationRunModel)
                .where(AccountReconciliationRunModel.account_id == account_id)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(AccountReconciliationRunModel)
            .where(AccountReconciliationRunModel.account_id == account_id)
            .order_by(
                AccountReconciliationRunModel.started_at.desc(),
                AccountReconciliationRunModel.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(AccountReconciliationRun, row) for row in rows], total


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

    async def append_many(self, entities: list[Signal]) -> None:
        self._session.add_all([model_from_entity(SignalModel, item) for item in entities])
        await self._session.flush()

    async def list_by_run(
        self, run_id: UUID, offset: int, limit: int, signal_type: str | None = None
    ) -> tuple[list[Signal], int]:
        conditions = [SignalModel.strategy_run_id == run_id]
        if signal_type is not None:
            conditions.append(SignalModel.signal_type == signal_type)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(SignalModel).where(*conditions)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(SignalModel)
            .where(*conditions)
            .order_by(SignalModel.sequence_number, SignalModel.id)
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(Signal, row) for row in rows], total

    async def list_filtered(
        self,
        *,
        strategy_run_id: UUID | None,
        strategy_key: str | None,
        instrument_id: UUID | None,
        signal_type: str | None,
        generated_from: datetime | None,
        generated_to: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Signal], int]:
        conditions = []
        for column, value in (
            (SignalModel.strategy_run_id, strategy_run_id),
            (SignalModel.strategy_key, strategy_key),
            (SignalModel.instrument_id, instrument_id),
            (SignalModel.signal_type, signal_type),
        ):
            if value is not None:
                conditions.append(column == value)
        if generated_from is not None:
            conditions.append(SignalModel.generated_at >= generated_from)
        if generated_to is not None:
            conditions.append(SignalModel.generated_at < generated_to)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(SignalModel).where(*conditions)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(SignalModel)
            .where(*conditions)
            .order_by(SignalModel.generated_at.desc(), SignalModel.id)
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(Signal, row) for row in rows], total

    async def count_by_run(self, run_id: UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(SignalModel)
                .where(SignalModel.strategy_run_id == run_id)
            )
            or 0
        )


class SqlAlchemyStrategyRunRepository(SqlAlchemyRepository[StrategyRun, StrategyRunModel]):
    entity_type = StrategyRun
    model_type = StrategyRunModel

    async def add(self, entity: StrategyRun) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> StrategyRun | None:
        return await self._get_by_id(entity_id)

    async def get_by_idempotency_key(self, key: str) -> StrategyRun | None:
        row = await self._session.scalar(
            select(StrategyRunModel).where(StrategyRunModel.idempotency_key == key)
        )
        return None if row is None else entity_from_model(StrategyRun, row)

    async def update(self, entity: StrategyRun) -> None:
        values = model_values(model_from_entity(StrategyRunModel, entity))
        values.pop("id", None)
        await self._session.execute(
            update(StrategyRunModel).where(StrategyRunModel.id == entity.id).values(**values)
        )
        await self._session.flush()

    async def list(
        self,
        *,
        strategy_key: str | None,
        status: str | None,
        instrument_id: UUID | None,
        created_from: datetime | None,
        created_to: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[StrategyRun], int]:
        conditions = []
        if strategy_key is not None:
            conditions.append(StrategyRunModel.strategy_key == strategy_key)
        if status is not None:
            conditions.append(StrategyRunModel.status == status)
        if instrument_id is not None:
            conditions.append(StrategyRunModel.instrument_ids.contains([instrument_id]))
        if created_from is not None:
            conditions.append(StrategyRunModel.created_at >= created_from)
        if created_to is not None:
            conditions.append(StrategyRunModel.created_at < created_to)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(StrategyRunModel).where(*conditions)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(StrategyRunModel)
            .where(*conditions)
            .order_by(StrategyRunModel.created_at.desc(), StrategyRunModel.id)
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(StrategyRun, row) for row in rows], total


class SqlAlchemyStrategyExperimentRepository(
    SqlAlchemyRepository[StrategyExperiment, StrategyExperimentModel]
):
    entity_type = StrategyExperiment
    model_type = StrategyExperimentModel

    async def add(self, entity: StrategyExperiment) -> None:
        await self._add(entity)

    async def claim(self, entity: StrategyExperiment) -> bool:
        values = model_values(model_from_entity(StrategyExperimentModel, entity))
        statement = (
            pg_insert(StrategyExperimentModel)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(StrategyExperimentModel.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def get_by_id(self, entity_id: UUID) -> StrategyExperiment | None:
        return await self._get_by_id(entity_id)

    async def get_by_idempotency_key(self, key: str) -> StrategyExperiment | None:
        row = await self._session.scalar(
            select(StrategyExperimentModel).where(StrategyExperimentModel.idempotency_key == key)
        )
        return None if row is None else entity_from_model(StrategyExperiment, row)

    async def get_for_update(self, entity_id: UUID) -> StrategyExperiment | None:
        row = await self._session.scalar(
            select(StrategyExperimentModel)
            .where(StrategyExperimentModel.id == entity_id)
            .with_for_update()
        )
        return None if row is None else entity_from_model(StrategyExperiment, row)

    async def update_status(self, entity: StrategyExperiment) -> None:
        values = model_values(model_from_entity(StrategyExperimentModel, entity))
        values.pop("id", None)
        await self._session.execute(
            update(StrategyExperimentModel)
            .where(StrategyExperimentModel.id == entity.id)
            .values(**values)
        )

    async def list(
        self,
        *,
        strategy_key: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[StrategyExperiment], int]:
        conditions = []
        if strategy_key is not None:
            conditions.append(StrategyExperimentModel.strategy_key == strategy_key)
        if status is not None:
            conditions.append(StrategyExperimentModel.status == status)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(StrategyExperimentModel).where(*conditions)
            )
            or 0
        )
        rows = await self._session.scalars(
            select(StrategyExperimentModel)
            .where(*conditions)
            .order_by(StrategyExperimentModel.created_at.desc(), StrategyExperimentModel.id)
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(StrategyExperiment, row) for row in rows], total


class SqlAlchemyStrategyExperimentRunRepository(
    SqlAlchemyRepository[StrategyExperimentRun, StrategyExperimentRunModel]
):
    entity_type = StrategyExperimentRun
    model_type = StrategyExperimentRunModel

    async def append(self, entity: StrategyExperimentRun) -> None:
        await self._add(entity)

    async def get_by_experiment_and_index(
        self, experiment_id: UUID, combination_index: int
    ) -> StrategyExperimentRun | None:
        row = await self._session.scalar(
            select(StrategyExperimentRunModel).where(
                StrategyExperimentRunModel.experiment_id == experiment_id,
                StrategyExperimentRunModel.combination_index == combination_index,
            )
        )
        return None if row is None else entity_from_model(StrategyExperimentRun, row)

    async def list_by_experiment(self, experiment_id: UUID) -> list[StrategyExperimentRun]:
        rows = await self._session.scalars(
            select(StrategyExperimentRunModel)
            .where(StrategyExperimentRunModel.experiment_id == experiment_id)
            .order_by(StrategyExperimentRunModel.combination_index)
        )
        return [entity_from_model(StrategyExperimentRun, row) for row in rows]

    async def count_by_experiment(self, experiment_id: UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(StrategyExperimentRunModel)
                .where(StrategyExperimentRunModel.experiment_id == experiment_id)
            )
            or 0
        )


class SqlAlchemyHistoricalBarProvider:
    """Read immutable S01 strategy bars from persisted market-bar facts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_bars(
        self,
        *,
        instrument_ids: tuple[UUID, ...],
        timeframe: MarketTimeframe,
        start_at: datetime,
        end_at: datetime,
    ) -> list[StrategyBar]:
        result = await self._session.execute(
            select(MarketBarModel, InstrumentModel)
            .join(InstrumentModel, InstrumentModel.id == MarketBarModel.instrument_id)
            .where(
                MarketBarModel.instrument_id.in_(instrument_ids),
                MarketBarModel.timeframe == timeframe.value,
                MarketBarModel.bar_time >= start_at,
                MarketBarModel.bar_time < end_at,
            )
            .order_by(
                MarketBarModel.bar_time,
                MarketBarModel.instrument_id,
                MarketBarModel.id,
            )
        )
        bars: list[StrategyBar] = []
        seen: set[tuple[UUID, datetime]] = set()
        for row, instrument in result.tuples():
            identity = (row.instrument_id, row.bar_time)
            if identity in seen:
                raise StrategyError(
                    "STRATEGY_INVALID_BAR",
                    "multiple market-bar facts exist for one instrument and timestamp",
                )
            seen.add(identity)
            bars.append(
                StrategyBar(
                    instrument_id=row.instrument_id,
                    symbol=instrument.symbol,
                    exchange=instrument.exchange,
                    timeframe=timeframe,
                    timestamp=row.bar_time,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    volume=row.volume,
                    amount=row.amount,
                )
            )
        return bars


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

    async def get_for_update(self, entity_id: UUID) -> Order | None:
        row = await self._session.scalar(
            select(OrderModel).where(OrderModel.id == entity_id).with_for_update()
        )
        return None if row is None else entity_from_model(Order, row)

    async def append_transition(self, transition: OrderStateTransition) -> None:
        """Retain the sealed M02 repository entry point for compatibility."""

        self._session.add(model_from_entity(OrderStateTransitionModel, transition))
        await self._session.flush()

    async def list(
        self,
        *,
        offset: int,
        limit: int,
        account_id: UUID | None = None,
        instrument_id: UUID | None = None,
        status: str | None = None,
        side: str | None = None,
        order_type: str | None = None,
        intent_source: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> tuple[builtins.list[Order], int]:
        filters = []
        if account_id is not None:
            filters.append(OrderModel.account_id == account_id)
        if instrument_id is not None:
            filters.append(OrderModel.instrument_id == instrument_id)
        if status is not None:
            filters.append(OrderModel.status == status)
        if side is not None:
            filters.append(OrderModel.side == side)
        if order_type is not None:
            filters.append(OrderModel.order_type == order_type)
        if intent_source is not None:
            filters.append(OrderModel.intent_source == intent_source)
        if created_from is not None:
            filters.append(OrderModel.created_at >= created_from)
        if created_to is not None:
            filters.append(OrderModel.created_at <= created_to)
        total = int(
            await self._session.scalar(select(func.count()).select_from(OrderModel).where(*filters))
            or 0
        )
        rows = await self._session.scalars(
            select(OrderModel)
            .where(*filters)
            .order_by(OrderModel.created_at.desc(), OrderModel.id)
            .offset(offset)
            .limit(limit)
        )
        return [entity_from_model(Order, row) for row in rows], total

    async def list_expirable(self, now: datetime, limit: int) -> builtins.list[Order]:
        rows = await self._session.scalars(
            select(OrderModel)
            .where(
                OrderModel.expires_at.is_not(None),
                OrderModel.expires_at <= now,
                OrderModel.status.in_(("CREATED", "WAITING_CONFIRMATION")),
            )
            .order_by(OrderModel.expires_at, OrderModel.id)
            .limit(limit)
        )
        return [entity_from_model(Order, row) for row in rows]

    async def update_projection(self, entity: Order) -> None:
        await self._session.execute(
            update(OrderModel)
            .where(OrderModel.id == entity.id)
            .values(
                {
                    OrderModel.status: entity.status.value,
                    OrderModel.row_version: entity.row_version,
                    OrderModel.confirmation_required: entity.confirmation_required,
                    OrderModel.confirmed_at: entity.confirmed_at,
                    OrderModel.cancelled_at: entity.cancelled_at,
                    OrderModel.expired_at: entity.expired_at,
                    OrderModel.submitted_at: entity.submitted_at,
                    OrderModel.completed_at: entity.completed_at,
                    OrderModel.filled_quantity: entity.filled_quantity,
                    OrderModel.average_fill_price: entity.average_fill_price,
                    OrderModel.broker_order_id: entity.broker_order_id,
                    OrderModel.metadata_json: entity.metadata,
                    OrderModel.updated_at: entity.updated_at,
                }
            )
        )
        await self._session.flush()


class SqlAlchemyOrderActionRepository(SqlAlchemyRepository[OrderAction, OrderActionModel]):
    entity_type = OrderAction
    model_type = OrderActionModel

    async def append(self, entity: OrderAction) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> OrderAction | None:
        return await self._get_by_id(entity_id)

    async def get_by_idempotency_key(self, key: str) -> OrderAction | None:
        row = await self._session.scalar(
            select(OrderActionModel).where(OrderActionModel.idempotency_key == key)
        )
        return None if row is None else entity_from_model(OrderAction, row)

    async def list_by_order(self, order_id: UUID) -> list[OrderAction]:
        rows = await self._session.scalars(
            select(OrderActionModel)
            .where(OrderActionModel.order_id == order_id)
            .order_by(OrderActionModel.occurred_at, OrderActionModel.id)
        )
        return [entity_from_model(OrderAction, row) for row in rows]


class SqlAlchemyOrderStateTransitionRepository(
    SqlAlchemyRepository[OrderStateTransition, OrderStateTransitionModel]
):
    entity_type = OrderStateTransition
    model_type = OrderStateTransitionModel

    async def append(self, entity: OrderStateTransition) -> None:
        await self._add(entity)

    async def list_by_order(self, order_id: UUID) -> list[OrderStateTransition]:
        rows = await self._session.scalars(
            select(OrderStateTransitionModel)
            .where(OrderStateTransitionModel.order_id == order_id)
            .order_by(OrderStateTransitionModel.occurred_at, OrderStateTransitionModel.id)
        )
        return [entity_from_model(OrderStateTransition, row) for row in rows]

    async def get_latest_by_order(self, order_id: UUID) -> OrderStateTransition | None:
        row = await self._session.scalar(
            select(OrderStateTransitionModel)
            .where(OrderStateTransitionModel.order_id == order_id)
            .order_by(
                OrderStateTransitionModel.occurred_at.desc(), OrderStateTransitionModel.id.desc()
            )
            .limit(1)
        )
        return None if row is None else entity_from_model(OrderStateTransition, row)


class SqlAlchemyOrderCommandRepository(SqlAlchemyRepository[OrderCommand, OrderCommandModel]):
    entity_type = OrderCommand
    model_type = OrderCommandModel

    async def add(self, entity: OrderCommand) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> OrderCommand | None:
        return await self._get_by_id(entity_id)

    async def get_by_command_id(self, command_id: UUID) -> OrderCommand | None:
        row = await self._session.scalar(
            select(OrderCommandModel).where(OrderCommandModel.command_id == command_id)
        )
        return None if row is None else entity_from_model(OrderCommand, row)

    async def get_submit_command_by_order(self, order_id: UUID) -> OrderCommand | None:
        row = await self._session.scalar(
            select(OrderCommandModel).where(
                OrderCommandModel.order_id == order_id,
                OrderCommandModel.command_type == CommandType.SUBMIT_ORDER.value,
            )
        )
        return None if row is None else entity_from_model(OrderCommand, row)

    async def list_by_order(self, order_id: UUID) -> list[OrderCommand]:
        rows = await self._session.scalars(
            select(OrderCommandModel)
            .where(OrderCommandModel.order_id == order_id)
            .order_by(OrderCommandModel.sequence_number, OrderCommandModel.created_at)
        )
        return [entity_from_model(OrderCommand, row) for row in rows]

    async def count_submit_by_order(self, order_id: UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(OrderCommandModel)
                .where(
                    OrderCommandModel.order_id == order_id,
                    OrderCommandModel.command_type == CommandType.SUBMIT_ORDER.value,
                )
            )
            or 0
        )


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

    async def list_by_entity(self, entity_type: str, entity_id: UUID) -> list[DomainEvent]:
        rows = await self._session.scalars(
            select(DomainEventModel)
            .where(
                DomainEventModel.entity_type == entity_type,
                DomainEventModel.entity_id == entity_id,
            )
            .order_by(DomainEventModel.event_time, DomainEventModel.sequence)
        )
        return [entity_from_model(DomainEvent, row) for row in rows]


class SqlAlchemyAuditLogRepository(SqlAlchemyRepository[AuditLog, AuditLogModel]):
    entity_type = AuditLog
    model_type = AuditLogModel

    async def append(self, entity: AuditLog) -> None:
        await self._add(entity)

    async def list_by_resource(self, resource_type: str, resource_id: UUID) -> list[AuditLog]:
        rows = await self._session.scalars(
            select(AuditLogModel)
            .where(
                AuditLogModel.resource_type == resource_type,
                AuditLogModel.resource_id == resource_id,
            )
            .order_by(AuditLogModel.occurred_at, AuditLogModel.id)
        )
        return [entity_from_model(AuditLog, row) for row in rows]


class SqlAlchemyOutboxRepository(SqlAlchemyRepository[OutboxMessage, OutboxMessageModel]):
    entity_type = OutboxMessage
    model_type = OutboxMessageModel

    async def add(self, entity: OutboxMessage) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> OutboxMessage | None:
        return await self._get_by_id(entity_id)

    async def get_by_event_and_topic(self, event_id: UUID, topic: str) -> OutboxMessage | None:
        row = await self._session.scalar(
            select(OutboxMessageModel).where(
                OutboxMessageModel.event_id == event_id, OutboxMessageModel.topic == topic
            )
        )
        return None if row is None else entity_from_model(OutboxMessage, row)

    async def list_pending(self, limit: int) -> list[OutboxMessage]:
        rows = await self._session.scalars(
            select(OutboxMessageModel)
            .where(OutboxMessageModel.status == OutboxStatus.PENDING.value)
            .order_by(OutboxMessageModel.available_at, OutboxMessageModel.id)
            .limit(limit)
        )
        return [entity_from_model(OutboxMessage, row) for row in rows]

    async def count_pending(self) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(OutboxMessageModel)
                .where(OutboxMessageModel.status == OutboxStatus.PENDING.value)
            )
            or 0
        )

    async def list_by_aggregate(
        self, aggregate_type: str, aggregate_id: UUID
    ) -> list[OutboxMessage]:
        rows = await self._session.scalars(
            select(OutboxMessageModel)
            .where(
                OutboxMessageModel.aggregate_type == aggregate_type,
                OutboxMessageModel.aggregate_id == aggregate_id,
            )
            .order_by(OutboxMessageModel.created_at, OutboxMessageModel.id)
        )
        return [entity_from_model(OutboxMessage, row) for row in rows]


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


class SqlAlchemyMarketRealtimeRunRepository(
    SqlAlchemyRepository[MarketRealtimeRun, MarketRealtimeRunModel]
):
    entity_type = MarketRealtimeRun
    model_type = MarketRealtimeRunModel

    async def add(self, entity: MarketRealtimeRun) -> None:
        await self._add(entity)

    async def get_by_id(self, entity_id: UUID) -> MarketRealtimeRun | None:
        return await self._get_by_id(entity_id)

    async def list_recent(self, limit: int) -> list[MarketRealtimeRun]:
        rows = await self._session.scalars(
            select(MarketRealtimeRunModel)
            .order_by(MarketRealtimeRunModel.started_at.desc())
            .limit(limit)
        )
        return [entity_from_model(MarketRealtimeRun, row) for row in rows]

    async def complete(
        self,
        entity_id: UUID,
        *,
        status: RealtimeRunStatus,
        completed_at: datetime,
        received_count: int,
        changed_count: int,
        rejected_count: int,
        error_summary: str | None,
    ) -> None:
        await self._session.execute(
            update(MarketRealtimeRunModel)
            .where(MarketRealtimeRunModel.id == entity_id)
            .values(
                status=status.value,
                completed_at=completed_at,
                received_count=received_count,
                changed_count=changed_count,
                rejected_count=rejected_count,
                error_summary=error_summary,
                updated_at=completed_at,
            )
        )
        await self._session.flush()
