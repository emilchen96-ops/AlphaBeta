from dataclasses import dataclass

import pytest

from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.demo import (
    ResearchDemoInitializationService,
    ResearchDemoVerificationService,
)
from alphadesk_api.application.system_capabilities import CapabilityDataSnapshot
from alphadesk_api.core.config import Settings
from alphadesk_domain.scanners import ScannerRegistry, register_builtin_scanners
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies


@dataclass
class SnapshotProvider:
    data: CapabilityDataSnapshot

    async def snapshot(self) -> CapabilityDataSnapshot:
        return self.data


def registries() -> tuple[StrategyRegistry, ScannerRegistry]:
    strategies = StrategyRegistry()
    scanners = ScannerRegistry()
    register_builtin_strategies(strategies)
    register_builtin_scanners(scanners)
    return strategies, scanners


@pytest.mark.asyncio
async def test_dry_run_is_read_only_and_describes_no_network() -> None:
    strategies, scanners = registries()

    def forbidden_factory():
        raise AssertionError("dry-run must not open a unit of work")

    result = await ResearchDemoInitializationService(
        forbidden_factory,
        strategies,
        scanners,
        Settings(environment="test", postgres_host="unused", redis_host="unused"),
    ).initialize(mode="fixture", dry_run=True)

    assert result.status == "READY"
    assert result.dry_run is True
    assert {item.key for item in result.steps} == {"preflight", "network"}


@pytest.mark.asyncio
async def test_initialization_is_blocked_outside_development_and_test() -> None:
    strategies, scanners = registries()
    service = ResearchDemoInitializationService(
        lambda: None,  # type: ignore[arg-type,return-value]
        strategies,
        scanners,
        Settings(
            environment="production",
            postgres_host="unused",
            redis_host="unused",
            postgres_password="not-the-default",
        ),
    )

    with pytest.raises(ApplicationError, match="development/test"):
        await service.initialize(mode="fixture", dry_run=True)


@pytest.mark.asyncio
async def test_verification_separates_ready_disabled_and_not_implemented() -> None:
    result = await ResearchDemoVerificationService(
        SnapshotProvider(
            CapabilityDataSnapshot(
                database_reachable=True,
                migration_head="0016_rt01",
                daily_market_bar_count=260,
                scan_run_count=2,
                strategy_run_count=3,
                strategy_experiment_count=1,
                backtest_run_count=1,
                replay_run_count=1,
                information_item_count=1,
                market_event_count=1,
                ai_analysis_run_count=1,
                simulated_account_count=1,
                risk_decision_count=1,
                order_count=1,
                fill_count=1,
            )
        ),
        Settings(environment="test", postgres_host="unused", redis_host="unused"),
        postgresql_ok=True,
        redis_ok=True,
    ).verify()
    by_key = {item.key: item for item in result.items}

    assert result.status == "READY"
    assert by_key["historical_market_data"].status == "READY"
    assert by_key["realtime_market_data"].status == "DISABLED"
    assert by_key["miniqmt"].status == "NOT_IMPLEMENTED"
