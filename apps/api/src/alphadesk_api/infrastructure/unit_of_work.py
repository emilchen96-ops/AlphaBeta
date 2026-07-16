"""SQLAlchemy implementation of the domain Unit of Work port."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.infrastructure.repositories import (
    SqlAlchemyAccountReconciliationRepository,
    SqlAlchemyAccountSnapshotRepository,
    SqlAlchemyAuditLogRepository,
    SqlAlchemyCashBalanceRepository,
    SqlAlchemyCashLedgerRepository,
    SqlAlchemyDomainEventRepository,
    SqlAlchemyExecutorDeviceRepository,
    SqlAlchemyFillRepository,
    SqlAlchemyInstrumentMappingRepository,
    SqlAlchemyInstrumentRepository,
    SqlAlchemyLedgerTransactionRepository,
    SqlAlchemyMarketBarRepository,
    SqlAlchemyMarketDataSourceRepository,
    SqlAlchemyMarketRealtimeRunRepository,
    SqlAlchemyMarketSyncRunRepository,
    SqlAlchemyOrderActionRepository,
    SqlAlchemyOrderCommandRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOrderStateTransitionRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyPositionLedgerRepository,
    SqlAlchemyPositionRepository,
    SqlAlchemyRiskDecisionRepository,
    SqlAlchemySignalRepository,
    SqlAlchemyStrategyRepository,
    SqlAlchemyTradingAccountRepository,
    SqlAlchemyWatchlistRepository,
)


class SqlAlchemyUnitOfWork:
    """Share one AsyncSession and own commit, rollback and close."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False
        self._rolled_back = False

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._committed = False
        self._rolled_back = False
        session = self._session
        self.instruments = SqlAlchemyInstrumentRepository(session)
        self.watchlists = SqlAlchemyWatchlistRepository(session)
        self.accounts = SqlAlchemyTradingAccountRepository(session)
        self.positions = SqlAlchemyPositionRepository(session)
        self.cash_balances = SqlAlchemyCashBalanceRepository(session)
        self.ledger_transactions = SqlAlchemyLedgerTransactionRepository(session)
        self.cash_ledger = SqlAlchemyCashLedgerRepository(session)
        self.position_ledger = SqlAlchemyPositionLedgerRepository(session)
        self.account_snapshots = SqlAlchemyAccountSnapshotRepository(session)
        self.account_reconciliations = SqlAlchemyAccountReconciliationRepository(session)
        self.strategies = SqlAlchemyStrategyRepository(session)
        self.signals = SqlAlchemySignalRepository(session)
        self.orders = SqlAlchemyOrderRepository(session)
        self.order_actions = SqlAlchemyOrderActionRepository(session)
        self.order_state_transitions = SqlAlchemyOrderStateTransitionRepository(session)
        self.order_commands = SqlAlchemyOrderCommandRepository(session)
        self.fills = SqlAlchemyFillRepository(session)
        self.risk_decisions = SqlAlchemyRiskDecisionRepository(session)
        self.events = SqlAlchemyDomainEventRepository(session)
        self.audit_logs = SqlAlchemyAuditLogRepository(session)
        self.outbox = SqlAlchemyOutboxRepository(session)
        self.executor_devices = SqlAlchemyExecutorDeviceRepository(session)
        self.market_data_sources = SqlAlchemyMarketDataSourceRepository(session)
        self.instrument_mappings = SqlAlchemyInstrumentMappingRepository(session)
        self.market_bars = SqlAlchemyMarketBarRepository(session)
        self.market_sync_runs = SqlAlchemyMarketSyncRunRepository(session)
        self.market_realtime_runs = SqlAlchemyMarketRealtimeRunRepository(session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            if (exc_type is not None or not self._committed) and not self._rolled_back:
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        session = self._require_session()
        try:
            await session.commit()
            self._committed = True
        except Exception:
            await session.rollback()
            self._rolled_back = True
            raise

    async def rollback(self) -> None:
        await self._require_session().rollback()
        self._rolled_back = True

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of Work is not active")
        return self._session
