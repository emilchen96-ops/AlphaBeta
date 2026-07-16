from datetime import timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.strategy_experiments import (
    StrategyExperimentIntegrityService,
    StrategyExperimentQueryService,
    StrategyExperimentRequest,
    StrategyExperimentService,
)
from alphadesk_api.infrastructure.models import (
    AccountCashBalanceModel,
    FillModel,
    OrderModel,
    PositionModel,
    StrategyExperimentModel,
)
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.enums import MarketTimeframe, OrderSide, SignalType
from alphadesk_domain.strategy import (
    SignalDraft,
    StrategyBar,
    StrategyContext,
    StrategyMetadata,
    StrategyParameterDefinition,
    StrategyParameterType,
    StrategyRegistry,
)
from alphadesk_domain.strategy_examples import register_builtin_strategies
from alphadesk_domain.strategy_experiments import StrategyExperimentStatus
from tests.integration.test_s01_strategy_runner import NOW, seed_history


class ConditionalStrategy:
    metadata = StrategyMetadata(
        strategy_key="conditional_test",
        display_name="Conditional test",
        description="Test-only strategy with a controlled failing combination.",
        version="1.0.0",
        supported_timeframes=(MarketTimeframe.MINUTE_1,),
    )

    def __init__(self, parameters) -> None:
        self._fail = parameters["fail"]

    def initialize(self, context: StrategyContext) -> None:
        del context

    def on_bar(self, context: StrategyContext, bar: StrategyBar) -> list[SignalDraft]:
        if self._fail:
            raise RuntimeError("controlled test failure")
        return [
            SignalDraft(
                strategy_key=self.metadata.strategy_key,
                strategy_version=self.metadata.version,
                instrument_id=bar.instrument_id,
                signal_type=SignalType.ENTRY,
                side=OrderSide.BUY,
                generated_at=context.current_time,
                bar_timestamp=bar.timestamp,
                quantity=Decimal("100"),
                reference_price=bar.close,
                reason="controlled test signal",
            )
        ]

    def finalize(self, context: StrategyContext) -> None:
        del context


def service(
    factory: async_sessionmaker[AsyncSession], *, max_combinations: int = 50
) -> tuple[StrategyExperimentService, StrategyExperimentQueryService]:
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    uow_factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(factory))
    return (
        StrategyExperimentService(uow_factory, registry, max_combinations=max_combinations),
        StrategyExperimentQueryService(uow_factory),
    )


def conditional_service(
    factory: async_sessionmaker[AsyncSession],
) -> StrategyExperimentService:
    registry = StrategyRegistry()
    registry.register(
        ConditionalStrategy.metadata,
        (
            StrategyParameterDefinition(
                name="fail",
                parameter_type=StrategyParameterType.BOOLEAN,
                required=False,
                default=False,
                description="Whether this test combination fails.",
            ),
        ),
        ConditionalStrategy,
    )
    return StrategyExperimentService(
        cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(factory)), registry
    )


def request(instrument_id, **changes) -> StrategyExperimentRequest:
    values = {
        "idempotency_key": f"experiment-{uuid4()}",
        "strategy_key": "sma_crossover",
        "parameter_grid": {"short_window": [2, 3], "long_window": [4]},
        "instrument_ids": (instrument_id,),
        "timeframe": MarketTimeframe.MINUTE_1,
        "start_at": NOW,
        "end_at": NOW + timedelta(minutes=8),
    }
    values.update(changes)
    return StrategyExperimentRequest(**values)


@pytest.mark.integration
@pytest.mark.s01
@pytest.mark.asyncio
async def test_batch_experiment_persists_comparisons_and_has_no_trading_side_effects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    instrument = await seed_history(
        session_factory,
        closes=("3", "2", "1", "4", "5", "0.5", "4", "5"),
        volumes=("100",) * 8,
    )
    protected = (OrderModel, FillModel, AccountCashBalanceModel, PositionModel)
    async with session_factory() as session:
        before = [
            await session.scalar(select(func.count()).select_from(model)) for model in protected
        ]
    experiment_service, query = service(session_factory)
    result = await experiment_service.run(request(instrument.id))
    assert result.experiment.status is StrategyExperimentStatus.COMPLETED
    assert result.experiment.runs_completed == 2
    assert result.experiment.runs_failed == 0

    runs = await query.list_runs(result.experiment.id)
    comparison = await query.comparison(result.experiment.id)
    overlap = await query.signal_overlap(result.experiment.id)
    integrity = await StrategyExperimentIntegrityService(
        cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))
    ).check(result.experiment.id)
    assert [item.combination_index for item in runs] == [1, 2]
    assert [item.combination_index for item in comparison] == [1, 2]
    assert len(overlap) == 1 and Decimal(overlap[0].similarity) <= 1
    assert integrity.is_valid
    async with session_factory() as session:
        after = [
            await session.scalar(select(func.count()).select_from(model)) for model in protected
        ]
        assert after == before


@pytest.mark.integration
@pytest.mark.s01
@pytest.mark.asyncio
async def test_experiment_idempotency_conflict_and_combination_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    instrument = await seed_history(session_factory)
    experiment_service, _ = service(session_factory, max_combinations=2)
    original = request(instrument.id, idempotency_key=f"stable-{uuid4()}")
    first = await experiment_service.run(original)
    replay = await experiment_service.run(original)
    assert replay.replayed and replay.experiment.id == first.experiment.id
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(StrategyExperimentModel)
                .where(StrategyExperimentModel.idempotency_key == original.idempotency_key)
            )
            == 1
        )
    with pytest.raises(ApplicationError) as conflict:
        await experiment_service.run(
            request(
                instrument.id,
                idempotency_key=original.idempotency_key,
                end_at=NOW + timedelta(minutes=7),
            )
        )
    assert conflict.value.code == "STRATEGY_EXPERIMENT_IDEMPOTENCY_CONFLICT"
    with pytest.raises(ApplicationError) as too_large:
        await experiment_service.run(
            request(
                instrument.id,
                parameter_grid={"short_window": [2, 3, 4], "long_window": [5]},
            )
        )
    assert too_large.value.code == "STRATEGY_EXPERIMENT_TOO_LARGE"
    assert too_large.value.details == {"actual_count": 3, "max_combinations": 2}


@pytest.mark.integration
@pytest.mark.s01
@pytest.mark.asyncio
async def test_partial_and_complete_failure_statuses_preserve_successful_signals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    instrument = await seed_history(session_factory)
    service_under_test = conditional_service(session_factory)
    partial = await service_under_test.run(
        StrategyExperimentRequest(
            idempotency_key=f"partial-{uuid4()}",
            strategy_key="conditional_test",
            parameter_grid={"fail": [False, True]},
            instrument_ids=(instrument.id,),
            timeframe=MarketTimeframe.MINUTE_1,
            start_at=NOW,
            end_at=NOW + timedelta(minutes=8),
        )
    )
    assert partial.experiment.status is StrategyExperimentStatus.PARTIAL_FAILED
    assert partial.experiment.runs_completed == partial.experiment.runs_failed == 1
    assert partial.experiment.total_signals == 8

    failed = await service_under_test.run(
        StrategyExperimentRequest(
            idempotency_key=f"failed-{uuid4()}",
            strategy_key="conditional_test",
            parameter_grid={"fail": [True]},
            instrument_ids=(instrument.id,),
            timeframe=MarketTimeframe.MINUTE_1,
            start_at=NOW,
            end_at=NOW + timedelta(minutes=8),
        )
    )
    assert failed.experiment.status is StrategyExperimentStatus.FAILED
    assert failed.experiment.runs_completed == 0
    assert failed.experiment.runs_failed == 1
