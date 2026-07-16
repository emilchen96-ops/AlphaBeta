"""Development/test CLI for accepting the M05 local order-fact pipeline."""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import NoReturn, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.orders import (
    CancelOrderRequest,
    ConfirmOrderRequest,
    CreateOrderRequest,
    OrderCancellationService,
    OrderConfirmationService,
    OrderExpirationService,
    OrderIntegrityService,
    OrderIntentService,
    OrderQueryService,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService


def _demo_uuid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"alphadesk:m05:demo:{name}")


async def _demo_order_context(factory: UnitOfWorkFactory) -> tuple[UUID, UUID]:
    async with factory() as uow:
        account = await uow.accounts.get_by_business_key("DEMO-001")
        instrument = await uow.instruments.get_by_business_key("SSE", "600000")
    if account is None:
        raise ValueError("DEMO-001 is missing; create the M04 demo account first")
    if instrument is None:
        raise ValueError("SSE:600000 is missing; seed the M03 demo instrument first")
    return account.id, instrument.id


async def execute(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    if settings.environment not in ("development", "test"):
        raise ValueError("M05 order CLI is restricted to development/test")
    database = DatabaseService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    try:
        if args.command == "create-demo-orders":
            account_id, instrument_id = await _demo_order_context(factory)
            now = datetime.now(UTC)
            orders = []
            for index, expires_at in enumerate((None, None, now + timedelta(seconds=2)), start=1):
                idempotency_key = f"m05-demo-order-{index}"
                async with factory() as uow:
                    existing = await uow.orders.get_by_idempotency_key(idempotency_key)
                if existing is not None:
                    orders.append(existing)
                    continue
                orders.append(
                    await OrderIntentService(factory).create(
                        CreateOrderRequest(
                            account_id=account_id,
                            instrument_id=instrument_id,
                            side="BUY",
                            order_type="LIMIT",
                            time_in_force="DAY",
                            quantity=Decimal("1000"),
                            limit_price=Decimal(f"{8 + index / 10:.2f}"),
                            expires_at=expires_at,
                            idempotency_key=idempotency_key,
                            correlation_id=_demo_uuid(f"order-{index}"),
                            note=f"M05 demo order {index}",
                            occurred_at=now,
                        )
                    )
                )
            return {
                "orders": [
                    {
                        "id": str(item.id),
                        "status": item.status.value,
                        "row_version": item.row_version,
                    }
                    for item in orders
                ]
            }
        if args.command == "list":
            page = await OrderQueryService(factory).list(page=args.page, page_size=args.page_size)
            return dict(page)
        if args.command == "confirm":
            order = await OrderConfirmationService(factory).confirm(
                ConfirmOrderRequest(
                    order_id=args.order_id,
                    idempotency_key=args.idempotency_key or f"m05-cli-confirm-{args.order_id}",
                    expected_order_version=args.expected_version,
                    correlation_id=uuid4(),
                    occurred_at=datetime.now(UTC),
                )
            )
            return {
                "order_id": str(order.id),
                "order_status": order.status.value,
                "row_version": order.row_version,
            }
        if args.command == "cancel":
            order = await OrderCancellationService(factory).cancel(
                CancelOrderRequest(
                    order_id=args.order_id,
                    idempotency_key=args.idempotency_key or f"m05-cli-cancel-{args.order_id}",
                    expected_order_version=args.expected_version,
                    reason=args.reason,
                    correlation_id=uuid4(),
                    occurred_at=datetime.now(UTC),
                )
            )
            return {
                "order_id": str(order.id),
                "order_status": order.status.value,
                "row_version": order.row_version,
            }
        if args.command == "expire-pending":
            result = await OrderExpirationService(factory, batch_limit=args.limit).expire_pending(
                now=datetime.now(UTC)
            )
            return {
                "expired_order_ids": [str(item) for item in result.expired_order_ids],
                "skipped_order_ids": [str(item) for item in result.skipped_order_ids],
            }
        if args.command == "verify-integrity":
            issues = await OrderIntegrityService(factory).verify()
            return {
                "issue_count": len(issues),
                "issues": [
                    {"order_id": str(item.order_id), "code": item.code, "message": item.message}
                    for item in issues
                ],
            }
        raise ValueError("unknown command")
    finally:
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-orders")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create-demo-orders")
    listing = commands.add_parser("list")
    listing.add_argument("--page", type=int, default=1)
    listing.add_argument("--page-size", type=int, default=20)
    for name in ("confirm", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("--order-id", type=UUID, required=True)
        command.add_argument("--expected-version", type=int, required=True)
        command.add_argument("--idempotency-key")
        if name == "cancel":
            command.add_argument("--reason")
    expire = commands.add_parser("expire-pending")
    expire.add_argument("--limit", type=int, default=100)
    commands.add_parser("verify-integrity")
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
