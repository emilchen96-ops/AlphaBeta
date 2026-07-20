from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest

from alphadesk_api.application.backtests import BacktestService
from alphadesk_domain.accounting import FillAccountingResult
from alphadesk_domain.entities import Fill, Order
from alphadesk_domain.enums import OrderSide

pytestmark = [pytest.mark.unit, pytest.mark.bt01]


def _accounting(
    *, quantity_delta: str, cost_delta: str, total_after: str, realized_delta: str
) -> FillAccountingResult:
    return FillAccountingResult(
        ledger_transaction_id=uuid4(),
        fill_id=uuid4(),
        cash_delta=Decimal("0"),
        quantity_delta=Decimal(quantity_delta),
        cost_basis_delta=Decimal(cost_delta),
        realized_pnl_delta=Decimal(realized_delta),
        total_cash_after=Decimal("100000"),
        total_quantity_after=Decimal(total_after),
        average_cost_after=Decimal("0"),
        realized_pnl_after=Decimal(realized_delta),
    )


def test_trade_summary_uses_m04_average_cost_realized_pnl() -> None:
    run_id, instrument_id = uuid4(), uuid4()
    opened_at = datetime(2025, 1, 2, 1, 30, tzinfo=UTC)
    closed_at = datetime(2025, 1, 3, 1, 30, tzinfo=UTC)
    position_opened_at: dict[UUID, datetime] = {}
    buy_order = cast(Order, SimpleNamespace(side=OrderSide.BUY, instrument_id=instrument_id))
    buy_fill = cast(
        Fill,
        SimpleNamespace(executed_at=opened_at, quantity=Decimal("200"), price=Decimal("10")),
    )
    assert (
        BacktestService._trade_from_accounting(
            run_id,
            buy_order,
            buy_fill,
            _accounting(
                quantity_delta="200", cost_delta="2005", total_after="200", realized_delta="0"
            ),
            Decimal("5"),
            position_opened_at,
        )
        is None
    )

    sell_order = cast(Order, SimpleNamespace(side=OrderSide.SELL, instrument_id=instrument_id))
    sell_fill = cast(
        Fill,
        SimpleNamespace(executed_at=closed_at, quantity=Decimal("100"), price=Decimal("12")),
    )
    trade = BacktestService._trade_from_accounting(
        run_id,
        sell_order,
        sell_fill,
        _accounting(
            quantity_delta="-100",
            cost_delta="-1002.5",
            total_after="100",
            realized_delta="191.5",
        ),
        Decimal("6"),
        position_opened_at,
    )

    assert trade is not None
    assert trade.entry_price == Decimal("10.025")
    assert trade.gross_pnl == Decimal("197.5")
    assert trade.fees == Decimal("6")
    assert trade.net_pnl == Decimal("191.5")
    assert position_opened_at[instrument_id] == opened_at
