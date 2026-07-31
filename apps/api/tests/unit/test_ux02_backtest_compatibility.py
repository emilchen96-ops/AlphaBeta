import logging
import runpy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from alphadesk_api.infrastructure.models import BacktestRunModel
from alphadesk_api.infrastructure.repositories import (
    _backtest_run_from_model,
    _backtest_run_values,
)
from alphadesk_domain.backtest import (
    BacktestConfiguration,
    BacktestError,
    BacktestRun,
    backtest_configuration_from_dict,
    backtest_configuration_to_dict,
    backtest_request_fingerprint,
)
from alphadesk_domain.enums import MarketTimeframe

pytestmark = [pytest.mark.unit, pytest.mark.bt01]


def configuration() -> BacktestConfiguration:
    return BacktestConfiguration(
        strategy_key="sma_crossover",
        strategy_version="1.0.0",
        parameters={"short_window": 5, "long_window": 20, "quantity": Decimal("100")},
        instrument_ids=(uuid4(),),
        timeframe=MarketTimeframe.DAY_1,
        start_at=datetime(2025, 1, 1, tzinfo=UTC),
        end_at=datetime(2025, 2, 1, tzinfo=UTC),
        initial_cash=Decimal("100000"),
    )


def test_legacy_d02_migration_adds_adjustment_mode_and_recomputes_fingerprint() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0022_ux02_backtest_fingerprint_repair.py"
    )
    migration = runpy.run_path(str(migration_path))
    repair = migration["repair_legacy_configuration"]
    value = backtest_configuration_to_dict(configuration())
    value.pop("strategy_price_adjustment_mode")

    repaired, fingerprint = repair(value, "RAW")

    assert repaired["strategy_price_adjustment_mode"] == "RAW"
    assert fingerprint == backtest_request_fingerprint(backtest_configuration_from_dict(repaired))


def test_bt01_execution_migration_adds_legacy_policy_and_recomputes_fingerprint() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "0028_bt01_execution_price_policy.py"
    )
    migration = runpy.run_path(str(migration_path))
    repair = migration["repair_legacy_configuration"]
    value = backtest_configuration_to_dict(configuration())
    value.pop("execution_price_mode")
    value.pop("maximum_entry_gap_ratio")

    repaired, fingerprint = repair(value)

    assert repaired["execution_price_mode"] == "NEXT_OPEN"
    assert repaired["maximum_entry_gap_ratio"] is None
    assert fingerprint == backtest_request_fingerprint(backtest_configuration_from_dict(repaired))


def test_backtest_list_projection_tolerates_one_bad_fingerprint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = configuration()
    run = BacktestRun(
        idempotency_key="legacy-backtest",
        request_fingerprint=backtest_request_fingerprint(config),
        configuration=config,
        correlation_id=uuid4(),
    )
    values = _backtest_run_values(run)
    values["request_fingerprint"] = "0" * 64
    model = BacktestRunModel(**values)

    with pytest.raises(BacktestError, match="request fingerprint"):
        _backtest_run_from_model(model)

    with caplog.at_level(logging.ERROR):
        recovered = _backtest_run_from_model(model, tolerate_fingerprint_mismatch=True)

    assert recovered.id == run.id
    assert recovered.request_fingerprint == backtest_request_fingerprint(config)
    assert "mismatched persisted fingerprint" in caplog.text
