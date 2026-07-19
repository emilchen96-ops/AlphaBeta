"""Unit of Work port without persistence framework dependencies."""

from types import TracebackType
from typing import Protocol, Self

from alphadesk_domain.repositories import (
    AccountReconciliationRepository,
    AccountSnapshotRepository,
    AIAnalysisRunRepository,
    AuditLogRepository,
    BrokerExecutionAttemptRepository,
    CashBalanceRepository,
    CashLedgerRepository,
    DomainEventRepository,
    EventInstrumentLinkRepository,
    EventThemeLinkRepository,
    ExecutorDeviceRepository,
    FillRepository,
    InformationIngestionRunRepository,
    InformationItemRepository,
    InformationSourceRepository,
    InstrumentMappingRepository,
    InstrumentRepository,
    LedgerTransactionRepository,
    MarketBarRepository,
    MarketDataQualityIssueRepository,
    MarketDataQualityRunRepository,
    MarketDataSourceRepository,
    MarketEventRepository,
    MarketRealtimeRunRepository,
    MarketSyncRunRepository,
    OrderActionRepository,
    OrderCommandRepository,
    OrderRepository,
    OrderStateTransitionRepository,
    OutboxRepository,
    PositionLedgerRepository,
    PositionRepository,
    RawDocumentRepository,
    ResearchEvidenceRepository,
    ResearchInsightRepository,
    RiskDecisionRepository,
    RiskRuleEvaluationRepository,
    ScanResultRepository,
    ScanRunRepository,
    SignalRepository,
    StrategyExperimentRepository,
    StrategyExperimentRunRepository,
    StrategyRepository,
    StrategyRunRepository,
    TradingAccountRepository,
    WatchlistRepository,
)
from alphadesk_domain.strategy_runs import HistoricalBarProvider


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
    strategy_runs: StrategyRunRepository
    strategy_experiments: StrategyExperimentRepository
    strategy_experiment_runs: StrategyExperimentRunRepository
    scan_runs: ScanRunRepository
    scan_results: ScanResultRepository
    information_sources: InformationSourceRepository
    raw_documents: RawDocumentRepository
    information_items: InformationItemRepository
    market_events: MarketEventRepository
    event_instrument_links: EventInstrumentLinkRepository
    event_theme_links: EventThemeLinkRepository
    information_ingestion_runs: InformationIngestionRunRepository
    ai_analysis_runs: AIAnalysisRunRepository
    research_insights: ResearchInsightRepository
    research_evidence: ResearchEvidenceRepository
    historical_bars: HistoricalBarProvider
    orders: OrderRepository
    order_actions: OrderActionRepository
    order_state_transitions: OrderStateTransitionRepository
    order_commands: OrderCommandRepository
    fills: FillRepository
    broker_execution_attempts: BrokerExecutionAttemptRepository
    risk_decisions: RiskDecisionRepository
    risk_rule_evaluations: RiskRuleEvaluationRepository
    events: DomainEventRepository
    audit_logs: AuditLogRepository
    outbox: OutboxRepository
    executor_devices: ExecutorDeviceRepository
    market_data_sources: MarketDataSourceRepository
    instrument_mappings: InstrumentMappingRepository
    market_bars: MarketBarRepository
    market_sync_runs: MarketSyncRunRepository
    market_data_quality_runs: MarketDataQualityRunRepository
    market_data_quality_issues: MarketDataQualityIssueRepository
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
