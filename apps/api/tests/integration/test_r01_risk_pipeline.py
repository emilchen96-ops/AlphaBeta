import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alphadesk_api.application.accounting import SimulatedAccountService
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.orders import CreateOrderRequest
from alphadesk_api.application.risk import ConfiguredRiskLimitsProvider, RiskGatedOrderService
from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import RiskDecisionType, SettlementPolicy
from tests.helpers import require_test_database_url

pytestmark = [pytest.mark.integration, pytest.mark.r01]


def _factory(session_factory: async_sessionmaker[AsyncSession]) -> UnitOfWorkFactory:
    return lambda: SqlAlchemyUnitOfWork(session_factory)


async def _seed(session_factory: async_sessionmaker[AsyncSession]):
    factory = _factory(session_factory)
    async with factory() as uow:
        instrument = Instrument(
            symbol=uuid4().hex[:8].upper(),
            exchange="TEST",
            market="TEST",
            name="R01 instrument",
            asset_type="EQUITY",
            currency="CNY",
            lot_size=Decimal("100"),
            price_tick=Decimal("0.01"),
            timezone="Asia/Shanghai",
        )
        await uow.instruments.add(instrument)
        await uow.commit()
    account = await SimulatedAccountService(factory).create(
        account_code=f"R01-{uuid4().hex[:10]}",
        name="R01 account",
        base_currency="CNY",
        initial_cash=Decimal("100000"),
        settlement_policy=SettlementPolicy.IMMEDIATE,
        idempotency_key=f"account-{uuid4()}",
        correlation_id=uuid4(),
    )
    return account, instrument


def _request(account, instrument, key: str) -> CreateOrderRequest:
    return CreateOrderRequest(
        account_id=account.id,
        instrument_id=instrument.id,
        side="BUY",
        order_type="LIMIT",
        time_in_force="DAY",
        quantity=Decimal("100"),
        limit_price=Decimal("10.00"),
        expires_at=None,
        idempotency_key=key,
        correlation_id=uuid4(),
        occurred_at=datetime.now(UTC),
    )


def _provider(**overrides: object) -> ConfiguredRiskLimitsProvider:
    return ConfiguredRiskLimitsProvider(Settings(environment="test", **overrides))


@pytest.mark.asyncio
async def test_pass_is_idempotent_and_creates_one_m05_fact_set(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    factory = _factory(session_factory)
    request = _request(account, instrument, f"risk-pass-{uuid4()}")
    service = RiskGatedOrderService(factory, _provider())
    first = await service.create(request)
    replay = await service.create(request)
    assert first.decision.overall_decision is RiskDecisionType.ALLOW
    assert first.order is not None and first.order.row_version == 2
    assert replay.decision.id == first.decision.id
    assert replay.order is not None and replay.order.id == first.order.id
    async with session_factory() as session:
        counts = [
            await session.scalar(
                text("select count(*) from risk_decisions where id=:id"), {"id": first.decision.id}
            ),
            await session.scalar(
                text("select count(*) from risk_rule_evaluations where risk_decision_id=:id"),
                {"id": first.decision.id},
            ),
            await session.scalar(
                text("select count(*) from orders where id=:id"), {"id": first.order.id}
            ),
            await session.scalar(
                text("select count(*) from order_state_transitions where order_id=:id"),
                {"id": first.order.id},
            ),
        ]
    assert counts == [1, 11, 1, 2]


@pytest.mark.asyncio
async def test_reject_persists_rules_without_order_or_ledgers(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    request = _request(account, instrument, f"risk-reject-{uuid4()}")
    service = RiskGatedOrderService(
        _factory(session_factory), _provider(risk_max_order_notional=Decimal("500"))
    )
    result = await service.create(request)
    assert result.decision.overall_decision is RiskDecisionType.REJECT
    assert result.order is None and result.decision.order_id is None
    async with session_factory() as session:
        assert (
            await session.scalar(
                text("select count(*) from risk_rule_evaluations where risk_decision_id=:id"),
                {"id": result.decision.id},
            )
            == 11
        )
        assert (
            await session.scalar(
                text("select count(*) from orders where idempotency_key=:key"),
                {"key": request.idempotency_key},
            )
            == 0
        )
        assert (
            await session.scalar(
                text("select count(*) from fills where account_id=:id"), {"id": account.id}
            )
            == 0
        )
        assert (
            await session.scalar(
                text("select count(*) from ledger_transactions where account_id=:id"),
                {"id": account.id},
            )
            == 1
        )


@pytest.mark.asyncio
async def test_failure_after_rules_rolls_back_and_session_remains_usable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    request = _request(account, instrument, f"risk-fail-{uuid4()}")

    def fail(stage: str) -> None:
        if stage == "after_rules":
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        await RiskGatedOrderService(_factory(session_factory), _provider(), fail).create(request)
    async with session_factory() as session:
        assert (
            await session.scalar(
                text("select count(*) from risk_decisions where idempotency_key=:key"),
                {"key": request.idempotency_key},
            )
            == 0
        )
        assert await session.scalar(text("select 1")) == 1


@pytest.mark.asyncio
async def test_same_key_different_fingerprint_conflicts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account, instrument = await _seed(session_factory)
    request = _request(account, instrument, f"risk-conflict-{uuid4()}")
    service = RiskGatedOrderService(_factory(session_factory), _provider())
    await service.create(request)
    with pytest.raises(Exception, match="idempotency"):
        await service.create(replace(request, quantity=Decimal("200")))


@pytest.mark.asyncio
async def test_concurrent_identical_request_converges() -> None:
    engine = create_async_engine(require_test_database_url(), pool_pre_ping=True)
    independent_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        account, instrument = await _seed(independent_factory)
        request = _request(account, instrument, f"risk-concurrent-{uuid4()}")
        service = RiskGatedOrderService(_factory(independent_factory), _provider())
        left, right = await asyncio.gather(service.create(request), service.create(request))
        assert left.decision.id == right.decision.id
        assert left.order is not None and right.order is not None
        assert left.order.id == right.order.id
    finally:
        await engine.dispose()
