"""Authoritative, read-only I01 system capability assessment."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from alphadesk_api.core.config import Settings

ImplementationStatus = Literal["WORKING", "PARTIAL", "PLACEHOLDER", "NOT_IMPLEMENTED"]
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
) -> tuple[SystemCapability, ...]:
    """Assess what can be used now without mutating business facts."""

    database_ready = data.database_reachable
    instruments_ready = database_ready and _has(data.instrument_count)
    bars_ready = instruments_ready and _has(data.daily_market_bar_count)
    accounts_ready = database_ready and _has(data.simulated_account_count)
    information_ready = database_ready and _has(data.information_item_count)
    executable_order_ready = database_ready and _has(data.executable_order_count)

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
        historical_capability("historical_market_data", "历史行情查询"),
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
            module_key="realtime_market_data",
            implementation_status="PARTIAL",
            data_status="UNKNOWN",
            configuration_status="DISABLED",
            available=False,
            reason=(
                "Redis/WebSocket 管道保留, 但实时 Provider "
                f"{settings.realtime_market_provider} 按安全基线禁用。"
            ),
            required_actions=("后续通过受控行情适配器提供交易级实时数据",),
        ),
        SystemCapability(
            module_key="miniqmt",
            implementation_status="NOT_IMPLEMENTED",
            data_status="NOT_REQUIRED",
            configuration_status="DISABLED",
            available=False,
            reason="Windows Agent、XtQuant Adapter 与真实券商链路尚未实现。",
            required_actions=("完成 Windows Agent、安全命令回执、最终风控与对账后再接入",),
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
