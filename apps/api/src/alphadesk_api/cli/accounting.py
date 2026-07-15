"""Development-only commands for deterministic M04 simulated-account acceptance."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import NoReturn, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from alphadesk_api.application.accounting import (
    AccountQueryService,
    AccountReconciliationService,
    AccountValuationService,
    CashFundingService,
    FillAccountingService,
    SimulatedAccountService,
)
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.market_data import MarketDataQueryService
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.entities import Fill, Order, TradingAccount
from alphadesk_domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    SettlementPolicy,
    TimeInForce,
)


def _demo_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"alphadesk:m04:demo:{name}")


async def _account_by_code(uow_factory: UnitOfWorkFactory, account_code: str) -> TradingAccount:
    async with uow_factory() as uow:
        account = await uow.accounts.get_by_business_key(account_code)
    if account is None:
        raise ValueError(f"account {account_code} does not exist")
    return account


async def _create_demo_account(
    service: SimulatedAccountService, account_code: str = "DEMO-001"
) -> TradingAccount:
    return await service.create(
        account_code=account_code,
        name="M04 Demo Account",
        base_currency="CNY",
        initial_cash=Decimal("100000"),
        settlement_policy=SettlementPolicy.IMMEDIATE,
        idempotency_key=f"m04-demo-account:{account_code}",
        correlation_id=_demo_id(f"account:{account_code}"),
    )


def _demo_facts(account_id: UUID, instrument_id: UUID) -> list[tuple[Order, Fill]]:
    specs = (
        ("buy-1", OrderSide.BUY, Decimal("1000"), Decimal("8"), Decimal("5"), Decimal("0")),
        ("buy-2", OrderSide.BUY, Decimal("500"), Decimal("8.4"), Decimal("5"), Decimal("0")),
        ("sell-1", OrderSide.SELL, Decimal("600"), Decimal("8.6"), Decimal("5"), Decimal("5.16")),
    )
    facts = []
    for index, (name, side, quantity, price, commission, tax) in enumerate(specs):
        gross = quantity * price
        fees = commission + tax
        net = gross + fees if side is OrderSide.BUY else gross - fees
        correlation_id = _demo_id(f"correlation:{name}")
        executed_at = datetime(2026, 1, 2, 2, index, tzinfo=UTC)
        order = Order(
            id=_demo_id(f"order:{name}"),
            account_id=account_id,
            instrument_id=instrument_id,
            side=side,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            requested_quantity=quantity,
            filled_quantity=quantity,
            average_fill_price=price,
            status=OrderStatus.FILLED,
            idempotency_key=f"M04-DEMO-ORDER-{name}",
            broker_type="DEMO",
            broker_order_id=f"DEMO-{name}",
            correlation_id=correlation_id,
            submitted_at=executed_at,
            completed_at=executed_at,
            metadata={"DEMO": True, "scope": "M04", "synthetic": True},
        )
        fill = Fill(
            id=_demo_id(f"fill:{name}"),
            order_id=order.id,
            account_id=account_id,
            instrument_id=instrument_id,
            broker_type="DEMO",
            broker_fill_id=f"DEMO-FILL-{name}",
            quantity=quantity,
            price=price,
            gross_amount=gross,
            commission=commission,
            tax=tax,
            other_fee=Decimal("0"),
            net_amount=net,
            executed_at=executed_at,
            received_at=executed_at,
            correlation_id=correlation_id,
            metadata={"DEMO": True, "scope": "M04", "synthetic": True},
        )
        facts.append((order, fill))
    return facts


async def execute(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    if settings.environment not in ("development", "test"):
        raise ValueError("M04 accounting CLI is restricted to development/test")
    database = DatabaseService(settings)
    uow_factory = cast(UnitOfWorkFactory, database.unit_of_work)
    accounts = SimulatedAccountService(uow_factory)
    try:
        if args.command == "create-demo-account":
            account = await _create_demo_account(accounts)
            return {"account_id": str(account.id), "account_code": account.account_code}
        if args.command == "deposit":
            account = await _account_by_code(uow_factory, args.account_code)
            transaction = await CashFundingService(uow_factory).post(
                account_id=account.id,
                amount=args.amount,
                is_deposit=True,
                idempotency_key=args.idempotency_key,
                correlation_id=uuid4(),
                description="M04 CLI demo deposit",
            )
            return {"transaction_id": str(transaction.id), "status": transaction.status.value}
        if args.command == "apply-fill":
            result = await FillAccountingService(uow_factory).apply(fill_id=args.fill_id)
            return {"fill_id": str(result.fill_id), "idempotent": result.idempotent}
        if args.command == "seed-demo-portfolio":
            account = await _account_by_code(uow_factory, args.account_code)
            async with uow_factory() as uow:
                instrument = await uow.instruments.get_by_business_key("SSE", "600000")
                if instrument is None:
                    raise ValueError(
                        "M03 DEMO instrument SSE:600000 is missing; seed market data first"
                    )
                facts = _demo_facts(account.id, instrument.id)
                new_orders = 0
                new_fills = 0
                for order, fill in facts:
                    if await uow.orders.get_by_id(order.id) is None:
                        await uow.orders.add(order)
                        new_orders += 1
                    if await uow.fills.get_by_id(fill.id) is None:
                        await uow.fills.append(fill)
                        new_fills += 1
                await uow.commit()
            posted = 0
            already_posted = 0
            for _, fill in facts:
                fill_result = await FillAccountingService(uow_factory).apply(fill_id=fill.id)
                if fill_result.idempotent:
                    already_posted += 1
                else:
                    posted += 1
            return {
                "new_orders": new_orders,
                "new_fills": new_fills,
                "posted": posted,
                "already_posted": already_posted,
            }
        account = await _account_by_code(uow_factory, args.account_code)
        if args.command == "value-account":
            query = MarketDataQueryService(
                uow_factory, minute_stale_seconds=settings.market_minute_stale_seconds
            )
            valuation_result = await AccountValuationService(uow_factory, query).value(
                account_id=account.id, correlation_id=uuid4()
            )
            return {
                "snapshot_id": str(valuation_result.snapshot.id),
                "valuation_status": valuation_result.snapshot.valuation_status.value,
                "total_equity": valuation_result.snapshot.total_equity,
                "unpriced": len(valuation_result.unpriced_instrument_ids),
            }
        if args.command == "reconcile":
            reconciliation_result = await AccountReconciliationService(uow_factory).run(
                account_id=account.id, correlation_id=uuid4()
            )
            return {
                "run_id": str(reconciliation_result.run.id),
                "reconciliation_status": reconciliation_result.run.status.value,
                "discrepancies": reconciliation_result.run.discrepancy_count,
            }
        if args.command == "summary":
            _, balances, positions, snapshot, reconciliation = await AccountQueryService(
                uow_factory
            ).summary(account.id)
            return {
                "cash": {item.currency: item.total_cash for item in balances},
                "positions": [
                    {
                        "instrument_id": str(item.instrument_id),
                        "quantity": item.total_quantity,
                        "average_cost": item.average_cost,
                        "realized_pnl": item.realized_pnl,
                    }
                    for item in positions
                ],
                "valuation_status": None if snapshot is None else snapshot.valuation_status.value,
                "reconciliation_status": (
                    None if reconciliation is None else reconciliation.status.value
                ),
            }
        raise ValueError("unknown command")
    finally:
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-accounting")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create-demo-account")
    deposit = commands.add_parser("deposit")
    deposit.add_argument("--account-code", default="DEMO-001")
    deposit.add_argument("--amount", type=Decimal, required=True)
    deposit.add_argument("--idempotency-key", default="m04-cli-demo-deposit")
    seed = commands.add_parser("seed-demo-portfolio")
    seed.add_argument("--account-code", default="DEMO-001")
    fill = commands.add_parser("apply-fill")
    fill.add_argument("--fill-id", type=UUID, required=True)
    for command_name in ("value-account", "reconcile", "summary"):
        command = commands.add_parser(command_name)
        command.add_argument("--account-code", default="DEMO-001")
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
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
