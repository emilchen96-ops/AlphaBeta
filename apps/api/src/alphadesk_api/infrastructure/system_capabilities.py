"""Read-only SQLAlchemy data snapshot for the I01 capability endpoint."""

from sqlalchemy import distinct, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.system_capabilities import CapabilityDataSnapshot
from alphadesk_api.infrastructure.models import (
    AIAnalysisRunModel,
    FillModel,
    InformationItemModel,
    InformationSourceModel,
    InstrumentModel,
    MarketBarModel,
    MarketEventModel,
    OrderModel,
    RiskDecisionModel,
    ScanRunModel,
    StrategyExperimentModel,
    StrategyRunModel,
    TradingAccountModel,
)


class UnavailableCapabilityDataProvider:
    async def snapshot(self) -> CapabilityDataSnapshot:
        return CapabilityDataSnapshot(database_reachable=False)


class SqlAlchemyCapabilityDataProvider:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def snapshot(self) -> CapabilityDataSnapshot:
        try:
            async with self._session_factory() as session:
                row = (
                    await session.execute(
                        select(
                            select(func.count())
                            .select_from(InstrumentModel)
                            .where(InstrumentModel.is_active.is_(True))
                            .scalar_subquery()
                            .label("instrument_count"),
                            select(func.count())
                            .select_from(MarketBarModel)
                            .scalar_subquery()
                            .label("market_bar_count"),
                            select(func.count())
                            .select_from(MarketBarModel)
                            .where(MarketBarModel.timeframe == "DAY_1")
                            .scalar_subquery()
                            .label("daily_market_bar_count"),
                            select(func.count(distinct(MarketBarModel.instrument_id)))
                            .where(MarketBarModel.timeframe == "DAY_1")
                            .scalar_subquery()
                            .label("market_bar_instrument_count"),
                            select(func.min(MarketBarModel.bar_time))
                            .scalar_subquery()
                            .label("earliest_market_bar_at"),
                            select(func.max(MarketBarModel.bar_time))
                            .scalar_subquery()
                            .label("latest_market_bar_at"),
                            select(func.count())
                            .select_from(TradingAccountModel)
                            .where(TradingAccountModel.account_type == "SIMULATED")
                            .scalar_subquery()
                            .label("simulated_account_count"),
                            select(func.count())
                            .select_from(ScanRunModel)
                            .scalar_subquery()
                            .label("scan_run_count"),
                            select(func.count())
                            .select_from(StrategyRunModel)
                            .scalar_subquery()
                            .label("strategy_run_count"),
                            select(func.count())
                            .select_from(StrategyExperimentModel)
                            .scalar_subquery()
                            .label("strategy_experiment_count"),
                            select(func.count())
                            .select_from(InformationSourceModel)
                            .scalar_subquery()
                            .label("information_source_count"),
                            select(func.count())
                            .select_from(InformationItemModel)
                            .scalar_subquery()
                            .label("information_item_count"),
                            select(func.count())
                            .select_from(MarketEventModel)
                            .scalar_subquery()
                            .label("market_event_count"),
                            select(func.count())
                            .select_from(AIAnalysisRunModel)
                            .scalar_subquery()
                            .label("ai_analysis_run_count"),
                            select(func.count())
                            .select_from(OrderModel)
                            .scalar_subquery()
                            .label("order_count"),
                            select(func.count())
                            .select_from(OrderModel)
                            .where(
                                OrderModel.status.in_(
                                    ("QUEUED", "BROKER_ACCEPTED", "PARTIALLY_FILLED")
                                )
                            )
                            .scalar_subquery()
                            .label("executable_order_count"),
                            select(func.count())
                            .select_from(FillModel)
                            .scalar_subquery()
                            .label("fill_count"),
                            select(func.count())
                            .select_from(RiskDecisionModel)
                            .scalar_subquery()
                            .label("risk_decision_count"),
                        )
                    )
                ).one()
            return CapabilityDataSnapshot(database_reachable=True, **row._asdict())
        except SQLAlchemyError:
            return CapabilityDataSnapshot(database_reachable=False)
