from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.infrastructure.models import (
    DomainEventModel,
    FillModel,
    InstrumentModel,
    OrderCommandModel,
    OrderModel,
    OutboxMessageModel,
    PositionModel,
    StrategyModel,
    StrategyVersionModel,
    TradingAccountModel,
    WatchlistItemModel,
    WatchlistModel,
)


def instrument_model(*, symbol: str | None = None, exchange: str = "TEST") -> InstrumentModel:
    return InstrumentModel(
        id=uuid4(),
        symbol=symbol or f"T{uuid4().hex[:8]}",
        exchange=exchange,
        market="TEST",
        name="Constraint instrument",
        asset_type="EQUITY",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="UTC",
        is_active=True,
        metadata_json={},
    )


def account_model() -> TradingAccountModel:
    return TradingAccountModel(
        id=uuid4(),
        account_code=f"SIM-{uuid4().hex[:8]}",
        name="Constraint account",
        account_type="SIMULATED",
        status="ACTIVE",
        broker_type="SIMULATED",
        base_currency="CNY",
        metadata_json={},
    )


def strategy_model() -> StrategyModel:
    return StrategyModel(
        id=uuid4(),
        strategy_code=f"S-{uuid4().hex[:8]}",
        name="Constraint strategy",
        status="DRAFT",
        metadata_json={},
    )


def order_model(
    account_id: UUID,
    instrument_id: UUID,
    *,
    idempotency_key: str | None = None,
    order_type: str = "MARKET",
    limit_price: Decimal | None = None,
) -> OrderModel:
    return OrderModel(
        id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        side="BUY",
        order_type=order_type,
        time_in_force="DAY",
        requested_quantity=Decimal("100"),
        filled_quantity=Decimal("0"),
        limit_price=limit_price,
        status="CREATED",
        idempotency_key=idempotency_key or f"order-{uuid4()}",
        broker_type="SIMULATED",
        correlation_id=uuid4(),
    )


def event_model(*, event_id: UUID | None = None) -> DomainEventModel:
    now = datetime.now(UTC)
    return DomainEventModel(
        event_id=event_id or uuid4(),
        event_type="test.event",
        entity_type="Test",
        entity_id=uuid4(),
        source="M02_TEST",
        event_time=now,
        received_time=now,
        correlation_id=uuid4(),
        schema_version=1,
        payload={},
        metadata_json={},
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_instrument_and_position_unique_constraints(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = instrument_model(symbol="DUPLICATE", exchange="TEST")
        session.add(first)
        await session.flush()
        session.add(instrument_model(symbol="DUPLICATE", exchange="TEST"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async with session_factory() as session:
        instrument = instrument_model()
        account = account_model()
        session.add_all([instrument, account])
        await session.flush()
        values = {
            "account_id": account.id,
            "instrument_id": instrument.id,
            "total_quantity": Decimal("100"),
            "available_quantity": Decimal("80"),
            "frozen_quantity": Decimal("20"),
            "average_cost": Decimal("10.12345678"),
            "market_value": Decimal("1000.00000000"),
            "realized_pnl": Decimal("0"),
            "unrealized_pnl": Decimal("0"),
            "as_of": datetime.now(UTC),
            "row_version": 1,
        }
        session.add(PositionModel(id=uuid4(), **values))
        await session.flush()
        session.add(PositionModel(id=uuid4(), **values))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_position_quantity_check_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        instrument = instrument_model()
        account = account_model()
        session.add_all([instrument, account])
        await session.flush()
        session.add(
            PositionModel(
                id=uuid4(),
                account_id=account.id,
                instrument_id=instrument.id,
                total_quantity=Decimal("100"),
                available_quantity=Decimal("90"),
                frozen_quantity=Decimal("20"),
                average_cost=Decimal("10"),
                market_value=Decimal("1000"),
                realized_pnl=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                as_of=datetime.now(UTC),
                row_version=1,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_watchlist_item_unique_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        instrument = instrument_model()
        watchlist = WatchlistModel(id=uuid4(), name="Primary")
        session.add_all([instrument, watchlist])
        await session.flush()
        first = WatchlistItemModel(
            id=uuid4(), watchlist_id=watchlist.id, instrument_id=instrument.id, sort_order=0
        )
        second = WatchlistItemModel(
            id=uuid4(), watchlist_id=watchlist.id, instrument_id=instrument.id, sort_order=1
        )
        session.add(first)
        await session.flush()
        session.add(second)
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_strategy_version_unique_and_single_active_constraints(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        strategy = strategy_model()
        session.add(strategy)
        await session.flush()
        first = StrategyVersionModel(
            id=uuid4(),
            strategy_id=strategy.id,
            version_number=1,
            source_hash="hash-1",
            code_reference="git:one",
            parameter_schema={},
            default_parameters={},
            is_active=False,
        )
        session.add(first)
        await session.flush()
        session.add(
            StrategyVersionModel(
                id=uuid4(),
                strategy_id=strategy.id,
                version_number=1,
                source_hash="hash-2",
                code_reference="git:two",
                parameter_schema={},
                default_parameters={},
                is_active=False,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()

    async with session_factory() as session:
        strategy = strategy_model()
        session.add(strategy)
        await session.flush()
        session.add(
            StrategyVersionModel(
                id=uuid4(),
                strategy_id=strategy.id,
                version_number=1,
                source_hash="hash-1",
                code_reference="git:one",
                parameter_schema={},
                default_parameters={},
                is_active=True,
            )
        )
        await session.flush()
        session.add(
            StrategyVersionModel(
                id=uuid4(),
                strategy_id=strategy.id,
                version_number=2,
                source_hash="hash-2",
                code_reference="git:two",
                parameter_schema={},
                default_parameters={},
                is_active=True,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_idempotency_and_limit_price_constraints(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        instrument = instrument_model()
        account = account_model()
        session.add_all([instrument, account])
        await session.flush()
        key = f"same-{uuid4()}"
        session.add(order_model(account.id, instrument.id, idempotency_key=key))
        await session.flush()
        session.add(order_model(account.id, instrument.id, idempotency_key=key))
        with pytest.raises(IntegrityError):
            await session.flush()

    async with session_factory() as session:
        instrument = instrument_model()
        account = account_model()
        session.add_all([instrument, account])
        await session.flush()
        session.add(order_model(account.id, instrument.id, order_type="LIMIT"))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_command_and_fill_idempotency_constraints(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        instrument = instrument_model()
        account = account_model()
        order = order_model(account.id, instrument.id)
        session.add_all([instrument, account])
        await session.flush()
        session.add(order)
        await session.flush()
        command_id = uuid4()
        command_values = {
            "command_id": command_id,
            "order_id": order.id,
            "command_type": "SUBMIT",
            "status": "CREATED",
            "sequence_number": 0,
            "payload": {},
            "payload_hash": "hash",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        }
        session.add(OrderCommandModel(id=uuid4(), **command_values))
        await session.flush()
        session.add(OrderCommandModel(id=uuid4(), **command_values))
        with pytest.raises(IntegrityError):
            await session.flush()

    async with session_factory() as session:
        instrument = instrument_model()
        account = account_model()
        order = order_model(account.id, instrument.id)
        session.add_all([instrument, account])
        await session.flush()
        session.add(order)
        await session.flush()
        fill_values = {
            "order_id": order.id,
            "account_id": account.id,
            "instrument_id": instrument.id,
            "broker_type": "SIMULATED",
            "broker_fill_id": "duplicate-fill",
            "quantity": Decimal("100"),
            "price": Decimal("10"),
            "gross_amount": Decimal("1000"),
            "commission": Decimal("1"),
            "tax": Decimal("0"),
            "other_fee": Decimal("0"),
            "net_amount": Decimal("1001"),
            "executed_at": datetime.now(UTC),
            "received_at": datetime.now(UTC),
            "correlation_id": uuid4(),
            "metadata_json": {},
        }
        session.add(FillModel(id=uuid4(), **fill_values))
        await session.flush()
        session.add(FillModel(id=uuid4(), **fill_values))
        with pytest.raises(IntegrityError):
            await session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_event_and_outbox_idempotency_constraints(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        event_id = uuid4()
        session.add(event_model(event_id=event_id))
        await session.flush()
        session.add(event_model(event_id=event_id))
        with pytest.raises(IntegrityError):
            await session.flush()

    async with session_factory() as session:
        event = event_model()
        session.add(event)
        await session.flush()
        values = {
            "event_id": event.event_id,
            "aggregate_type": "Test",
            "aggregate_id": uuid4(),
            "topic": "test.events",
            "payload": {},
            "headers": {},
            "status": "PENDING",
            "attempts": 0,
            "available_at": datetime.now(UTC),
        }
        session.add(OutboxMessageModel(id=uuid4(), **values))
        await session.flush()
        session.add(OutboxMessageModel(id=uuid4(), **values))
        with pytest.raises(IntegrityError):
            await session.flush()
