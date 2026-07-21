from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_api.application.replays import replay_interval_seconds
from alphadesk_api.core.config import Settings
from alphadesk_domain.backtest import (
    BacktestConfiguration,
    BacktestPhase,
    BacktestSession,
    HistoricalSessionProcessor,
)
from alphadesk_domain.broker import FixedBasisPointsSlippageModel
from alphadesk_domain.enums import MarketTimeframe, OrderType, TimeInForce
from alphadesk_domain.replay import (
    ReplayConfiguration,
    ReplayControlActionType,
    ReplayError,
    ReplayRun,
    ReplayRunStatus,
    ReplaySpeedMode,
    replay_action_fingerprint,
    replay_request_fingerprint,
)


def configuration(speed: ReplaySpeedMode = ReplaySpeedMode.MANUAL) -> ReplayConfiguration:
    return ReplayConfiguration(
        execution=BacktestConfiguration(
            strategy_key="sma_crossover",
            strategy_version="1.0.0",
            parameters={"short_window": 2, "long_window": 3, "quantity": "100"},
            instrument_ids=(uuid4(),),
            timeframe=MarketTimeframe.DAY_1,
            start_at=datetime(2024, 1, 1, tzinfo=UTC),
            end_at=datetime(2024, 2, 1, tzinfo=UTC),
            initial_cash=Decimal("100000"),
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            slippage_configuration=FixedBasisPointsSlippageModel(basis_points=Decimal("2")),
        ),
        speed_mode=speed,
    )


def replay_run() -> ReplayRun:
    config = configuration()
    return ReplayRun(
        idempotency_key="replay-test",
        request_fingerprint=replay_request_fingerprint(config),
        configuration=config,
        correlation_id=uuid4(),
        total_sessions=3,
    )


def test_replay_state_machine_supports_ready_running_pause_resume_and_completion() -> None:
    run = replay_run()
    occurred_at = datetime(2024, 1, 2, tzinfo=UTC)
    run.transition(ReplayRunStatus.READY, occurred_at)
    run.transition(ReplayRunStatus.RUNNING, occurred_at)
    run.transition(ReplayRunStatus.PAUSED, occurred_at)
    run.transition(ReplayRunStatus.RUNNING, occurred_at)
    run.transition(ReplayRunStatus.COMPLETED, occurred_at)
    assert run.status is ReplayRunStatus.COMPLETED
    assert run.row_version == 5
    with pytest.raises(ReplayError, match="terminal") as error:
        run.transition(ReplayRunStatus.RUNNING, occurred_at)
    assert error.value.code == "REPLAY_TERMINAL_STATE"


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (ReplayRunStatus.CREATED, ReplayRunStatus.RUNNING),
        (ReplayRunStatus.READY, ReplayRunStatus.PAUSED),
        (ReplayRunStatus.PAUSED, ReplayRunStatus.COMPLETED),
    ],
)
def test_invalid_state_transitions_are_stable(
    source: ReplayRunStatus, target: ReplayRunStatus
) -> None:
    run = replay_run()
    run.status = source
    with pytest.raises(ReplayError) as error:
        run.transition(target, datetime(2024, 1, 2, tzinfo=UTC))
    assert error.value.code == "REPLAY_INVALID_TRANSITION"


def test_fingerprints_include_speed_and_expected_version() -> None:
    assert replay_request_fingerprint(
        configuration(ReplaySpeedMode.X1)
    ) != replay_request_fingerprint(configuration(ReplaySpeedMode.X10))
    run_id = uuid4()
    assert replay_action_fingerprint(
        run_id, ReplayControlActionType.STEP, 1, None
    ) != replay_action_fingerprint(run_id, ReplayControlActionType.STEP, 2, None)


def test_bt01_session_time_model_remains_the_replay_business_clock() -> None:
    session = BacktestSession(trading_date=date(2024, 1, 2), instrument_ids=(uuid4(),))
    assert session.time_for(BacktestPhase.SESSION_OPEN).date() == date(2024, 1, 2)


def test_shared_session_processor_advances_exactly_one_stably_ordered_session() -> None:
    instrument_ids = (uuid4(), uuid4())
    sessions = [
        BacktestSession(trading_date=date(2024, 1, 3), instrument_ids=instrument_ids),
        BacktestSession(trading_date=date(2024, 1, 2), instrument_ids=instrument_ids),
    ]
    processor = HistoricalSessionProcessor(sessions)
    first = processor.process_next_session()
    assert first.session.trading_date == date(2024, 1, 2)
    assert first.next_session_index == 1
    assert not first.completed
    second = processor.process_next_session()
    assert second.session.trading_date == date(2024, 1, 3)
    assert second.completed


def test_speed_changes_only_wall_clock_interval() -> None:
    settings = Settings(environment="test")
    assert replay_interval_seconds(settings, ReplaySpeedMode.MANUAL) is None
    assert replay_interval_seconds(settings, ReplaySpeedMode.X1) == 1.0
    assert replay_interval_seconds(settings, ReplaySpeedMode.X10) == 0.25
    assert replay_interval_seconds(settings, ReplaySpeedMode.X100) == 0.05
