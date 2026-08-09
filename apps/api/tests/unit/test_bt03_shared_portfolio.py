from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from alphadesk_api.application.backtest_batches import (
    _empty_contribution,
    _portfolio_derived_summary,
)
from alphadesk_api.application.backtests import (
    BacktestService,
    _backtest_instrument_limit,
    _shared_intraday_work_key,
    _SharedIntradayWork,
)
from alphadesk_api.core.config import Settings
from alphadesk_domain.backtest import (
    BacktestConfiguration,
    BacktestError,
    BacktestExecutionPriceMode,
    backtest_configuration_from_dict,
    backtest_configuration_to_dict,
)
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import (
    MarketTimeframe,
    OrderSide,
    SignalType,
)
from alphadesk_domain.strategy import SignalDraft, StrategyBar

NOW = datetime(2026, 7, 30, 6, 1, tzinfo=UTC)


def test_shared_portfolio_uses_batch_instrument_limit() -> None:
    settings = Settings(
        environment="test",
        backtest_max_instruments=20,
        backtest_batch_max_instruments=6_000,
    )

    assert _backtest_instrument_limit(settings, shared_portfolio=False) == 20
    assert _backtest_instrument_limit(settings, shared_portfolio=True) == 6_000


def test_empty_shared_portfolio_contribution_is_report_safe() -> None:
    """Closed or never-held stocks must still be serializable in the report."""

    instrument_id = UUID("00000000-0000-4000-8000-000000000031")

    contribution = _empty_contribution(
        instrument_id,
        {instrument_id: "测试股票 (600031.SSE)"},
    )

    assert contribution["current_market_value"] == Decimal("0")
    assert contribution["unrealized_pnl"] == Decimal("0")
    assert contribution["total_contribution"] == Decimal("0")
    assert contribution["realized_pnl"] + contribution["unrealized_pnl"] == Decimal("0")


def test_shared_portfolio_average_exposure_uses_equity_ratio() -> None:
    """Stored exposure is an amount; report exposure must be a percentage ratio."""

    points = [
        SimpleNamespace(
            gross_exposure=Decimal("20000"),
            total_equity=Decimal("100000"),
            positions_count=1,
            cumulative_return=Decimal("0"),
            drawdown=Decimal("0"),
        ),
        SimpleNamespace(
            gross_exposure=Decimal("60000"),
            total_equity=Decimal("120000"),
            positions_count=3,
            cumulative_return=Decimal("0.2"),
            drawdown=Decimal("-0.1"),
        ),
    ]

    summary = _portfolio_derived_summary(None, points, [], {"curve": []})

    assert summary["average_exposure"] == Decimal("0.35")
    assert summary["average_idle_cash_ratio"] == Decimal("0.65")


class _StaticRepository:
    def __init__(self, *, item: object | None = None, items: list[object] | None = None) -> None:
        self.item = item
        self.items = [] if items is None else items

    async def get_by_id(self, *_args: object) -> object | None:
        return self.item

    async def get_for_account_instrument(self, *_args: object) -> object | None:
        return self.item

    async def get(self, *_args: object) -> object | None:
        return self.item

    async def latest(self, *_args: object) -> object | None:
        return self.item

    async def list_for_account(self, *_args: object) -> list[object]:
        return self.items


class _SizingUnitOfWork:
    def __init__(
        self,
        *,
        available_cash: Decimal,
        positions: list[object],
        instrument_id: UUID,
        total_equity: Decimal = Decimal("100000"),
    ) -> None:
        existing_position = next(
            (
                item
                for item in positions
                if item.instrument_id == instrument_id and item.total_quantity > 0
            ),
            None,
        )
        self.accounts = _StaticRepository(item=SimpleNamespace(base_currency="CNY"))
        self.positions = _StaticRepository(item=existing_position, items=positions)
        self.cash_balances = _StaticRepository(item=SimpleNamespace(available_cash=available_cash))
        self.account_snapshots = _StaticRepository(item=SimpleNamespace(total_equity=total_equity))

    async def __aenter__(self) -> "_SizingUnitOfWork":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _instrument(instrument_id: UUID, symbol: str) -> Instrument:
    return Instrument(
        id=instrument_id,
        symbol=symbol,
        exchange="SSE",
        market="CN_A",
        name=symbol,
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
    )


def _bar(instrument_id: UUID, symbol: str, volume: str) -> StrategyBar:
    return StrategyBar(
        instrument_id=instrument_id,
        symbol=symbol,
        exchange="SSE",
        timeframe=MarketTimeframe.MINUTE_1,
        timestamp=NOW,
        open=Decimal("10"),
        high=Decimal("10.2"),
        low=Decimal("9.9"),
        close=Decimal("10.1"),
        volume=Decimal(volume),
    )


def _work(
    instrument_id: UUID,
    symbol: str,
    *,
    side: OrderSide,
    confidence: str,
    volume: str,
) -> _SharedIntradayWork:
    bar = _bar(instrument_id, symbol, volume)
    return _SharedIntradayWork(
        instrument_id=instrument_id,
        draft=SignalDraft(
            strategy_key="shared_test",
            strategy_version="1.0.0",
            instrument_id=instrument_id,
            signal_type=(SignalType.EXIT if side is OrderSide.SELL else SignalType.ENTRY),
            side=side,
            generated_at=NOW,
            bar_timestamp=NOW,
            confidence=Decimal(confidence),
            reason="deterministic shared-account test",
        ),
        partial_bar=bar,
        source_minute=bar,
        execution_minute=bar,
        confirmed_at=NOW,
        price_source="test",
        completed_session_count=20,
        previous_close=Decimal("10"),
    )


def test_same_timestamp_exits_release_capacity_before_ranked_entries() -> None:
    exit_id = UUID("00000000-0000-4000-8000-000000000001")
    strong_id = UUID("00000000-0000-4000-8000-000000000002")
    weak_id = UUID("00000000-0000-4000-8000-000000000003")
    instruments = {
        exit_id: _instrument(exit_id, "600001"),
        strong_id: _instrument(strong_id, "600002"),
        weak_id: _instrument(weak_id, "600003"),
    }
    history = {
        instrument_id: [_bar(instrument_id, item.symbol, "100")]
        for instrument_id, item in instruments.items()
    }
    work = [
        _work(weak_id, "600003", side=OrderSide.BUY, confidence="0.4", volume="300"),
        _work(strong_id, "600002", side=OrderSide.BUY, confidence="0.8", volume="100"),
        _work(exit_id, "600001", side=OrderSide.SELL, confidence="0.1", volume="100"),
    ]

    ordered = sorted(
        work,
        key=lambda item: _shared_intraday_work_key(
            item,
            completed_daily_bars=history,
            instruments=instruments,
        ),
    )

    assert [item.draft.side for item in ordered] == [
        OrderSide.SELL,
        OrderSide.BUY,
        OrderSide.BUY,
    ]
    assert [item.instrument_id for item in ordered] == [exit_id, strong_id, weak_id]


def test_shared_portfolio_configuration_round_trips_frozen_rules() -> None:
    instrument_ids = (
        UUID("00000000-0000-4000-8000-000000000011"),
        UUID("00000000-0000-4000-8000-000000000012"),
    )
    configuration = BacktestConfiguration(
        strategy_key="shared_test",
        strategy_version="1.0.0",
        parameters={},
        instrument_ids=instrument_ids,
        timeframe=MarketTimeframe.DAY_1,
        start_at=datetime(2025, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 1, tzinfo=UTC),
        initial_cash=Decimal("100000"),
        execution_price_mode=BacktestExecutionPriceMode.INTRADAY_NEXT_MINUTE,
        position_size_ratio=Decimal("0.2"),
        shared_portfolio=True,
        maximum_holdings=5,
        maximum_total_exposure=Decimal("1"),
        maximum_instrument_weight=Decimal("0.2"),
        allow_position_addition=False,
        benchmark_symbol="000300.SH",
    )

    restored = backtest_configuration_from_dict(backtest_configuration_to_dict(configuration))

    assert restored.shared_portfolio is True
    assert restored.instrument_ids == instrument_ids
    assert restored.position_size_ratio == Decimal("0.2")
    assert restored.maximum_holdings == 5
    assert restored.maximum_total_exposure == Decimal("1")
    assert restored.maximum_instrument_weight == Decimal("0.2")
    assert restored.allow_position_addition is False
    assert restored.benchmark_symbol == "000300.SH"


def test_shared_portfolio_rejects_target_weight_above_single_stock_cap() -> None:
    with pytest.raises(BacktestError, match="position_size_ratio exceeds"):
        BacktestConfiguration(
            strategy_key="shared_test",
            strategy_version="1.0.0",
            parameters={},
            instrument_ids=(UUID("00000000-0000-4000-8000-000000000021"),),
            timeframe=MarketTimeframe.DAY_1,
            start_at=datetime(2025, 1, 1, tzinfo=UTC),
            end_at=datetime(2026, 1, 1, tzinfo=UTC),
            initial_cash=Decimal("100000"),
            execution_price_mode=BacktestExecutionPriceMode.INTRADAY_NEXT_MINUTE,
            position_size_ratio=Decimal("0.3"),
            shared_portfolio=True,
            maximum_instrument_weight=Decimal("0.2"),
        )


@pytest.mark.asyncio
async def test_a_to_g_rotation_uses_one_account_and_releases_capacity_after_exit() -> None:
    """Exercise the task-spec A-G rotation against the production sizing rule."""

    instrument_ids = tuple(UUID(int=index) for index in range(101, 108))
    configuration = BacktestConfiguration(
        strategy_key="shared_test",
        strategy_version="1.0.0",
        parameters={},
        instrument_ids=instrument_ids,
        timeframe=MarketTimeframe.DAY_1,
        start_at=datetime(2025, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 1, 1, tzinfo=UTC),
        initial_cash=Decimal("100000"),
        execution_price_mode=BacktestExecutionPriceMode.INTRADAY_NEXT_MINUTE,
        position_size_ratio=Decimal("0.2"),
        shared_portfolio=True,
        maximum_holdings=5,
        maximum_total_exposure=Decimal("1"),
        maximum_instrument_weight=Decimal("0.2"),
        allow_position_addition=False,
    )
    run = SimpleNamespace(
        account_id=UUID("00000000-0000-4000-8000-000000000099"),
        configuration=configuration,
    )
    service = object.__new__(BacktestService)
    active_positions: list[object] = []
    available_cash = Decimal("100000")

    async def sized_quantity(instrument_id: UUID) -> Decimal:
        service._uow_factory = lambda: _SizingUnitOfWork(  # type: ignore[method-assign]
            available_cash=available_cash,
            positions=active_positions,
            instrument_id=instrument_id,
        )
        signal = SimpleNamespace(side=OrderSide.BUY, instrument_id=instrument_id)
        return await service._position_sized_quantity(
            run,  # type: ignore[arg-type]
            signal,  # type: ignore[arg-type]
            opening_price=Decimal("10"),
            lot_size=Decimal("100"),
        )

    # A-E each consume one 20% target slot in the same CNY 100,000 account.
    for instrument_id in instrument_ids[:5]:
        quantity = await sized_quantity(instrument_id)
        assert quantity == Decimal("1900")
        fees = configuration.fee_configuration.calculate(
            side=OrderSide.BUY,
            quantity=quantity,
            price=Decimal("10"),
        ).total_fee
        available_cash -= (quantity * Decimal("10")) + fees
        active_positions.append(
            SimpleNamespace(
                instrument_id=instrument_id,
                total_quantity=quantity,
                available_quantity=quantity,
                average_cost=Decimal("10"),
                market_value=quantity * Decimal("10"),
            )
        )

    assert len(active_positions) == 5
    assert sum(item.market_value for item in active_positions) == Decimal("95000")
    assert available_cash > 0

    # No same-stock pyramiding and F cannot enter while all five slots are occupied.
    assert await sized_quantity(instrument_ids[0]) == 0
    assert await sized_quantity(instrument_ids[5]) == 0

    # A exits: cash and one holding slot are released before G competes for entry.
    exited = active_positions.pop(0)
    sell_fees = configuration.fee_configuration.calculate(
        side=OrderSide.SELL,
        quantity=exited.total_quantity,
        price=Decimal("10"),
    ).total_fee
    available_cash += (exited.total_quantity * Decimal("10")) - sell_fees

    assert len(active_positions) == 4
    assert await sized_quantity(instrument_ids[6]) == Decimal("1900")
