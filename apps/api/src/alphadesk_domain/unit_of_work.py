"""Unit of Work port without persistence framework dependencies."""

from types import TracebackType
from typing import Protocol, Self

from alphadesk_domain.repositories import (
    AuditLogRepository,
    DomainEventRepository,
    ExecutorDeviceRepository,
    FillRepository,
    InstrumentMappingRepository,
    InstrumentRepository,
    MarketBarRepository,
    MarketDataSourceRepository,
    MarketSyncRunRepository,
    OrderCommandRepository,
    OrderRepository,
    OutboxRepository,
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
    strategies: StrategyRepository
    signals: SignalRepository
    orders: OrderRepository
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

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
