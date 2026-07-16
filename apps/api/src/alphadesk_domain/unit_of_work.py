"""Unit of Work port without persistence framework dependencies."""

from types import TracebackType
from typing import Protocol, Self

from alphadesk_domain.repositories import (
    AccountReconciliationRepository,
    AccountSnapshotRepository,
    AuditLogRepository,
    CashBalanceRepository,
    CashLedgerRepository,
    DomainEventRepository,
    ExecutorDeviceRepository,
    FillRepository,
    InstrumentMappingRepository,
    InstrumentRepository,
    LedgerTransactionRepository,
    MarketBarRepository,
    MarketDataSourceRepository,
    MarketRealtimeRunRepository,
    MarketSyncRunRepository,
    OrderActionRepository,
    OrderCommandRepository,
    OrderRepository,
    OutboxRepository,
    PositionLedgerRepository,
    PositionRepository,
    RiskDecisionRepository,
    SignalRepository,
    StrategyRepository,
    TradingAccountRepository,
    WatchlistRepository,
)


class UnitOfWork(Protocol):
    instruments: InstrumentRepository
    watchlists: WatchlistRepository
    accounts: TradingAccountRepository
    positions: PositionRepository
    cash_balances: CashBalanceRepository
    ledger_transactions: LedgerTransactionRepository
    cash_ledger: CashLedgerRepository
    position_ledger: PositionLedgerRepository
    account_snapshots: AccountSnapshotRepository
    account_reconciliations: AccountReconciliationRepository
    strategies: StrategyRepository
    signals: SignalRepository
    orders: OrderRepository
    order_actions: OrderActionRepository
    order_commands: OrderCommandRepository
    fills: FillRepository
    risk_decisions: RiskDecisionRepository
    events: DomainEventRepository
    audit_logs: AuditLogRepository
    outbox: OutboxRepository
    executor_devices: ExecutorDeviceRepository
    market_data_sources: MarketDataSourceRepository
    instrument_mappings: InstrumentMappingRepository
    market_bars: MarketBarRepository
    market_sync_runs: MarketSyncRunRepository
    market_realtime_runs: MarketRealtimeRunRepository

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
