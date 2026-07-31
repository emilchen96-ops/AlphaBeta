"""Unified UX02 quick-backtest workflow backed by the complete BT01 engine."""

# ruff: noqa: RUF001

from __future__ import annotations

import builtins
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from alphadesk_api.application.backtests import (
    BacktestQueryService,
    BacktestService,
    CreateBacktestRequest,
)
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.core.config import Settings
from alphadesk_domain.backtest import BacktestExecutionPriceMode
from alphadesk_domain.broker import AshareSimpleFeeModel, FixedBasisPointsSlippageModel
from alphadesk_domain.enums import MarketTimeframe, OrderType, TimeInForce
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_spec import (
    ResearchBacktestSpecSnapshot,
    StrategySpec,
    StrategySpecCompiler,
    strategy_spec_preview,
    strategy_spec_to_dict,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class QuickBacktestRequest:
    instrument_id: UUID
    start_at: datetime
    end_at: datetime
    initial_cash: Decimal
    spec: StrategySpec | None = None
    user_strategy_id: UUID | None = None
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW
    commission_rate: Decimal = Decimal("0.0003")
    minimum_commission: Decimal = Decimal("5")
    stamp_duty_rate: Decimal = Decimal("0.0005")
    transfer_fee_rate: Decimal = Decimal("0.00001")
    slippage_basis_points: Decimal = Decimal("2")
    maximum_volume_participation: Decimal | None = Decimal("0.1")
    execution_price_mode: BacktestExecutionPriceMode = BacktestExecutionPriceMode.NEXT_OPEN
    position_size_ratio: Decimal | None = Decimal("1")
    maximum_entry_gap_ratio: Decimal | None = Decimal("0.05")
    time_in_force: TimeInForce = TimeInForce.DAY
    idempotency_key: str | None = None
    correlation_id: UUID | None = None


class QuickBacktestService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: StrategyRegistry,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._settings = settings

    async def run(self, request: QuickBacktestRequest) -> dict[str, Any]:
        spec, user_strategy_id, version_id = await self._resolve_spec(request)
        strategy_key = StrategySpecCompiler().register(self._registry, spec)
        service = BacktestService(self._uow_factory, self._registry, self._settings)
        result = await service.run(
            CreateBacktestRequest(
                strategy_key=strategy_key,
                parameters={},
                instrument_ids=(request.instrument_id,),
                timeframe=MarketTimeframe.DAY_1,
                start_at=request.start_at,
                end_at=request.end_at,
                initial_cash=request.initial_cash,
                order_type=(
                    OrderType.MARKET
                    if request.execution_price_mode
                    is not BacktestExecutionPriceMode.SIGNAL_CLOSE_LIMIT
                    else OrderType.LIMIT
                ),
                time_in_force=request.time_in_force,
                execution_price_mode=request.execution_price_mode,
                position_size_ratio=request.position_size_ratio,
                maximum_entry_gap_ratio=request.maximum_entry_gap_ratio,
                fee_configuration=AshareSimpleFeeModel(
                    commission_rate=request.commission_rate,
                    minimum_commission=request.minimum_commission,
                    stamp_duty_rate=request.stamp_duty_rate,
                    transfer_fee_rate=request.transfer_fee_rate,
                ),
                slippage_configuration=FixedBasisPointsSlippageModel(
                    basis_points=request.slippage_basis_points,
                ),
                maximum_volume_participation=request.maximum_volume_participation,
                benchmark_symbol=None,
                data_source_code=self._settings.authoritative_market_source,
                idempotency_key=(request.idempotency_key or f"research-quick:{uuid4()}"),
                correlation_id=request.correlation_id,
                strategy_price_adjustment_mode=request.price_adjustment_mode,
            )
        )
        await self._save_snapshot(
            run_id=result.run.id,
            spec=spec,
            user_strategy_id=user_strategy_id,
            version_id=version_id,
        )
        detail = await BacktestQueryService(self._uow_factory).detail(result.run.id)
        detail.update(
            {
                "replayed": result.replayed,
                "strategy_spec": strategy_spec_to_dict(spec),
                "strategy_preview": strategy_spec_preview(spec),
                "simulation_notice": "回测仅为历史模拟, 不会发送给券商。",
            }
        )
        return detail

    async def _resolve_spec(
        self, request: QuickBacktestRequest
    ) -> tuple[StrategySpec, UUID | None, UUID | None]:
        if (request.spec is None) == (request.user_strategy_id is None):
            raise ApplicationError(
                "QUICK_BACKTEST_STRATEGY_REQUIRED",
                "必须且只能提供策略规则或我的策略编号之一",
            )
        if request.spec is not None:
            return request.spec, None, None
        assert request.user_strategy_id is not None
        async with self._uow_factory() as uow:
            definition = await uow.user_strategies.get_definition(request.user_strategy_id)
            version = await uow.user_strategies.get_version(request.user_strategy_id)
        if definition is None or version is None or definition.archived:
            raise ApplicationError("USER_STRATEGY_NOT_FOUND", "没有找到可用的策略")
        return version.spec, definition.id, version.id

    async def _save_snapshot(
        self,
        *,
        run_id: UUID,
        spec: StrategySpec,
        user_strategy_id: UUID | None,
        version_id: UUID | None,
    ) -> None:
        async with self._uow_factory() as uow:
            existing = await uow.research_backtest_specs.get_by_run(run_id)
            if existing is None:
                await uow.research_backtest_specs.save(
                    ResearchBacktestSpecSnapshot(
                        id=uuid4(),
                        backtest_run_id=run_id,
                        user_strategy_id=user_strategy_id,
                        user_strategy_version_id=version_id,
                        spec=spec,
                    )
                )
                await uow.commit()


class ResearchBacktestQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory
        self._backtests = BacktestQueryService(uow_factory)

    async def list(self, *, page: int, page_size: int) -> dict[str, Any]:
        result = await self._backtests.list(page=page, page_size=page_size, status=None)
        items: list[dict[str, Any]] = []
        for item in result["items"]:
            items.append(await self.detail(UUID(str(item["id"]))))
        return {**dict(result), "items": items}

    async def detail(self, run_id: UUID) -> dict[str, Any]:
        detail = await self._backtests.detail(run_id)
        async with self._uow_factory() as uow:
            snapshot = await uow.research_backtest_specs.get_by_run(run_id)
            parent = await uow.backtest_batches.get_parent_for_run(run_id)
            raw_configuration = detail.get("configuration")
            configuration = (
                dict(raw_configuration) if isinstance(raw_configuration, Mapping) else {}
            )
            raw_instrument_ids = configuration.get("instrument_ids", [])
            instrument_ids = (
                [UUID(str(value)) for value in raw_instrument_ids]
                if isinstance(raw_instrument_ids, (list, tuple))
                else []
            )
            instruments = await uow.instruments.get_many(instrument_ids)
        if snapshot is not None:
            detail["strategy_spec"] = strategy_spec_to_dict(snapshot.spec)
            detail["strategy_preview"] = strategy_spec_preview(snapshot.spec)
        raw_preview = detail.get("strategy_preview", [])
        preview = (
            [str(value) for value in raw_preview] if isinstance(raw_preview, (list, tuple)) else []
        )
        strategy_key = str(detail.get("strategy_key", ""))
        strategy_name = (
            _readable_strategy_name(snapshot.spec.name, strategy_key)
            if snapshot is not None
            else _strategy_fallback_name(strategy_key)
        )
        strategy_summary = (
            "；".join(preview[:2]) if preview else "历史策略回测（旧记录未保存完整策略快照）"
        )
        instrument_display = "、".join(
            f"{item.name}（{item.symbol}.{item.exchange}）" for item in instruments
        )
        parent_batch = None if parent is None else parent[0]
        run_source = "BATCH_CHILD" if parent_batch is not None else "DIRECT"
        detail.update(
            {
                "display_name": (f"{instrument_display or '历史标的'} · {strategy_name}"),
                "instrument_display": instrument_display or "历史标的（信息待补全）",
                "strategy_display_name": strategy_name,
                "strategy_summary": strategy_summary,
                "run_source": run_source,
                "backtest_type": "批量独立回测子任务" if parent_batch else "单股回测",
                "parent_batch_id": None if parent_batch is None else parent_batch.id,
                "parent_batch_name": None if parent_batch is None else parent_batch.name,
                "start_at": configuration.get("start_at"),
                "end_at": configuration.get("end_at"),
            }
        )
        detail["simulation_notice"] = "回测仅为历史模拟, 不会发送给券商。"
        return detail

    async def summary(self, run_id: UUID) -> dict[str, Any]:
        detail = await self.detail(run_id)
        metrics = detail.get("metrics")
        fills = int(detail.get("fills_generated", 0))
        explanation: builtins.list[str] = []
        if fills == 0:
            async with self._uow_factory() as uow:
                events = await uow.backtest_events.list_by_run(run_id)
            gap_events = [
                event
                for event in events
                if event.details.get("code") == "BACKTEST_ENTRY_GAP_EXCEEDED"
            ]
            if gap_events:
                explanation = [
                    "策略产生了买入信号, 但下一交易日高开超过设置的最大允许幅度。",
                    (
                        f"共有 {len(gap_events)} 次买入因不追高规则未成交; "
                        "可在再次回测时提高“最大允许高开幅度”, 或改为继续等待后续交易日。"
                    ),
                ]
            else:
                explanation = [
                    "当前区间没有产生模拟成交。",
                    "可能原因包括策略条件较严格、风控未通过、数据范围较短或历史行情缺失。",
                ]
        return {
            "run_id": run_id,
            "status": detail["status"],
            "metrics": metrics,
            "signals_generated": detail["signals_generated"],
            "fills_generated": fills,
            "explanation": explanation,
            "strategy_preview": detail.get("strategy_preview", []),
            "simulation_notice": detail["simulation_notice"],
        }

    async def trades(self, run_id: UUID) -> builtins.list[dict[str, Any]]:
        return [asdict(item) for item in await self._backtests.trades(run_id)]

    async def signals(self, run_id: UUID) -> builtins.list[dict[str, Any]]:
        return [asdict(item) for item in await self._backtests.signals(run_id)]

    async def equity(self, run_id: UUID) -> builtins.list[dict[str, Any]]:
        return [asdict(item) for item in await self._backtests.equity_curve(run_id)]


def _strategy_fallback_name(strategy_key: str) -> str:
    known = {
        "sma_crossover": "均线交叉策略",
        "volume_breakout": "放量突破策略",
        "atr_channel": "ATR 通道策略",
        "trend_pullback": "趋势回调策略",
    }
    if strategy_key in known:
        return known[strategy_key]
    if strategy_key.startswith("user_spec_"):
        return "自定义规则策略"
    return "历史策略回测"


def _readable_strategy_name(name: str, strategy_key: str) -> str:
    normalized = name.strip()
    mojibake_markers = ("Ã", "Â", "â", "æ", "ç", "å", "ä", "é", "è", "ï¿½", "�")
    if not normalized or any(marker in normalized for marker in mojibake_markers):
        return _strategy_fallback_name(strategy_key)
    return normalized
