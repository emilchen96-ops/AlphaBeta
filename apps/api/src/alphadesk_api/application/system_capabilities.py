"""Authoritative, read-only I01 system capability assessment."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from alphadesk_api.core.config import Settings

ImplementationStatus = Literal["WORKING", "PARTIAL", "PLACEHOLDER", "NOT_IMPLEMENTED", "DISABLED"]
ReadinessStatus = Literal["READY", "MISSING", "DISABLED", "NOT_REQUIRED", "UNKNOWN"]
ConfigurationStatus = Literal[
    "READY",
    "MISSING",
    "DISABLED",
    "NOT_REQUIRED",
    "UNKNOWN",
    "FAKE",
    "REAL_CONFIGURED",
    "REAL_AVAILABLE",
    "REAL_UNAVAILABLE",
]


@dataclass(frozen=True, slots=True)
class CapabilityDataSnapshot:
    database_reachable: bool
    migration_head: str | None = None
    instrument_count: int | None = None
    market_bar_count: int | None = None
    daily_market_bar_count: int | None = None
    intraday_1m_bar_count: int | None = None
    intraday_5m_bar_count: int | None = None
    intraday_15m_bar_count: int | None = None
    intraday_30m_bar_count: int | None = None
    intraday_60m_bar_count: int | None = None
    market_bar_instrument_count: int | None = None
    earliest_market_bar_at: datetime | None = None
    latest_market_bar_at: datetime | None = None
    simulated_account_count: int | None = None
    scan_run_count: int | None = None
    strategy_run_count: int | None = None
    strategy_experiment_count: int | None = None
    information_source_count: int | None = None
    information_item_count: int | None = None
    market_event_count: int | None = None
    ai_analysis_run_count: int | None = None
    order_count: int | None = None
    executable_order_count: int | None = None
    fill_count: int | None = None
    risk_decision_count: int | None = None
    backtest_run_count: int | None = None
    replay_run_count: int | None = None
    trading_calendar_session_count: int | None = None
    adjustment_factor_count: int | None = None
    trading_status_count: int | None = None
    lifecycle_event_count: int | None = None


class CapabilityDataProvider(Protocol):
    async def snapshot(self) -> CapabilityDataSnapshot: ...


@dataclass(frozen=True, slots=True)
class SystemCapability:
    module_key: str
    implementation_status: ImplementationStatus
    data_status: ReadinessStatus
    configuration_status: ConfigurationStatus
    available: bool
    reason: str
    required_actions: tuple[str, ...] = field(default_factory=tuple)
    worker_status: Literal["ONLINE", "OFFLINE", "NOT_REQUIRED"] = "NOT_REQUIRED"


def _has(value: int | None) -> bool:
    return value is not None and value > 0


def assess_system_capabilities(
    settings: Settings,
    data: CapabilityDataSnapshot,
    *,
    ai_provider_configured: bool,
    ai_provider_key: str,
    ai_provider_available: bool | None = None,
    ai_provider_mode: str = "DISABLED",
    replay_worker_available: bool = False,
    miniqmt_agent_connected: bool = False,
) -> tuple[SystemCapability, ...]:
    """Assess what can be used now without mutating business facts."""

    database_ready = data.database_reachable
    instruments_ready = database_ready and _has(data.instrument_count)
    bars_ready = instruments_ready and _has(data.daily_market_bar_count)
    minute_counts = {
        "intraday_1m": data.intraday_1m_bar_count,
        "intraday_5m": data.intraday_5m_bar_count,
        "intraday_15m": data.intraday_15m_bar_count,
        "intraday_30m": data.intraday_30m_bar_count,
        "intraday_60m": data.intraday_60m_bar_count,
    }
    intraday_ready = any(_has(value) for value in minute_counts.values())
    accounts_ready = database_ready and _has(data.simulated_account_count)
    information_ready = database_ready and _has(data.information_item_count)
    executable_order_ready = database_ready and _has(data.executable_order_count)
    calendar_ready = database_ready and _has(data.trading_calendar_session_count)
    factors_ready = database_ready and _has(data.adjustment_factor_count)
    suspension_ready = database_ready and _has(data.trading_status_count)
    lifecycle_ready = database_ready and _has(data.lifecycle_event_count)
    tushare_configured = settings.tushare_enabled and settings.tushare_token is not None

    def reference_capability(
        module_key: str,
        label: str,
        ready: bool,
        provider: str,
        action: str,
    ) -> SystemCapability:
        provider_configured = provider == "fixture" or (
            provider == "tushare" and tushare_configured
        )
        return SystemCapability(
            module_key=module_key,
            implementation_status="WORKING",
            data_status="READY" if ready else ("MISSING" if database_ready else "UNKNOWN"),
            configuration_status="READY" if provider_configured else "MISSING",
            available=ready and provider_configured,
            reason=(
                f"{label}事实已持久化并可查询。"
                if ready
                else f"{label}代码已实现, 当前尚无同步事实。"
            ),
            required_actions=() if ready and provider_configured else (action,),
        )

    def historical_capability(module_key: str, label: str) -> SystemCapability:
        coverage = data.market_bar_instrument_count or 0
        latest = (
            data.latest_market_bar_at.date().isoformat()
            if data.latest_market_bar_at is not None
            else "未知"
        )
        return SystemCapability(
            module_key=module_key,
            implementation_status="WORKING",
            data_status="READY" if bars_ready else ("MISSING" if database_ready else "UNKNOWN"),
            configuration_status="NOT_REQUIRED",
            available=bars_ready,
            reason=(
                f"{label}可读取 PostgreSQL 历史日线; 当前覆盖 {coverage} 个标的, "
                f"最近行情日 {latest}; 具体运行仍校验时间范围和最少 K 线。"
                if bars_ready
                else f"{label}代码已实现, 但当前缺少 Instrument 或历史日线。"
            ),
            required_actions=(
                () if bars_ready else ("导入 Instrument 与足够范围的 DAY_1 MarketBar",)
            ),
        )

    orders_ready = accounts_ready and instruments_ready
    effective_ai_mode = (
        "FAKE"
        if ai_provider_mode == "DISABLED" and ai_provider_configured and ai_provider_key == "fake"
        else ai_provider_mode
    )
    ai_configuration_by_mode: dict[str, ConfigurationStatus] = {
        "FAKE": "FAKE",
        "REAL_CONFIGURED": "REAL_CONFIGURED",
        "REAL_AVAILABLE": "REAL_AVAILABLE",
        "REAL_UNAVAILABLE": "REAL_UNAVAILABLE",
    }
    ai_config_status: ConfigurationStatus = ai_configuration_by_mode.get(
        effective_ai_mode, "DISABLED"
    )
    ai_available = information_ready and (ai_provider_key == "fake" or bool(ai_provider_available))
    return (
        SystemCapability(
            module_key="infrastructure",
            implementation_status="WORKING",
            data_status="READY" if database_ready else "UNKNOWN",
            configuration_status="READY" if database_ready else "UNKNOWN",
            available=database_ready,
            reason="PostgreSQL 能力快照可读取。" if database_ready else "PostgreSQL 当前不可达。",
            required_actions=() if database_ready else ("启动 PostgreSQL 与 Redis",),
        ),
        reference_capability(
            "trading_calendar",
            "交易日历",
            calendar_ready,
            settings.market_calendar_provider,
            "在数据中心同步 SHSE/SZSE 交易日历",
        ),
        reference_capability(
            "adjustment_factors",
            "复权因子",
            factors_ready,
            settings.market_adjustment_provider,
            "在数据中心同步复权因子",
        ),
        reference_capability(
            "suspension_data",
            "停复牌状态",
            suspension_ready,
            settings.market_suspension_provider,
            "在数据中心同步停复牌状态",
        ),
        reference_capability(
            "instrument_lifecycle",
            "Instrument 生命周期",
            lifecycle_ready,
            settings.market_suspension_provider,
            "在数据中心同步 Instrument 生命周期",
        ),
        reference_capability(
            "adjusted_strategy_data",
            "QFQ 策略数据",
            bars_ready and factors_ready and calendar_ready,
            settings.market_adjustment_provider,
            "先同步交易日历与复权因子, 再检查 QFQ Readiness",
        ),
        historical_capability("historical_market_data", "历史行情查询"),
        SystemCapability(
            module_key="intraday_market_data",
            implementation_status="WORKING",
            data_status="READY" if intraday_ready else ("MISSING" if database_ready else "UNKNOWN"),
            configuration_status="NOT_REQUIRED",
            available=intraday_ready,
            reason=(
                "D03历史分钟行情导入、聚合、质量和查询已实现。"
                if intraday_ready
                else "D03代码已实现, 当前尚无历史分钟Bar。"
            ),
            required_actions=() if intraday_ready else ("运行D03 Fixture或CLI导入本地CSV",),
        ),
        *(
            SystemCapability(
                module_key=key,
                implementation_status="WORKING",
                data_status=(
                    "READY" if _has(value) else ("MISSING" if database_ready else "UNKNOWN")
                ),
                configuration_status="NOT_REQUIRED",
                available=_has(value),
                reason=f"历史分钟Bar数量: {value or 0}; 非实时行情。",
                required_actions=() if _has(value) else ("导入1分钟RAW并运行D03确定性聚合",),
            )
            for key, value in minute_counts.items()
        ),
        SystemCapability(
            module_key="minute_backtest",
            implementation_status="NOT_IMPLEMENTED",
            data_status=(
                "READY"
                if _has(data.intraday_5m_bar_count)
                else ("MISSING" if database_ready else "UNKNOWN")
            ),
            configuration_status="NOT_REQUIRED",
            available=False,
            reason="BT02代码尚未开发; 此状态只反映分钟数据。",
            required_actions=("BT02尚未实施",),
        ),
        SystemCapability(
            module_key="minute_replay",
            implementation_status="NOT_IMPLEMENTED",
            data_status="READY" if intraday_ready else ("MISSING" if database_ready else "UNKNOWN"),
            configuration_status="NOT_REQUIRED",
            available=False,
            reason="分钟历史回放代码尚未开发; 此状态只反映分钟数据。",
            required_actions=("分钟历史回放尚未实施",),
        ),
        historical_capability("scanner", "条件扫描"),
        historical_capability("strategy_research", "历史策略研究"),
        historical_capability("strategy_experiments", "批量策略研究"),
        SystemCapability(
            module_key="information_center",
            implementation_status="WORKING",
            data_status="READY" if database_ready else "UNKNOWN",
            configuration_status="NOT_REQUIRED",
            available=database_ready,
            reason=(
                "可手工录入资讯并生成确定性 MarketEvent。" if database_ready else "数据库不可用。"
            ),
            required_actions=() if database_ready else ("恢复 PostgreSQL 连接",),
        ),
        SystemCapability(
            module_key="ai_research",
            implementation_status="WORKING",
            data_status=(
                "READY" if information_ready else ("MISSING" if database_ready else "UNKNOWN")
            ),
            configuration_status=ai_config_status,
            available=ai_available,
            reason=(
                f"Provider {ai_provider_key} 已启用, 并存在可选资讯事实。"
                if ai_available
                else (
                    f"Provider {ai_provider_key} 已配置但尚不可用。"
                    if ai_provider_configured
                    else "AI 研究需要已启用 Provider 和至少一条 InformationItem。"
                )
            ),
            required_actions=tuple(
                action
                for needed, action in (
                    (not information_ready, "先在资讯中心创建 InformationItem"),
                    (
                        not ai_provider_configured
                        or (
                            ai_provider_key == "openai_compatible"
                            and not bool(ai_provider_available)
                        ),
                        "配置并测试 OpenAI 兼容 Provider, 或显式使用本地 Fake 演示",
                    ),
                )
                if needed
            ),
        ),
        SystemCapability(
            module_key="orders",
            implementation_status="WORKING",
            data_status="READY" if orders_ready else ("MISSING" if database_ready else "UNKNOWN"),
            configuration_status="READY",
            available=orders_ready,
            reason=(
                "可创建经 R01 风控的本地模拟订单事实。"
                if orders_ready
                else "创建订单需要模拟账户和 Instrument。"
            ),
            required_actions=() if orders_ready else ("创建模拟账户并导入 Instrument",),
        ),
        SystemCapability(
            module_key="risk",
            implementation_status="WORKING",
            data_status="READY" if orders_ready else ("MISSING" if database_ready else "UNKNOWN"),
            configuration_status="READY",
            available=orders_ready,
            reason="R01 规则和只读限制已接线。" if orders_ready else "风险评估需要账户与标的事实。",
            required_actions=() if orders_ready else ("创建模拟账户并导入 Instrument",),
        ),
        SystemCapability(
            module_key="simulated_broker",
            implementation_status="WORKING",
            data_status=(
                "READY" if executable_order_ready else ("MISSING" if database_ready else "UNKNOWN")
            ),
            configuration_status="READY",
            available=executable_order_ready,
            reason=(
                "存在可使用手工市场快照执行的模拟订单。"
                if executable_order_ready
                else "模拟执行代码已实现, 当前没有 QUEUED/BROKER_ACCEPTED/PARTIALLY_FILLED 订单。"
            ),
            required_actions=(
                () if executable_order_ready else ("创建并人工确认一个通过风控的模拟订单",)
            ),
        ),
        SystemCapability(
            module_key="daily_backtest",
            implementation_status="WORKING",
            data_status=("READY" if bars_ready else ("MISSING" if database_ready else "UNKNOWN")),
            configuration_status="NOT_REQUIRED",
            available=bars_ready,
            reason=(
                "BT01 日线回测已完成, 可使用 PostgreSQL 本地历史日线同步运行。"
                if bars_ready
                else "BT01 日线回测代码已完成, 但当前缺少 Instrument 或历史日线。"
            ),
            required_actions=(() if bars_ready else ("先完成 D01 历史日线补数与质量检查",)),
        ),
        SystemCapability(
            module_key="historical_replay",
            implementation_status="WORKING",
            data_status=("READY" if bars_ready else ("MISSING" if database_ready else "UNKNOWN")),
            configuration_status="READY" if replay_worker_available else "MISSING",
            available=bars_ready and replay_worker_available,
            reason=(
                "RT01 日线历史回放、控制动作和独立 Worker 已就绪。"
                if bars_ready and replay_worker_available
                else (
                    "RT01 已实现且历史数据就绪; replay_worker 当前离线。"
                    if bars_ready
                    else "RT01 已实现; 但需要先完成 D01 历史日线准备。"
                )
            ),
            required_actions=tuple(
                action
                for needed, action in (
                    (not bars_ready, "先完成 D01 历史日线补数与质量检查"),
                    (not replay_worker_available, "启动 replay_worker 服务"),
                )
                if needed
            ),
            worker_status="ONLINE" if replay_worker_available else "OFFLINE",
        ),
        SystemCapability(
            module_key="realtime_market_data",
            implementation_status="WORKING",
            data_status="READY" if miniqmt_agent_connected else "UNKNOWN",
            configuration_status=(
                "READY"
                if miniqmt_agent_connected
                else ("MISSING" if settings.miniqmt_market_data_enabled else "DISABLED")
            ),
            available=miniqmt_agent_connected,
            reason=(
                "MiniQMT只读实时行情、Redis和WebSocket链路已连接。"
                if miniqmt_agent_connected
                else "实时行情链路已实现, 当前MiniQMT只读行情代理未连接。"
            ),
            required_actions=(
                () if miniqmt_agent_connected else ("启动MiniQMT客户端和Windows行情代理",)
            ),
        ),
        SystemCapability(
            module_key="miniqmt_market_data",
            implementation_status="WORKING",
            data_status="READY" if miniqmt_agent_connected else "UNKNOWN",
            configuration_status=(
                "READY"
                if miniqmt_agent_connected
                else ("MISSING" if settings.miniqmt_market_data_enabled else "DISABLED")
            ),
            available=miniqmt_agent_connected,
            reason=(
                "MiniQMT只读行情代理已连接。"
                if miniqmt_agent_connected
                else "MiniQMT只读行情代码已完成, 当前Windows行情代理未连接。"
            ),
            required_actions=(
                () if miniqmt_agent_connected else ("启动MiniQMT客户端和Windows行情代理",)
            ),
            worker_status="ONLINE" if miniqmt_agent_connected else "OFFLINE",
        ),
        SystemCapability(
            module_key="realtime_quotes",
            implementation_status="WORKING",
            data_status="READY" if miniqmt_agent_connected else "UNKNOWN",
            configuration_status="READY" if miniqmt_agent_connected else "MISSING",
            available=miniqmt_agent_connected,
            reason=(
                "MiniQMT行情快照正在写入Redis并通过WebSocket推送。"
                if miniqmt_agent_connected
                else "实时快照链路已实现, 等待MiniQMT行情代理连接。"
            ),
            required_actions=(() if miniqmt_agent_connected else ("连接MiniQMT只读行情代理",)),
        ),
        SystemCapability(
            module_key="market_subscription",
            implementation_status="WORKING",
            data_status="READY" if miniqmt_agent_connected else "UNKNOWN",
            configuration_status="READY" if miniqmt_agent_connected else "MISSING",
            available=miniqmt_agent_connected,
            reason="期望订阅、实际订阅和失败事实已分离保存。",
            required_actions=(
                () if miniqmt_agent_connected else ("启用自选列表盘中监控并启动行情代理",)
            ),
        ),
        SystemCapability(
            module_key="intraday_persistence",
            implementation_status="WORKING",
            data_status="READY" if intraday_ready else "MISSING",
            configuration_status=("READY" if settings.miniqmt_market_data_enabled else "DISABLED"),
            available=intraday_ready,
            reason="MiniQMT 1分钟Bar接入D03 PostgreSQL MarketBar。",
            required_actions=(() if intraday_ready else ("启动行情代理并等待分钟Bar封板",)),
        ),
        SystemCapability(
            module_key="miniqmt_trading",
            implementation_status="DISABLED",
            data_status="NOT_REQUIRED",
            configuration_status="DISABLED",
            available=False,
            reason="当前系统仅启用MiniQMT只读行情能力",
            required_actions=(),
        ),
        SystemCapability(
            module_key="audit",
            implementation_status="PARTIAL",
            data_status="READY" if database_ready else "UNKNOWN",
            configuration_status="NOT_REQUIRED",
            available=False,
            reason="各业务链路已有审计事实; 统一审计中心仍是计划功能。",
            required_actions=("后续实现统一审计查询 API 与页面",),
        ),
        SystemCapability(
            module_key="settings",
            implementation_status="WORKING",
            data_status="NOT_REQUIRED",
            configuration_status="READY",
            available=True,
            reason="只读设置与安全边界说明可查看。",
        ),
    )
