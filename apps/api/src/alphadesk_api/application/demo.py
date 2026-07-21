"""U01 one-click research initialization and read-only verification."""

# ruff: noqa: RUF001

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from alphadesk_api.application.accounting import AccountValuationService, SimulatedAccountService
from alphadesk_api.application.ai_research import AIResearchAnalysisService, AnalysisRequest
from alphadesk_api.application.backtests import (
    BacktestIntegrityService,
    BacktestService,
    CreateBacktestRequest,
)
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.information import (
    InformationIngestionService,
    ManualInformationRequest,
    ThemeInput,
)
from alphadesk_api.application.market_data import MarketDataQueryService
from alphadesk_api.application.orders import (
    ConfirmOrderRequest,
    CreateOrderRequest,
    OrderConfirmationService,
)
from alphadesk_api.application.risk import ConfiguredRiskLimitsProvider, RiskGatedOrderService
from alphadesk_api.application.scanners import ScannerRunRequest, ScannerRunService
from alphadesk_api.application.simulated_execution import (
    SimulatedBrokerExecutionService,
    SimulatedExecutionMarketInput,
)
from alphadesk_api.application.strategies import StrategyResearchService
from alphadesk_api.application.strategy_experiments import (
    StrategyExperimentRequest,
    StrategyExperimentService,
)
from alphadesk_api.application.strategy_runner import StrategyRunRequest
from alphadesk_api.application.system_capabilities import CapabilityDataProvider
from alphadesk_api.core.config import Settings
from alphadesk_domain.ai_research import AIAnalysisType, FakeAIResearchProvider
from alphadesk_domain.broker import (
    AshareSimpleFeeModel,
    FixedBasisPointsSlippageModel,
    TradingStatus,
)
from alphadesk_domain.entities import Instrument, Watchlist, WatchlistItem
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketTimeframe,
    OrderStatus,
    OrderType,
    RiskDecisionType,
    SettlementPolicy,
    TimeInForce,
)
from alphadesk_domain.information import MarketEventDirection, MarketEventType
from alphadesk_domain.market import MarketBar, MarketDataSource
from alphadesk_domain.scanners import ScannerParameterValue, ScannerRegistry
from alphadesk_domain.strategy import StrategyParameterValue, StrategyRegistry

DemoMode = Literal["fixture", "existing-data"]
VerificationStatus = Literal[
    "READY", "PARTIAL", "NOT_READY", "DISABLED", "FAILED", "NOT_IMPLEMENTED"
]

DEMO_SCOPE = "U01_DEMO"
DEMO_SOURCE_CODE = "U01_DEMO"
DEMO_ACCOUNT_CODE = "U01-DEMO"
DEMO_WATCHLIST_NAME = "U01 Research Demo"
DEMO_INSTRUMENT_KEY = ("U01", "U01001")
DEMO_START = datetime(2025, 1, 2, tzinfo=UTC)
DEMO_END = DEMO_START + timedelta(days=259)


def _id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"alphadesk:u01:{name}")


@dataclass(frozen=True, slots=True)
class DemoStep:
    key: str
    status: VerificationStatus
    message: str
    entity_id: UUID | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class DemoInitializationResult:
    status: VerificationStatus
    mode: DemoMode
    dry_run: bool
    steps: tuple[DemoStep, ...]
    required_actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerificationItem:
    key: str
    label: str
    status: VerificationStatus
    reason: str
    evidence: dict[str, object] = field(default_factory=dict)
    required_actions: tuple[str, ...] = ()
    link: str | None = None
    available: bool | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.available is None:
            object.__setattr__(self, "available", self.status == "READY")


@dataclass(frozen=True, slots=True)
class ResearchVerificationResult:
    status: VerificationStatus
    generated_at: datetime
    items: tuple[VerificationItem, ...]


class DemoResetGateway(Protocol):
    async def reset(self) -> dict[str, int]: ...


class ResearchDemoInitializationService:
    """Compose existing bounded services into one deterministic local research demo."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        strategy_registry: StrategyRegistry,
        scanner_registry: ScannerRegistry,
        settings: Settings,
        *,
        reset_gateway: DemoResetGateway | None = None,
    ) -> None:
        self._factory = uow_factory
        self._strategies = strategy_registry
        self._scanners = scanner_registry
        self._settings = settings
        self._reset = reset_gateway

    async def initialize(
        self,
        *,
        mode: DemoMode = "existing-data",
        reset_demo: bool = False,
        dry_run: bool = False,
    ) -> DemoInitializationResult:
        self._guard()
        if mode not in ("fixture", "existing-data"):
            raise ApplicationError("DEMO_MODE_INVALID", "mode must be fixture or existing-data")
        if dry_run:
            return DemoInitializationResult(
                status="READY",
                mode=mode,
                dry_run=True,
                steps=(
                    DemoStep("preflight", "READY", "只读预检完成；未写入任何数据"),
                    DemoStep("network", "READY", "初始化不会访问外部网络"),
                ),
            )
        reset_step: DemoStep | None = None
        if reset_demo:
            counts = await self._reset.reset() if self._reset is not None else {}
            reset_step = DemoStep(
                "reset",
                "READY",
                (
                    f"已清理 {sum(counts.values())} 条 U01 演示事实"
                    if counts
                    else "将 U01 演示数据恢复为确定性基线（用户数据不受影响）"
                ),
            )

        selected = await (self._ensure_fixture() if mode == "fixture" else self._existing_data())
        if selected is None:
            return DemoInitializationResult(
                status="NOT_READY",
                mode=mode,
                dry_run=False,
                steps=(DemoStep("historical_data", "NOT_READY", "没有满足研究要求的本地日线"),),
                required_actions=(
                    "先执行 D01 Instrument 同步和历史日线补数",
                    "或使用 --mode fixture 创建明确标记的本地演示数据",
                ),
            )
        instrument, source_code, start_at, end_at = selected
        run_key = (
            "u01-demo"
            if mode == "fixture"
            else f"u01-demo:existing:{instrument.id}:{end_at.date().isoformat()}"
        )
        steps: list[DemoStep] = [] if reset_step is None else [reset_step]
        await self._ensure_watchlist(instrument)
        steps.append(
            DemoStep(
                "market_data",
                "READY",
                f"研究标的 {instrument.exchange}:{instrument.symbol}",
                instrument.id,
            )
        )

        account = await SimulatedAccountService(self._factory).create(
            account_code=DEMO_ACCOUNT_CODE,
            name="U01 Research Demo Account",
            base_currency="CNY",
            initial_cash=Decimal("100000"),
            settlement_policy=SettlementPolicy.IMMEDIATE,
            idempotency_key="u01-demo:account:v1",
            correlation_id=_id("account"),
            occurred_at=DEMO_START,
            scope=DEMO_SCOPE,
        )
        steps.append(DemoStep("account", "READY", "模拟账户及初始资金账本已就绪", account.id))

        scanner_service = ScannerRunService(self._factory, self._scanners)
        scanner_specs: tuple[tuple[str, dict[str, ScannerParameterValue]], ...] = (
            ("volume_anomaly", {"volume_window": 5, "minimum_volume_ratio": "2"}),
            (
                "limit_up_pullback",
                {
                    "lookback_days": 10,
                    "limit_up_threshold": "0.095",
                    "baseline_tolerance": "0.05",
                    "minimum_days_after_limit_up": 2,
                    "maximum_days_after_limit_up": 10,
                    "require_current_above_baseline": True,
                },
            ),
        )
        for scanner_key, raw_scanner_parameters in scanner_specs:
            scanner_parameters: dict[str, ScannerParameterValue] = dict(raw_scanner_parameters)
            outcome = await scanner_service.run(
                ScannerRunRequest(
                    scanner_key=scanner_key,
                    parameters=scanner_parameters,
                    instrument_ids=(instrument.id,),
                    timeframe=MarketTimeframe.DAY_1,
                    as_of=end_at,
                    idempotency_key=f"{run_key}:scanner:{scanner_key}:v1",
                    correlation_id=_id(f"scanner:{scanner_key}"),
                )
            )
            status: VerificationStatus = "READY" if outcome.results else "PARTIAL"
            steps.append(
                DemoStep(
                    f"scanner:{scanner_key}",
                    status,
                    f"命中 {len(outcome.results)} 条",
                    outcome.run.id,
                    outcome.replayed,
                )
            )

        research = StrategyResearchService(self._factory, self._strategies)
        strategy_parameters: dict[str, StrategyParameterValue] = research.parameters(
            "sma_crossover", {"short_window": 2, "long_window": 3, "quantity": "100"}
        )
        strategy = await research.run(
            StrategyRunRequest(
                idempotency_key=f"{run_key}:strategy:sma-crossover:v1",
                strategy_key="sma_crossover",
                timeframe=MarketTimeframe.DAY_1,
                start_at=start_at,
                end_at=end_at + timedelta(days=1),
                instrument_ids=(instrument.id,),
                parameters=strategy_parameters,
                correlation_id=_id("strategy"),
            )
        )
        sides = {signal.side.value for signal in strategy.signals}
        strategy_status: VerificationStatus = "READY" if {"BUY", "SELL"} <= sides else "PARTIAL"
        steps.append(
            DemoStep(
                "strategy",
                strategy_status,
                f"生成 {len(strategy.signals)} 个 Signal（{', '.join(sorted(sides)) or '无'}）",
                strategy.run.id,
                strategy.replayed,
            )
        )

        experiment = await StrategyExperimentService(
            self._factory,
            self._strategies,
            max_combinations=self._settings.strategy_experiment_max_combinations,
        ).run(
            StrategyExperimentRequest(
                idempotency_key=f"{run_key}:experiment:sma-crossover:v1",
                strategy_key="sma_crossover",
                parameter_grid=research.parameter_grid(
                    "sma_crossover",
                    {
                        "short_window": [2, 3],
                        "long_window": [4],
                        "quantity": ["100"],
                    },
                ),
                instrument_ids=(instrument.id,),
                timeframe=MarketTimeframe.DAY_1,
                start_at=start_at,
                end_at=end_at + timedelta(days=1),
                correlation_id=_id("experiment"),
            )
        )
        steps.append(
            DemoStep(
                "experiment",
                "READY",
                "批量研究实验已完成",
                experiment.experiment.id,
                experiment.replayed,
            )
        )

        backtest = await BacktestService(self._factory, self._strategies, self._settings).run(
            CreateBacktestRequest(
                strategy_key="sma_crossover",
                parameters=strategy_parameters,
                instrument_ids=(instrument.id,),
                timeframe=MarketTimeframe.DAY_1,
                start_at=start_at,
                end_at=end_at + timedelta(days=1),
                initial_cash=Decimal("100000"),
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                fee_configuration=AshareSimpleFeeModel(),
                slippage_configuration=FixedBasisPointsSlippageModel(basis_points=Decimal("2")),
                maximum_volume_participation=Decimal("0.1"),
                benchmark_symbol=None,
                data_source_code=source_code,
                idempotency_key=f"{run_key}:backtest:sma-crossover:v1",
                correlation_id=_id("backtest"),
            )
        )
        backtest_integrity = await BacktestIntegrityService(self._factory).verify(backtest.run.id)
        backtest_ready = backtest.metrics is not None and backtest_integrity.passed
        steps.append(
            DemoStep(
                "backtest",
                "READY" if backtest_ready else "FAILED",
                (
                    "日线回测、指标及隔离账本已生成，Integrity 通过"
                    if backtest_ready
                    else "日线回测缺少指标或 Integrity 未通过"
                ),
                backtest.run.id,
                backtest.replayed,
            )
        )

        info = await InformationIngestionService(self._factory).add_manual(
            ManualInformationRequest(
                source_name="U01 Demo Source",
                title=(
                    "U01 一键研究演示事实"
                    if mode == "fixture"
                    else f"U01 一键研究演示事实 {instrument.exchange}:{instrument.symbol}"
                ),
                content=(
                    "这是 AlphaDesk U01 明确标记的本地演示资讯，仅用于验证研究链路。"
                    if mode == "fixture"
                    else (
                        "这是 AlphaDesk U01 明确标记的本地演示资讯，仅用于验证研究链路。"
                        f"研究标的为 {instrument.exchange}:{instrument.symbol}。"
                    )
                ),
                source_url="https://example.invalid/alphadesk/u01-demo",
                published_at=end_at,
                instrument_ids=(instrument.id,),
                themes=(ThemeInput(theme_key="u01-demo", theme_name="U01 演示"),),
                event_type=MarketEventType.COMPANY_NEWS,
                direction=MarketEventDirection.NEUTRAL,
                summary="U01 本地演示资讯和市场事件。",
                importance=Decimal("0.5"),
                correlation_id=_id("information"),
            )
        )
        steps.append(
            DemoStep("information", "READY", "资讯和市场事件已生成", info.event.id, info.duplicate)
        )
        ai = await AIResearchAnalysisService(self._factory, FakeAIResearchProvider()).analyze(
            AnalysisRequest(
                analysis_type=AIAnalysisType.EVENT_SUMMARY,
                event_ids=(info.event.id,),
                information_item_ids=(info.item.id,),
                instrument_ids=(instrument.id,),
                question=None,
                idempotency_key=f"{run_key}:ai:event-summary:v1",
                correlation_id=_id("ai"),
            )
        )
        steps.append(
            DemoStep("ai_research", "READY", "Fake Provider 演示研究已生成", ai.run.id, ai.replayed)
        )

        now = end_at + timedelta(days=2)
        order_key = f"{run_key}:order:buy:v1"
        async with self._factory() as uow:
            existing_order = await uow.orders.get_by_idempotency_key(order_key)
        if existing_order is None:
            await AccountValuationService(
                self._factory,
                MarketDataQueryService(
                    self._factory,
                    minute_stale_seconds=self._settings.market_minute_stale_seconds,
                ),
            ).value(account_id=account.id, correlation_id=_id(f"valuation:{run_key}"))
        risk_order = await RiskGatedOrderService(
            self._factory, ConfiguredRiskLimitsProvider(self._settings)
        ).create(
            CreateOrderRequest(
                account_id=account.id,
                instrument_id=instrument.id,
                side="BUY",
                order_type="LIMIT",
                time_in_force="DAY",
                quantity=Decimal("100"),
                limit_price=Decimal("10"),
                expires_at=None,
                idempotency_key=order_key,
                correlation_id=_id("order"),
                note="U01 deterministic simulated order",
                occurred_at=now,
                reference_price=Decimal("10"),
            )
        )
        if (
            risk_order.decision.overall_decision is not RiskDecisionType.ALLOW
            or risk_order.order is None
        ):
            raise ApplicationError("DEMO_ORDER_REJECTED", "U01 演示订单未通过风控")
        order = risk_order.order
        if order.status is OrderStatus.WAITING_CONFIRMATION:
            order = await OrderConfirmationService(self._factory).confirm(
                ConfirmOrderRequest(
                    order_id=order.id,
                    idempotency_key=f"{run_key}:order:confirm:v1",
                    expected_order_version=order.row_version,
                    correlation_id=_id("order-confirm"),
                    occurred_at=now,
                )
            )
        execution = await SimulatedBrokerExecutionService(self._factory).execute_market_input(
            SimulatedExecutionMarketInput(
                order_id=order.id,
                idempotency_key=f"{run_key}:order:execute:v1",
                correlation_id=_id("execution"),
                timestamp=now + timedelta(seconds=1),
                trading_status=TradingStatus.TRADING,
                source=DEMO_SOURCE_CODE,
                is_stale=False,
                last_price=Decimal("9.98"),
                bid_price=Decimal("9.97"),
                ask_price=Decimal("9.99"),
                available_volume=Decimal("100"),
            )
        )
        reconciliation = execution.reconciliation
        steps.extend(
            (
                DemoStep("risk_order", "READY", "风控决策和人工确认订单已生成", order.id),
                DemoStep(
                    "simulated_broker",
                    "READY",
                    f"模拟执行结果：{execution.attempt.result_status.value}",
                    order.id,
                    execution.idempotent,
                ),
                DemoStep(
                    "accounting",
                    "READY",
                    (
                        f"成交记账与对账：{reconciliation.run.status.value}"
                        if reconciliation is not None
                        else "成交记账已幂等重放"
                    ),
                    None if reconciliation is None else reconciliation.run.id,
                    execution.idempotent,
                ),
            )
        )
        overall: VerificationStatus = (
            "READY" if all(item.status == "READY" for item in steps) else "PARTIAL"
        )
        return DemoInitializationResult(overall, mode, False, tuple(steps))

    def _guard(self) -> None:
        if self._settings.environment not in ("development", "test"):
            raise ApplicationError("DEMO_DISABLED", "U01 初始化仅允许 development/test 环境")

    async def _existing_data(self) -> tuple[Instrument, str | None, datetime, datetime] | None:
        async with self._factory() as uow:
            watchlist = await uow.watchlists.get_by_name("D01 Research Universe")
            if watchlist is None:
                return None
            items = await uow.watchlists.list_items(watchlist.id)
            instruments = await uow.instruments.get_many([item.instrument_id for item in items])
            for instrument in instruments:
                bars = await uow.historical_bars.list_bars(
                    instrument_ids=(instrument.id,),
                    timeframe=MarketTimeframe.DAY_1,
                    start_at=datetime(1970, 1, 1, tzinfo=UTC),
                    end_at=datetime.now(UTC) + timedelta(days=1),
                )
                if len(bars) >= self._settings.market_data_backtest_minimum_bars:
                    return instrument, None, bars[0].timestamp, bars[-1].timestamp
        return None

    async def _ensure_fixture(self) -> tuple[Instrument, str, datetime, datetime]:
        closes = [Decimal(str(10 + ((index % 12) - 6) / 10)) for index in range(254)]
        closes.extend(Decimal(item) for item in ("10", "11", "10.8", "10.4", "10.2", "10"))
        async with self._factory() as uow:
            source = await uow.market_data_sources.get_by_code(DEMO_SOURCE_CODE)
            if source is None:
                source = MarketDataSource(
                    source_code=DEMO_SOURCE_CODE,
                    name="U01 deterministic local research demo",
                    status=MarketDataSourceStatus.ACTIVE,
                    priority=999,
                    supports_realtime=False,
                    supported_timeframes=(MarketTimeframe.DAY_1,),
                    provider_tier=MarketProviderTier.DEMO,
                    metadata={"scope": DEMO_SCOPE, "network_access": False},
                )
                await uow.market_data_sources.add(source)
            instrument = await uow.instruments.get_by_business_key(*DEMO_INSTRUMENT_KEY)
            if instrument is None:
                instrument = Instrument(
                    exchange=DEMO_INSTRUMENT_KEY[0],
                    symbol=DEMO_INSTRUMENT_KEY[1],
                    market="CN_DEMO",
                    name="U01 deterministic research instrument",
                    asset_type="STOCK",
                    currency="CNY",
                    lot_size=Decimal("100"),
                    price_tick=Decimal("0.01"),
                    timezone="Asia/Shanghai",
                    metadata={"scope": DEMO_SCOPE, "not_real_market_data": True},
                )
                await uow.instruments.add(instrument)
            bars = []
            previous = closes[0]
            for index, close in enumerate(closes):
                timestamp = DEMO_START + timedelta(days=index)
                volume = Decimal("500000") if index == len(closes) - 1 else Decimal("100000")
                bars.append(
                    MarketBar(
                        instrument_id=instrument.id,
                        source_id=source.id,
                        timeframe=MarketTimeframe.DAY_1,
                        adjustment_type=AdjustmentType.NONE,
                        bar_time=timestamp,
                        open=previous,
                        high=max(previous, close) + Decimal("0.2"),
                        low=min(previous, close) - Decimal("0.2"),
                        close=close,
                        volume=volume,
                        amount=volume * close,
                        received_at=timestamp + timedelta(hours=16),
                        quality_status=MarketDataQualityStatus.NORMAL,
                        quality_flags={"scope": DEMO_SCOPE, "deterministic": True},
                    )
                )
                previous = close
            await uow.market_bars.upsert_many(bars)
            await uow.commit()
        return instrument, DEMO_SOURCE_CODE, DEMO_START, DEMO_END

    async def _ensure_watchlist(self, instrument: Instrument) -> None:
        async with self._factory() as uow:
            watchlist = await uow.watchlists.get_by_name(DEMO_WATCHLIST_NAME)
            if watchlist is None:
                watchlist = Watchlist(
                    name=DEMO_WATCHLIST_NAME,
                    description="U01_DEMO：一键研究初始化生成，可安全重放。",
                )
                await uow.watchlists.add(watchlist)
            items = await uow.watchlists.list_items(watchlist.id)
            if all(item.instrument_id != instrument.id for item in items):
                await uow.watchlists.add_item(
                    WatchlistItem(
                        watchlist_id=watchlist.id,
                        instrument_id=instrument.id,
                        sort_order=len(items),
                        note="U01_DEMO",
                    )
                )
            await uow.commit()


class ResearchDemoVerificationService:
    """Read-only U01 readiness report; it never creates or repairs facts."""

    def __init__(
        self,
        data_provider: CapabilityDataProvider,
        settings: Settings,
        *,
        postgresql_ok: bool,
        redis_ok: bool,
    ) -> None:
        self._provider = data_provider
        self._settings = settings
        self._postgresql_ok = postgresql_ok
        self._redis_ok = redis_ok

    async def verify(self) -> ResearchVerificationResult:
        data = await self._provider.snapshot()
        items: list[VerificationItem] = []

        def add(key: str, label: str, ready: bool, count: int | None, link: str) -> None:
            items.append(
                VerificationItem(
                    key=key,
                    label=label,
                    status="READY" if ready else "NOT_READY",
                    reason=(f"已有 {count or 0} 条可追溯事实" if ready else "当前缺少可用数据"),
                    evidence={"count": count or 0},
                    required_actions=() if ready else ("运行一键研究初始化",),
                    link=link,
                )
            )

        infrastructure_ready = self._postgresql_ok and self._redis_ok
        items.append(
            VerificationItem(
                "infrastructure",
                "基础设施",
                "READY" if infrastructure_ready else "NOT_READY",
                (
                    f"PostgreSQL={'在线' if self._postgresql_ok else '离线'}，"
                    f"Redis={'在线' if self._redis_ok else '离线'}"
                ),
                {"postgresql": self._postgresql_ok, "redis": self._redis_ok},
                () if infrastructure_ready else ("启动 Docker 服务并检查连接配置",),
                "/",
            )
        )
        migration_ready = data.migration_head == "0015_bt01"
        items.append(
            VerificationItem(
                "migrations",
                "数据库迁移",
                "READY" if migration_ready else "NOT_READY",
                (
                    f"当前 Alembic head: {data.migration_head}"
                    if data.migration_head
                    else "无法读取 Alembic head"
                ),
                {"current": data.migration_head, "expected": "0015_bt01"},
                () if migration_ready else ("执行 alembic upgrade head",),
                "/getting-started",
            )
        )
        bars_ready = bool(data.daily_market_bar_count and data.daily_market_bar_count > 0)
        add(
            "historical_market_data",
            "历史行情",
            bars_ready,
            data.daily_market_bar_count,
            "/market-data-center",
        )
        add("scanner", "条件扫描", bool(data.scan_run_count), data.scan_run_count, "/scan-runs")
        add(
            "strategy_research",
            "策略研究",
            bool(data.strategy_run_count),
            data.strategy_run_count,
            "/strategy-runs",
        )
        add(
            "strategy_experiments",
            "批量研究",
            bool(data.strategy_experiment_count),
            data.strategy_experiment_count,
            "/strategy-experiments",
        )
        add(
            "daily_backtest",
            "日线回测",
            bool(data.backtest_run_count),
            data.backtest_run_count,
            "/backtest",
        )
        add(
            "information_center",
            "资讯事件",
            bool(data.market_event_count),
            data.market_event_count,
            "/market-events",
        )
        add(
            "ai_research",
            "AI 研究（Fake）",
            bool(data.ai_analysis_run_count),
            data.ai_analysis_run_count,
            "/ai-research",
        )
        add(
            "simulated_account",
            "模拟账户",
            bool(data.simulated_account_count),
            data.simulated_account_count,
            "/portfolio",
        )
        add(
            "risk",
            "风控",
            bool(data.risk_decision_count),
            data.risk_decision_count,
            "/risk/decisions",
        )
        add("orders", "订单", bool(data.order_count), data.order_count, "/orders")
        add("simulated_broker", "模拟成交", bool(data.fill_count), data.fill_count, "/fills")
        accounting_ready = bool(data.simulated_account_count and data.fill_count)
        add(
            "accounting",
            "资金持仓账本",
            accounting_ready,
            data.fill_count,
            "/portfolio",
        )
        integrity_ready = bool(data.risk_decision_count and data.order_count and data.fill_count)
        items.append(
            VerificationItem(
                "audit_integrity",
                "事实链完整性",
                "READY" if integrity_ready else "PARTIAL",
                (
                    "风险、订单、成交与账本事实均存在，可继续进入各详情页核对"
                    if integrity_ready
                    else "事实链尚未全部建立"
                ),
                {
                    "risk_decisions": data.risk_decision_count or 0,
                    "orders": data.order_count or 0,
                    "fills": data.fill_count or 0,
                },
                () if integrity_ready else ("运行一键研究初始化",),
                "/audit",
            )
        )
        items.append(
            VerificationItem(
                "realtime_market_data",
                "实时行情",
                "DISABLED",
                "交易级实时 Provider 按安全基线关闭",
                {"provider": self._settings.realtime_market_provider},
                ("后续接入受控实时行情适配器",),
                "/market",
            )
        )
        items.append(
            VerificationItem(
                "miniqmt",
                "MiniQMT",
                "NOT_IMPLEMENTED",
                "Windows 执行器和真实券商链路尚未实施",
                {},
                ("完成独立 RT01/MiniQMT 安全接入任务",),
                "/settings",
            )
        )
        active = [item for item in items if item.status not in ("DISABLED", "NOT_IMPLEMENTED")]
        overall: VerificationStatus = (
            "READY" if all(item.status == "READY" for item in active) else "PARTIAL"
        )
        return ResearchVerificationResult(overall, datetime.now(UTC), tuple(items))
