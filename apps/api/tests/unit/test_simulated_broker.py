from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from alphadesk_domain.broker import (
    AshareSimpleFeeModel,
    BrokerAccountSnapshot,
    BrokerDomainError,
    BrokerErrorCode,
    BrokerExecutionStatus,
    BrokerOrderRequest,
    ExecutionMarketSnapshot,
    FixedBasisPointsSlippageModel,
    NoSlippageModel,
    SimulatedBrokerAdapter,
    TradingStatus,
    execution_fingerprint,
)
from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    OrderSide,
    OrderType,
    TimeInForce,
)

NOW = datetime(2026, 7, 17, 2, 0, tzinfo=UTC)
INSTRUMENT_ID = UUID("11111111-1111-1111-1111-111111111111")
ACCOUNT_ID = UUID("22222222-2222-2222-2222-222222222222")
ORDER_ID = UUID("33333333-3333-3333-3333-333333333333")
COMMAND_ID = UUID("44444444-4444-4444-4444-444444444444")
CORRELATION_ID = UUID("55555555-5555-5555-5555-555555555555")


def request(**overrides: object) -> BrokerOrderRequest:
    values: dict[str, object] = {
        "command_id": COMMAND_ID,
        "order_id": ORDER_ID,
        "account_id": ACCOUNT_ID,
        "instrument_id": INSTRUMENT_ID,
        "symbol": "510300",
        "exchange": "SSE",
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "quantity": Decimal("100"),
        "submitted_at": NOW,
        "correlation_id": CORRELATION_ID,
    }
    values.update(overrides)
    return BrokerOrderRequest(**values)  # type: ignore[arg-type]


def market(**overrides: object) -> ExecutionMarketSnapshot:
    values: dict[str, object] = {
        "instrument_id": INSTRUMENT_ID,
        "timestamp": NOW + timedelta(seconds=1),
        "trading_status": TradingStatus.TRADING,
        "source": "test-snapshot",
        "is_stale": False,
        "open": Decimal("9.90"),
        "high": Decimal("10.20"),
        "low": Decimal("9.80"),
        "close": Decimal("10.00"),
        "last_price": Decimal("10.01"),
        "bid_price": Decimal("10.00"),
        "ask_price": Decimal("10.02"),
        "available_volume": None,
        "price_limit_up": Decimal("11.00"),
        "price_limit_down": Decimal("9.00"),
    }
    values.update(overrides)
    return ExecutionMarketSnapshot(**values)  # type: ignore[arg-type]


def account(**overrides: object) -> BrokerAccountSnapshot:
    values: dict[str, object] = {
        "account_id": ACCOUNT_ID,
        "account_type": AccountType.SIMULATED,
        "account_status": AccountStatus.ACTIVE,
        "cash_available": Decimal("1000000"),
        "position_quantity": Decimal("1000"),
        "sellable_quantity": Decimal("1000"),
        "snapshot_at": NOW,
    }
    values.update(overrides)
    return BrokerAccountSnapshot(**values)  # type: ignore[arg-type]


def test_request_rejects_float_and_invalid_order_shapes() -> None:
    with pytest.raises(TypeError, match="quantity must be Decimal"):
        request(quantity=100.0)
    with pytest.raises(BrokerDomainError, match="LIMIT order requires limit_price"):
        request(order_type=OrderType.LIMIT)
    with pytest.raises(BrokerDomainError, match="MARKET order must not carry limit_price"):
        request(limit_price=Decimal("10"))
    with pytest.raises(BrokerDomainError, match="limit_price must be positive"):
        request(order_type=OrderType.LIMIT, limit_price=Decimal("0"))


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_request_rejects_non_finite_decimal(value: Decimal) -> None:
    with pytest.raises(ValueError, match="quantity must be finite"):
        request(quantity=value)


def test_request_normalizes_aware_time_and_rejects_naive_time() -> None:
    china_time = datetime(2026, 7, 17, 10, tzinfo=timezone(timedelta(hours=8)))
    normalized = request(
        submitted_at=china_time,
        expires_at=china_time + timedelta(minutes=5),
    )
    assert normalized.submitted_at == NOW
    assert normalized.submitted_at.tzinfo is UTC
    with pytest.raises(ValueError, match="submitted_at must be timezone-aware"):
        request(submitted_at=datetime(2026, 7, 17, 2))
    with pytest.raises(BrokerDomainError, match="expires_at must be later"):
        request(expires_at=NOW)


def test_market_snapshot_validates_ohlc_volume_and_immutability() -> None:
    snapshot = market()
    with pytest.raises(FrozenInstanceError):
        snapshot.close = Decimal("11")  # type: ignore[misc]
    with pytest.raises(BrokerDomainError, match="invalid OHLC"):
        market(high=Decimal("9.70"))
    with pytest.raises(BrokerDomainError, match="OHLC values must be supplied together"):
        market(open=None)
    with pytest.raises(BrokerDomainError, match="available_volume must be non-negative"):
        market(available_volume=Decimal("-1"))


def test_account_snapshot_validates_balances_and_immutability() -> None:
    snapshot = account()
    with pytest.raises(FrozenInstanceError):
        snapshot.cash_available = Decimal("0")  # type: ignore[misc]
    with pytest.raises(BrokerDomainError, match="sellable_quantity must not exceed"):
        account(position_quantity=Decimal("10"), sellable_quantity=Decimal("11"))
    with pytest.raises(TypeError, match="cash_available must be Decimal"):
        account(cash_available=1000.0)


def test_fee_model_buy_sell_minimum_and_transfer_fee() -> None:
    model = AshareSimpleFeeModel()
    buy = model.calculate(side=OrderSide.BUY, quantity=Decimal("1000"), price=Decimal("10"))
    sell = model.calculate(side=OrderSide.SELL, quantity=Decimal("1000"), price=Decimal("10"))
    assert buy.commission == Decimal("5.00")
    assert buy.stamp_duty == Decimal("0.00")
    assert buy.transfer_fee == Decimal("0.10")
    assert sell.commission == Decimal("5.00")
    assert sell.stamp_duty == Decimal("5.00")
    assert sell.transfer_fee == Decimal("0.10")
    assert sell.total_fee == Decimal("10.10")


def test_fee_model_uses_explicit_half_up_rounding_and_is_deterministic() -> None:
    model = AshareSimpleFeeModel(
        commission_rate=Decimal("0.0005"),
        minimum_commission=Decimal("0"),
        stamp_duty_rate=Decimal("0"),
        transfer_fee_rate=Decimal("0"),
    )
    first = model.calculate(side=OrderSide.BUY, quantity=Decimal("101"), price=Decimal("10"))
    second = model.calculate(side=OrderSide.BUY, quantity=Decimal("101"), price=Decimal("10"))
    assert first.commission == Decimal("0.51")
    assert first == second


@pytest.mark.parametrize(
    "overrides",
    [
        {"commission_rate": Decimal("-0.1")},
        {"minimum_commission": Decimal("-1")},
        {"stamp_duty_rate": 0.1},
    ],
)
def test_fee_model_rejects_invalid_configuration(overrides: dict[str, object]) -> None:
    with pytest.raises(BrokerDomainError) as error:
        AshareSimpleFeeModel(**overrides)  # type: ignore[arg-type]
    assert error.value.code is BrokerErrorCode.INVALID_FEE_CONFIGURATION


def test_slippage_models_apply_direction_cap_and_price_limits() -> None:
    no_slippage = NoSlippageModel()
    assert no_slippage.apply(
        side=OrderSide.BUY,
        reference_price=Decimal("10"),
        price_limit_up=None,
        price_limit_down=None,
    ) == Decimal("10")
    model = FixedBasisPointsSlippageModel(
        basis_points=Decimal("100"), maximum_slippage=Decimal("0.05")
    )
    buy = model.apply(
        side=OrderSide.BUY,
        reference_price=Decimal("10"),
        price_limit_up=Decimal("10.03"),
        price_limit_down=Decimal("9"),
    )
    sell = model.apply(
        side=OrderSide.SELL,
        reference_price=Decimal("10"),
        price_limit_up=Decimal("11"),
        price_limit_down=Decimal("9.97"),
    )
    assert buy == Decimal("10.03")
    assert sell == Decimal("9.97")
    assert buy == model.apply(
        side=OrderSide.BUY,
        reference_price=Decimal("10"),
        price_limit_up=Decimal("10.03"),
        price_limit_down=Decimal("9"),
    )


def test_slippage_rejects_invalid_configuration() -> None:
    with pytest.raises(BrokerDomainError) as error:
        FixedBasisPointsSlippageModel(basis_points=Decimal("-1"))
    assert error.value.code is BrokerErrorCode.INVALID_SLIPPAGE_CONFIGURATION
    with pytest.raises(BrokerDomainError):
        FixedBasisPointsSlippageModel(basis_points=Decimal("1"), maximum_slippage=1.0)


def test_market_buy_uses_ask_and_sell_uses_bid() -> None:
    broker = SimulatedBrokerAdapter()
    buy = broker.submit(request(), market(), account())
    sell = broker.submit(request(side=OrderSide.SELL), market(), account())
    assert buy.status is BrokerExecutionStatus.FILLED
    assert buy.average_fill_price == Decimal("10.02")
    assert "ask_price" in buy.message
    assert sell.average_fill_price == Decimal("10.00")
    assert "bid_price" in sell.message


def test_market_price_falls_back_to_last_then_close() -> None:
    broker = SimulatedBrokerAdapter()
    last = broker.submit(request(), market(ask_price=None), account())
    close = broker.submit(request(), market(ask_price=None, last_price=None), account())
    missing = broker.submit(
        request(),
        market(ask_price=None, last_price=None, close=None, open=None, high=None, low=None),
        account(),
    )
    assert last.average_fill_price == Decimal("10.01")
    assert close.average_fill_price == Decimal("10.00")
    assert missing.status is BrokerExecutionStatus.REJECTED
    assert missing.rejection_code == BrokerErrorCode.MARKET_PRICE_UNAVAILABLE.value


@pytest.mark.parametrize(
    ("side", "limit_price", "ask", "bid", "expected"),
    [
        (OrderSide.BUY, Decimal("10.02"), Decimal("10.02"), Decimal("10"), True),
        (OrderSide.BUY, Decimal("10.01"), Decimal("10.02"), Decimal("10"), False),
        (OrderSide.SELL, Decimal("10.00"), Decimal("10.02"), Decimal("10"), True),
        (OrderSide.SELL, Decimal("10.01"), Decimal("10.02"), Decimal("10"), False),
    ],
)
def test_limit_order_marketability(
    side: OrderSide,
    limit_price: Decimal,
    ask: Decimal,
    bid: Decimal,
    expected: bool,
) -> None:
    result = SimulatedBrokerAdapter().submit(
        request(side=side, order_type=OrderType.LIMIT, limit_price=limit_price),
        market(ask_price=ask, bid_price=bid),
        account(),
    )
    assert (result.status is BrokerExecutionStatus.FILLED) is expected
    if not expected:
        assert result.status is BrokerExecutionStatus.NO_FILL
        assert result.rejection_code == BrokerErrorCode.LIMIT_NOT_MARKETABLE.value


@pytest.mark.parametrize(
    ("market_overrides", "account_overrides", "request_overrides", "code", "status"),
    [
        (
            {"trading_status": TradingStatus.SUSPENDED},
            {},
            {},
            BrokerErrorCode.MARKET_NOT_TRADING,
            BrokerExecutionStatus.REJECTED,
        ),
        (
            {"is_stale": True},
            {},
            {},
            BrokerErrorCode.MARKET_DATA_STALE,
            BrokerExecutionStatus.REJECTED,
        ),
        (
            {},
            {"account_status": AccountStatus.SUSPENDED},
            {},
            BrokerErrorCode.ACCOUNT_NOT_ACTIVE,
            BrokerExecutionStatus.REJECTED,
        ),
        (
            {},
            {"account_type": AccountType.CASH},
            {},
            BrokerErrorCode.ACCOUNT_NOT_SUPPORTED,
            BrokerExecutionStatus.REJECTED,
        ),
        (
            {"instrument_id": uuid4()},
            {},
            {},
            BrokerErrorCode.INSTRUMENT_MISMATCH,
            BrokerExecutionStatus.REJECTED,
        ),
        (
            {},
            {},
            {"expires_at": NOW + timedelta(milliseconds=500)},
            BrokerErrorCode.ORDER_EXPIRED,
            BrokerExecutionStatus.EXPIRED,
        ),
    ],
)
def test_execution_rejects_constraints_in_stable_order(
    market_overrides: dict[str, object],
    account_overrides: dict[str, object],
    request_overrides: dict[str, object],
    code: BrokerErrorCode,
    status: BrokerExecutionStatus,
) -> None:
    result = SimulatedBrokerAdapter().submit(
        request(**request_overrides), market(**market_overrides), account(**account_overrides)
    )
    assert result.status is status
    assert result.rejection_code == code.value
    assert result.fills == ()


def test_buy_cash_and_sellable_position_are_rechecked() -> None:
    broker = SimulatedBrokerAdapter()
    buy = broker.submit(request(), market(), account(cash_available=Decimal("100")))
    sell = broker.submit(
        request(side=OrderSide.SELL),
        market(),
        account(position_quantity=Decimal("50"), sellable_quantity=Decimal("50")),
    )
    assert buy.rejection_code == BrokerErrorCode.INSUFFICIENT_CASH.value
    assert sell.rejection_code == BrokerErrorCode.INSUFFICIENT_POSITION.value
    assert buy.fills == sell.fills == ()


def test_sell_request_cannot_exceed_sellable_quantity_even_if_volume_is_partial() -> None:
    result = SimulatedBrokerAdapter().submit(
        request(side=OrderSide.SELL),
        market(available_volume=Decimal("40")),
        account(position_quantity=Decimal("100"), sellable_quantity=Decimal("50")),
    )
    assert result.status is BrokerExecutionStatus.REJECTED
    assert result.rejection_code == BrokerErrorCode.INSUFFICIENT_POSITION.value
    assert result.fills == ()


def test_sell_result_is_rejected_when_fees_would_consume_all_proceeds() -> None:
    result = SimulatedBrokerAdapter().submit(
        request(side=OrderSide.SELL, quantity=Decimal("0.1")),
        market(),
        account(),
    )
    assert result.status is BrokerExecutionStatus.REJECTED
    assert result.rejection_code == BrokerErrorCode.EXECUTION_FAILED.value
    assert result.fills == ()


def test_full_partial_zero_volume_and_fok_results() -> None:
    broker = SimulatedBrokerAdapter()
    full = broker.submit(request(), market(available_volume=None), account())
    partial = broker.submit(request(), market(available_volume=Decimal("40")), account())
    empty = broker.submit(request(), market(available_volume=Decimal("0")), account())
    fok = broker.submit(
        request(time_in_force=TimeInForce.FOK),
        market(available_volume=Decimal("40")),
        account(),
    )
    assert full.status is BrokerExecutionStatus.FILLED
    assert full.filled_quantity == Decimal("100")
    assert full.remaining_quantity == Decimal("0")
    assert partial.status is BrokerExecutionStatus.PARTIALLY_FILLED
    assert partial.filled_quantity == Decimal("40")
    assert partial.remaining_quantity == Decimal("60")
    assert partial.fills[0].quantity == Decimal("40")
    assert empty.status is fok.status is BrokerExecutionStatus.NO_FILL
    assert empty.rejection_code == fok.rejection_code == BrokerErrorCode.NO_AVAILABLE_VOLUME.value


def test_fees_fill_balances_and_net_cash_direction() -> None:
    broker = SimulatedBrokerAdapter()
    buy = broker.submit(request(), market(), account()).fills[0]
    sell = broker.submit(request(side=OrderSide.SELL), market(), account()).fills[0]
    assert buy.gross_amount == buy.quantity * buy.price
    assert buy.reference_price == Decimal("10.02")
    assert buy.reference_price_source == "ask_price"
    assert buy.total_fee == buy.commission + buy.stamp_duty + buy.transfer_fee + buy.other_fee
    assert buy.net_cash_effect == -(buy.gross_amount + buy.total_fee)
    assert buy.net_cash_effect < 0
    assert sell.net_cash_effect == sell.gross_amount - sell.total_fee
    assert sell.net_cash_effect > 0
    assert buy.sequence_number == sell.sequence_number == 1


def test_price_limits_reject_invalid_execution_prices() -> None:
    broker = SimulatedBrokerAdapter()
    buy = broker.submit(
        request(), market(ask_price=Decimal("11.01"), price_limit_up=Decimal("11")), account()
    )
    sell = broker.submit(
        request(side=OrderSide.SELL),
        market(bid_price=Decimal("8.99"), price_limit_down=Decimal("9")),
        account(),
    )
    assert buy.rejection_code == sell.rejection_code == BrokerErrorCode.PRICE_LIMIT_VIOLATION.value


def test_fingerprint_and_result_are_stable_and_sensitive_to_inputs() -> None:
    broker = SimulatedBrokerAdapter()
    order_request = request()
    snapshot = market()
    first = execution_fingerprint(
        broker_key=broker.metadata.broker_key,
        request=order_request,
        market=snapshot,
        fee_model_version=broker.fee_model.version,
        slippage_model_version=broker.slippage_model.version,
    )
    second = execution_fingerprint(
        broker_key=broker.metadata.broker_key,
        request=order_request,
        market=snapshot,
        fee_model_version=broker.fee_model.version,
        slippage_model_version=broker.slippage_model.version,
    )
    changed = execution_fingerprint(
        broker_key=broker.metadata.broker_key,
        request=order_request,
        market=market(ask_price=Decimal("10.03")),
        fee_model_version=broker.fee_model.version,
        slippage_model_version=broker.slippage_model.version,
    )
    assert len(first) == 64
    assert first == second
    assert first != changed
    assert broker.submit(order_request, snapshot, account()) == broker.submit(
        order_request, snapshot, account()
    )


def test_pure_domain_module_does_not_import_framework_or_persistence_dependencies() -> None:
    import alphadesk_domain.broker as broker_module

    source = broker_module.__loader__.get_source(broker_module.__name__)  # type: ignore[union-attr]
    assert source is not None
    for forbidden in (
        "fastapi",
        "sqlalchemy",
        "redis",
        "asyncsession",
        "miniqmt",
        "xtquant",
        "alphadesk_api",
        "repository",
        "unitofwork",
        "fillaccountingservice",
    ):
        assert forbidden not in source.lower()
