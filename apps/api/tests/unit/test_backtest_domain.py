from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_domain.backtest import (
    BacktestClock,
    BacktestConfiguration,
    BacktestError,
    BacktestFillMetricInput,
    BacktestPerformanceService,
    BacktestPhase,
    BacktestSession,
    BacktestTradeSummary,
    backtest_request_fingerprint,
    build_equity_points,
)
from alphadesk_domain.broker import AshareSimpleFeeModel, FixedBasisPointsSlippageModel
from alphadesk_domain.enums import MarketTimeframe, OrderSide

pytestmark = [pytest.mark.unit, pytest.mark.bt01]


def _configuration(*, instruments: tuple = ()) -> BacktestConfiguration:
    return BacktestConfiguration(
        strategy_key="sma_crossover",
        strategy_version="1.0.0",
        parameters={"fast_window": 5, "slow_window": 20, "quantity": Decimal("100")},
        instrument_ids=instruments or (uuid4(), uuid4()),
        timeframe=MarketTimeframe.DAY_1,
        start_at=datetime(2025, 1, 1, tzinfo=UTC),
        end_at=datetime(2025, 2, 1, tzinfo=UTC),
        initial_cash=Decimal("100000"),
        fee_configuration=AshareSimpleFeeModel(),
        slippage_configuration=FixedBasisPointsSlippageModel(basis_points=Decimal("2")),
    )


def test_configuration_normalizes_instruments_and_has_stable_fingerprint() -> None:
    first, second = uuid4(), uuid4()
    left = _configuration(instruments=(second, first, second))
    right = _configuration(instruments=(first, second))

    assert left.instrument_ids == tuple(sorted((first, second), key=str))
    assert backtest_request_fingerprint(left) == backtest_request_fingerprint(right)


def test_configuration_rejects_naive_time_and_non_daily_timeframe() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        BacktestConfiguration(
            strategy_key="sma_crossover",
            strategy_version="1.0.0",
            parameters={},
            instrument_ids=(uuid4(),),
            timeframe=MarketTimeframe.DAY_1,
            start_at=datetime(2025, 1, 1),
            end_at=datetime(2025, 2, 1, tzinfo=UTC),
            initial_cash=Decimal("1"),
        )
    with pytest.raises(BacktestError) as error:
        BacktestConfiguration(
            strategy_key="sma_crossover",
            strategy_version="1.0.0",
            parameters={},
            instrument_ids=(uuid4(),),
            timeframe=MarketTimeframe.MINUTE_1,
            start_at=datetime(2025, 1, 1, tzinfo=UTC),
            end_at=datetime(2025, 2, 1, tzinfo=UTC),
            initial_cash=Decimal("1"),
        )
    assert error.value.code == "BACKTEST_TIMEFRAME_NOT_SUPPORTED"


def test_clock_emits_open_close_end_for_each_session_in_order() -> None:
    first, second = uuid4(), uuid4()
    clock = BacktestClock(
        [
            BacktestSession(trading_date=date(2025, 1, 3), instrument_ids=(second,)),
            BacktestSession(trading_date=date(2025, 1, 2), instrument_ids=(first, second)),
        ]
    )
    observed = []
    while not clock.is_complete:
        observed.append(
            (
                clock.current_session.trading_date,
                clock.current_phase,
                clock.current_time,
            )
        )
        clock.advance()

    assert [(item[0], item[1]) for item in observed] == [
        (date(2025, 1, 2), BacktestPhase.SESSION_OPEN),
        (date(2025, 1, 2), BacktestPhase.SESSION_CLOSE),
        (date(2025, 1, 2), BacktestPhase.SESSION_END),
        (date(2025, 1, 3), BacktestPhase.SESSION_OPEN),
        (date(2025, 1, 3), BacktestPhase.SESSION_CLOSE),
        (date(2025, 1, 3), BacktestPhase.SESSION_END),
    ]
    assert all(timestamp.tzinfo is UTC for _, _, timestamp in observed)


def test_equity_points_calculate_return_drawdown_without_future_values() -> None:
    run_id = uuid4()
    points = build_equity_points(
        run_id=run_id,
        initial_equity=Decimal("100"),
        snapshots=[
            (
                datetime(2025, 1, 2, 7, 1, tzinfo=UTC),
                Decimal("100"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                0,
                (),
            ),
            (
                datetime(2025, 1, 3, 7, 1, tzinfo=UTC),
                Decimal("60"),
                Decimal("50"),
                Decimal("50"),
                Decimal("50"),
                1,
                (),
            ),
            (
                datetime(2025, 1, 6, 7, 1, tzinfo=UTC),
                Decimal("60"),
                Decimal("28"),
                Decimal("28"),
                Decimal("28"),
                1,
                ("STALE_VALUATION",),
            ),
        ],
    )

    assert points[0].daily_return is None
    assert points[1].daily_return == Decimal("0.1")
    assert points[1].drawdown == Decimal("0")
    assert points[2].drawdown == Decimal("-0.2")
    assert points[2].warnings == ("STALE_VALUATION",)


def test_performance_metrics_cover_fees_drawdown_sharpe_and_trades() -> None:
    run_id, instrument_id = uuid4(), uuid4()
    points = build_equity_points(
        run_id=run_id,
        initial_equity=Decimal("100"),
        snapshots=[
            (
                datetime(2025, 1, 2, tzinfo=UTC),
                Decimal("100"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                0,
                (),
            ),
            (
                datetime(2025, 1, 3, tzinfo=UTC),
                Decimal("50"),
                Decimal("60"),
                Decimal("60"),
                Decimal("60"),
                1,
                (),
            ),
            (
                datetime(2025, 1, 6, tzinfo=UTC),
                Decimal("90"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                0,
                (),
            ),
        ],
    )
    fills = [
        BacktestFillMetricInput(
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            price=Decimal("5"),
            commission=Decimal("1"),
            stamp_duty=Decimal("0"),
            transfer_fee=Decimal("0.1"),
        ),
        BacktestFillMetricInput(
            side=OrderSide.SELL,
            quantity=Decimal("10"),
            price=Decimal("4"),
            commission=Decimal("1"),
            stamp_duty=Decimal("0.2"),
            transfer_fee=Decimal("0.1"),
        ),
    ]
    trades = [
        BacktestTradeSummary(
            run_id=run_id,
            instrument_id=instrument_id,
            opened_at=datetime(2025, 1, 2, tzinfo=UTC),
            closed_at=datetime(2025, 1, 6, tzinfo=UTC),
            quantity=Decimal("10"),
            entry_price=Decimal("5"),
            exit_price=Decimal("4"),
            gross_pnl=Decimal("-10"),
            fees=Decimal("2.4"),
            net_pnl=Decimal("-12.4"),
        )
    ]

    metrics = BacktestPerformanceService().calculate(
        run_id=run_id, equity_points=points, fills=fills, trades=trades
    )

    assert metrics.total_return == Decimal("-0.1")
    assert metrics.maximum_drawdown == Decimal("-0.18181818")
    assert metrics.annualized_volatility is not None
    assert metrics.sharpe_ratio is not None
    assert metrics.fill_count == 2
    assert metrics.total_turnover == Decimal("90")
    assert metrics.total_fees == Decimal("2.4")
    assert metrics.win_rate == Decimal("0")
    assert metrics.loss_rate == Decimal("1")
    assert metrics.profit_factor == Decimal("0")


def test_profit_factor_is_null_when_there_are_no_losses() -> None:
    run_id, instrument_id = uuid4(), uuid4()
    points = build_equity_points(
        run_id=run_id,
        initial_equity=Decimal("100"),
        snapshots=[
            (
                datetime(2025, 1, 2, tzinfo=UTC),
                Decimal("100"),
                Decimal("0"),
                Decimal("0"),
                Decimal("0"),
                0,
                (),
            )
        ],
    )
    trade = BacktestTradeSummary(
        run_id=run_id,
        instrument_id=instrument_id,
        opened_at=datetime(2025, 1, 1, tzinfo=UTC),
        closed_at=datetime(2025, 1, 2, tzinfo=UTC),
        quantity=Decimal("1"),
        entry_price=Decimal("10"),
        exit_price=Decimal("12"),
        gross_pnl=Decimal("2"),
        fees=Decimal("0"),
        net_pnl=Decimal("2"),
    )
    metrics = BacktestPerformanceService().calculate(
        run_id=run_id, equity_points=points, fills=[], trades=[trade]
    )
    assert metrics.profit_factor is None
    assert metrics.win_rate == Decimal("1")
