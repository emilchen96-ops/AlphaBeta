from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.accounting import AccountQueryService, SimulatedAccountService
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.demo import ResearchDemoInitializationService
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.enums import SettlementPolicy
from alphadesk_domain.scanners import ScannerRegistry, register_builtin_scanners
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies
from tests.helpers import require_bt01_test_database_url

pytestmark = [pytest.mark.integration, pytest.mark.bt01]


@pytest.mark.asyncio
async def test_u01_fixture_builds_full_chain_and_replays_idempotently(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    require_bt01_test_database_url()
    factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))
    strategies = StrategyRegistry()
    scanners = ScannerRegistry()
    register_builtin_strategies(strategies)
    register_builtin_scanners(scanners)
    service = ResearchDemoInitializationService(
        factory,
        strategies,
        scanners,
        Settings(environment="test", postgres_host="unused", redis_host="unused"),
    )
    ordinary = await SimulatedAccountService(factory).create(
        account_code="U01-NON-DEMO-CONTROL",
        name="non demo control",
        base_currency="CNY",
        initial_cash=Decimal("54321"),
        settlement_policy=SettlementPolicy.IMMEDIATE,
        idempotency_key="u01-non-demo-control-v1",
    )
    _, cash_before, positions_before = await AccountQueryService(factory).detail(ordinary.id)

    first = await service.initialize(mode="fixture")
    repeated = await service.initialize(mode="fixture")
    reset_replay = await service.initialize(mode="fixture", reset_demo=True)
    first_steps = {item.key: item for item in first.steps}
    repeated_steps = {item.key: item for item in repeated.steps}

    assert first.status == "READY"
    assert first_steps["scanner:volume_anomaly"].status == "READY"
    assert first_steps["scanner:limit_up_pullback"].status == "READY"
    assert "BUY, SELL" in first_steps["strategy"].message
    for key in ("strategy", "experiment", "backtest", "ai_research", "risk_order"):
        assert first_steps[key].entity_id == repeated_steps[key].entity_id
    assert repeated_steps["simulated_broker"].replayed is True
    assert {item.key for item in reset_replay.steps} >= {"reset", "accounting"}
    _, cash_after, positions_after = await AccountQueryService(factory).detail(ordinary.id)
    assert cash_after == cash_before
    assert positions_after == positions_before
