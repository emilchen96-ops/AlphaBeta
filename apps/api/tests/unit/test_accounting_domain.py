from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from alphadesk_domain.accounting import (
    CashBalance,
    PositionLedgerEntry,
    assert_fill_amounts,
    calculate_fill_amounts,
)
from alphadesk_domain.enums import PositionLedgerEntryType

pytestmark = [pytest.mark.unit, pytest.mark.m04]


def test_buy_fill_amounts_capitalize_all_fees() -> None:
    result = calculate_fill_amounts(
        quantity=Decimal("1000"),
        price=Decimal("8"),
        commission=Decimal("5"),
        tax=Decimal("0"),
        other_fee=Decimal("0"),
        is_buy=True,
    )
    assert result.gross_amount == Decimal("8000")
    assert result.fee_total == Decimal("5")
    assert result.net_amount == Decimal("8005")


def test_sell_fill_amounts_deduct_all_fees() -> None:
    result = calculate_fill_amounts(
        quantity=Decimal("600"),
        price=Decimal("8.6"),
        commission=Decimal("5"),
        tax=Decimal("5.16"),
        other_fee=Decimal("0"),
        is_buy=False,
    )
    assert result.gross_amount == Decimal("5160.0")
    assert result.net_amount == Decimal("5149.84")


def test_stored_fill_amount_mismatch_is_rejected() -> None:
    calculated = calculate_fill_amounts(
        quantity=Decimal("1"),
        price=Decimal("10"),
        commission=Decimal("0"),
        tax=Decimal("0"),
        other_fee=Decimal("0"),
        is_buy=True,
    )
    with pytest.raises(ValueError, match="gross"):
        assert_fill_amounts(
            calculated=calculated,
            stored_gross=Decimal("9"),
            stored_net=Decimal("10"),
            tolerance=Decimal("0.00000001"),
        )


def test_cash_projection_must_reconcile_components() -> None:
    with pytest.raises(ValueError, match="must equal"):
        CashBalance(
            account_id=uuid4(),
            currency="cny",
            total_cash=Decimal("10"),
            available_cash=Decimal("9"),
            frozen_cash=Decimal("0"),
            as_of=datetime.now(UTC),
        )


def test_position_ledger_must_reconcile_quantity_components() -> None:
    with pytest.raises(ValueError, match="deltas do not balance"):
        PositionLedgerEntry(
            ledger_transaction_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            entry_type=PositionLedgerEntryType.BUY,
            quantity_delta=Decimal("2"),
            available_quantity_delta=Decimal("1"),
            frozen_quantity_delta=Decimal("0"),
            unsettled_quantity_delta=Decimal("0"),
            cost_basis_delta=Decimal("10"),
            realized_pnl_delta=Decimal("0"),
            total_quantity_after=Decimal("2"),
            available_quantity_after=Decimal("2"),
            frozen_quantity_after=Decimal("0"),
            unsettled_quantity_after=Decimal("0"),
            cost_basis_after=Decimal("10"),
            average_cost_after=Decimal("5"),
            realized_pnl_after=Decimal("0"),
            correlation_id=uuid4(),
            occurred_at=datetime.now(UTC),
        )
