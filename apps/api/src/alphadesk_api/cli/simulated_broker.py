"""Development/test CLI for the B01 local simulated Broker."""

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, NoReturn, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.orders import (
    ConfirmOrderRequest,
    CreateOrderRequest,
    OrderConfirmationService,
)
from alphadesk_api.application.risk import ConfiguredRiskLimitsProvider, RiskGatedOrderService
from alphadesk_api.application.simulated_execution import (
    SimulatedBrokerExecutionService,
    SimulatedExecutionIntegrityService,
    SimulatedExecutionMarketInput,
    SimulatedExecutionQueryService,
    SimulatedExecutionResult,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.broker import TradingStatus
from alphadesk_domain.entities import Order
from alphadesk_domain.enums import OrderStatus, RiskDecisionType


def _stable_uuid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"alphadesk:b01:demo:{name}")


def _json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(cast(Any, value))
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


async def _context(factory: UnitOfWorkFactory) -> tuple[UUID, UUID]:
    async with factory() as uow:
        account = await uow.accounts.get_by_business_key("DEMO-001")
        instrument = await uow.instruments.get_by_business_key("SSE", "600000")
    if account is None:
        raise ValueError("DEMO-001 is missing; create the M04 demo account first")
    if instrument is None:
        raise ValueError("SSE:600000 is missing; seed the M03 demo instrument first")
    return account.id, instrument.id


async def _execute_input(
    factory: UnitOfWorkFactory,
    *,
    order_id: UUID,
    key: str,
    timestamp: datetime,
    trading_status: TradingStatus,
    source: str,
    last_price: Decimal | None,
    bid_price: Decimal | None,
    ask_price: Decimal | None,
    available_volume: Decimal | None,
    close: Decimal | None = None,
    limit_up: Decimal | None = None,
    limit_down: Decimal | None = None,
) -> SimulatedExecutionResult:
    return await SimulatedBrokerExecutionService(factory).execute_market_input(
        SimulatedExecutionMarketInput(
            order_id=order_id,
            idempotency_key=key,
            correlation_id=uuid4(),
            timestamp=timestamp,
            trading_status=trading_status,
            source=source,
            is_stale=False,
            last_price=last_price,
            bid_price=bid_price,
            ask_price=ask_price,
            available_volume=available_volume,
            close=close,
            price_limit_up=limit_up,
            price_limit_down=limit_down,
        )
    )


async def _demo_order(
    factory: UnitOfWorkFactory,
    settings: Settings,
    *,
    name: str,
    account_id: UUID,
    instrument_id: UUID,
    side: str,
    quantity: Decimal,
    limit_price: Decimal,
) -> Order:
    now = datetime.now(UTC)
    outcome = await RiskGatedOrderService(factory, ConfiguredRiskLimitsProvider(settings)).create(
        CreateOrderRequest(
            account_id=account_id,
            instrument_id=instrument_id,
            side=side,
            order_type="LIMIT",
            time_in_force="DAY",
            quantity=quantity,
            limit_price=limit_price,
            expires_at=None,
            idempotency_key=f"b01-demo-create:{name}",
            correlation_id=_stable_uuid(f"create:{name}"),
            note=f"B01 deterministic demo {name}",
            occurred_at=now,
        )
    )
    if outcome.decision.overall_decision is not RiskDecisionType.ALLOW or outcome.order is None:
        raise ValueError(f"demo order {name} did not pass R01")
    order = outcome.order
    if order.status is OrderStatus.WAITING_CONFIRMATION:
        order = await OrderConfirmationService(factory).confirm(
            ConfirmOrderRequest(
                order_id=order.id,
                idempotency_key=f"b01-demo-confirm:{name}",
                expected_order_version=order.row_version,
                correlation_id=_stable_uuid(f"confirm:{name}"),
                occurred_at=now,
            )
        )
    return order


async def _run_demo(factory: UnitOfWorkFactory, settings: Settings) -> dict[str, object]:
    account_id, instrument_id = await _context(factory)
    scenarios: dict[str, object] = {}

    buy = await _demo_order(
        factory,
        settings,
        name="buy",
        account_id=account_id,
        instrument_id=instrument_id,
        side="BUY",
        quantity=Decimal("100"),
        limit_price=Decimal("10"),
    )
    scenarios["BUY"] = await _execute_input(
        factory,
        order_id=buy.id,
        key="b01-demo-execute:buy",
        timestamp=buy.created_at + timedelta(seconds=1),
        trading_status=TradingStatus.TRADING,
        source="B01_DEMO",
        last_price=Decimal("9.98"),
        bid_price=Decimal("9.97"),
        ask_price=Decimal("9.99"),
        available_volume=Decimal("100"),
    )
    sell = await _demo_order(
        factory,
        settings,
        name="sell",
        account_id=account_id,
        instrument_id=instrument_id,
        side="SELL",
        quantity=Decimal("100"),
        limit_price=Decimal("10"),
    )
    scenarios["SELL"] = await _execute_input(
        factory,
        order_id=sell.id,
        key="b01-demo-execute:sell",
        timestamp=sell.created_at + timedelta(seconds=1),
        trading_status=TradingStatus.TRADING,
        source="B01_DEMO",
        last_price=Decimal("10.02"),
        bid_price=Decimal("10.01"),
        ask_price=Decimal("10.03"),
        available_volume=Decimal("100"),
    )
    no_fill = await _demo_order(
        factory,
        settings,
        name="no-fill",
        account_id=account_id,
        instrument_id=instrument_id,
        side="BUY",
        quantity=Decimal("100"),
        limit_price=Decimal("9"),
    )
    scenarios["NO_FILL"] = await _execute_input(
        factory,
        order_id=no_fill.id,
        key="b01-demo-execute:no-fill",
        timestamp=no_fill.created_at + timedelta(seconds=1),
        trading_status=TradingStatus.TRADING,
        source="B01_DEMO",
        last_price=Decimal("10"),
        bid_price=Decimal("9.99"),
        ask_price=Decimal("10.01"),
        available_volume=Decimal("100"),
    )
    partial = await _demo_order(
        factory,
        settings,
        name="partial",
        account_id=account_id,
        instrument_id=instrument_id,
        side="BUY",
        quantity=Decimal("200"),
        limit_price=Decimal("10"),
    )
    first = await _execute_input(
        factory,
        order_id=partial.id,
        key="b01-demo-execute:partial:1",
        timestamp=partial.created_at + timedelta(seconds=1),
        trading_status=TradingStatus.TRADING,
        source="B01_DEMO",
        last_price=Decimal("9.98"),
        bid_price=Decimal("9.97"),
        ask_price=Decimal("9.99"),
        available_volume=Decimal("100"),
    )
    second = await _execute_input(
        factory,
        order_id=partial.id,
        key="b01-demo-execute:partial:2",
        timestamp=partial.created_at + timedelta(seconds=2),
        trading_status=TradingStatus.TRADING,
        source="B01_DEMO",
        last_price=Decimal("9.98"),
        bid_price=Decimal("9.97"),
        ask_price=Decimal("9.99"),
        available_volume=Decimal("100"),
    )
    scenarios["PARTIAL"] = {"first": first, "second": second}
    integrity = await SimulatedExecutionIntegrityService(factory).verify_order(partial.id)
    return {"account_id": account_id, "scenarios": scenarios, "integrity_issues": integrity}


async def execute(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    if settings.environment not in ("development", "test"):
        raise ValueError("B01 simulated Broker CLI is restricted to development/test")
    database = DatabaseService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    try:
        if args.command == "execute":
            result = await _execute_input(
                factory,
                order_id=args.order_id,
                key=args.idempotency_key,
                timestamp=args.timestamp or datetime.now(UTC),
                trading_status=TradingStatus(args.trading_status),
                source="B01_CLI",
                last_price=args.last_price,
                bid_price=args.bid_price,
                ask_price=args.ask_price,
                available_volume=args.available_volume,
                close=args.close,
                limit_up=args.limit_up,
                limit_down=args.limit_down,
            )
            return {"result": result}
        query = SimulatedExecutionQueryService(factory)
        if args.command == "list-attempts":
            return await query.list_attempts(args.order_id, page_size=100)
        if args.command == "list-fills":
            return await query.list_fills(order_id=args.order_id, page_size=100)
        if args.command == "verify-integrity":
            issues = await SimulatedExecutionIntegrityService(factory).verify_order(args.order_id)
            return {"order_id": args.order_id, "valid": not issues, "issues": issues}
        if args.command == "run-demo":
            return await _run_demo(factory, settings)
        raise ValueError("unknown command")
    finally:
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-simulated-broker")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("execute")
    run.add_argument("--order-id", type=UUID, required=True)
    run.add_argument("--idempotency-key", required=True)
    run.add_argument("--last-price", type=Decimal)
    run.add_argument("--bid-price", type=Decimal)
    run.add_argument("--ask-price", type=Decimal)
    run.add_argument("--available-volume", type=Decimal)
    run.add_argument(
        "--trading-status",
        default="TRADING",
        choices=[item.value for item in TradingStatus],
    )
    run.add_argument("--close", type=Decimal)
    run.add_argument("--limit-up", type=Decimal)
    run.add_argument("--limit-down", type=Decimal)
    run.add_argument("--timestamp", type=datetime.fromisoformat)
    for name in ("list-attempts", "list-fills", "verify-integrity"):
        command = commands.add_parser(name)
        command.add_argument("--order-id", type=UUID, required=True)
    commands.add_parser("run-demo")
    return parser


def fail(message: str) -> NoReturn:
    print(json.dumps({"status": "error", "error": message}, ensure_ascii=False))
    raise SystemExit(2)


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(execute(args, get_settings()))
    except (ApplicationError, OSError, RuntimeError, ValueError) as exc:
        fail(str(exc))
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, default=_json))


if __name__ == "__main__":
    main()
