from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from alphadesk_api.application.risk import RiskSnapshotService
from alphadesk_domain.enums import AccountStatus, AccountType, OrderSide, OrderType
from alphadesk_domain.risk import RiskLimits, RiskRequest, RiskRequestSource

pytestmark = pytest.mark.unit


class _Repo:
    def __init__(self, value=None) -> None:
        self.value = value

    async def get_by_id(self, _value):
        return self.value

    async def get(self, *_args):
        return self.value

    async def latest(self, _account_id):
        return self.value

    async def list_for_account(self, _account_id):
        return list(self.value)

    async def list_recent_timestamps(self, *_args):
        return []

    async def count_open(self, _account_id):
        return 0


@pytest.mark.asyncio
async def test_closed_zero_quantity_projection_does_not_block_next_risk_assessment() -> None:
    now = datetime(2026, 7, 24, 7, 0, tzinfo=UTC)
    account_id = uuid4()
    instrument_id = uuid4()
    account = SimpleNamespace(
        id=account_id,
        base_currency="CNY",
        account_type=AccountType.SIMULATED,
        status=AccountStatus.ACTIVE,
        metadata={},
    )
    instrument = SimpleNamespace(
        id=instrument_id,
        symbol="300088",
        exchange="SZSE",
        is_active=True,
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
    )
    cash = SimpleNamespace(
        currency="CNY",
        available_cash=Decimal("100000"),
        total_cash=Decimal("100000"),
    )
    closed_position = SimpleNamespace(
        instrument_id=instrument_id,
        total_quantity=Decimal("0"),
        available_quantity=Decimal("0"),
        market_value=None,
        last_price=None,
    )
    uow = SimpleNamespace(
        accounts=_Repo(account),
        instruments=_Repo(instrument),
        cash_balances=_Repo([cash]),
        positions=_Repo([closed_position]),
        account_snapshots=_Repo(None),
        orders=_Repo(),
    )
    request = RiskRequest(
        request_id=uuid4(),
        correlation_id=uuid4(),
        source_type=RiskRequestSource.STRATEGY_SIGNAL,
        source_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("100"),
        limit_price=Decimal("10"),
        reference_price=Decimal("10"),
        requested_at=now,
        strategy_key="price_volume_breakout_sma_exit",
    )
    limits = RiskLimits(
        max_order_notional=Decimal("1000000"),
        max_instrument_weight=Decimal("1"),
        max_total_exposure=Decimal("1"),
        max_orders_per_window=20,
        order_frequency_window_seconds=60,
        allow_market_orders=False,
        require_reference_price_for_market_order=True,
        kill_switch_enabled=False,
    )

    snapshots = await RiskSnapshotService().build(uow, request, limits)

    assert snapshots.review_reason is None
    assert snapshots.account is not None
    assert snapshots.account.positions == ()
    assert snapshots.account.total_equity == Decimal("100000")
