"""Unified UX02 quick-backtest workflow backed by the complete BT01 engine."""

from __future__ import annotations

import builtins
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
    price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.QFQ
    commission_rate: Decimal = Decimal("0.0003")
    minimum_commission: Decimal = Decimal("5")
    stamp_duty_rate: Decimal = Decimal("0.0005")
    transfer_fee_rate: Decimal = Decimal("0.00001")
    slippage_basis_points: Decimal = Decimal("2")
    maximum_volume_participation: Decimal | None = Decimal("0.1")
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
                order_type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
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
        return dict(result)

    async def detail(self, run_id: UUID) -> dict[str, Any]:
        detail = await self._backtests.detail(run_id)
        async with self._uow_factory() as uow:
            snapshot = await uow.research_backtest_specs.get_by_run(run_id)
        if snapshot is not None:
            detail["strategy_spec"] = strategy_spec_to_dict(snapshot.spec)
            detail["strategy_preview"] = strategy_spec_preview(snapshot.spec)
        detail["simulation_notice"] = "回测仅为历史模拟, 不会发送给券商。"
        return detail

    async def summary(self, run_id: UUID) -> dict[str, Any]:
        detail = await self.detail(run_id)
        metrics = detail.get("metrics")
        fills = int(detail.get("fills_generated", 0))
        explanation: builtins.list[str] = []
        if fills == 0:
            explanation = [
                "当前区间没有产生模拟成交。",
                "可能原因包括策略条件较严格、数据范围较短或历史行情缺失。",
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
