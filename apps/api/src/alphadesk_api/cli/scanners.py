"""Local SC01 scanner commands; all operations are research-only."""

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.scanners import (
    ScannerIntegrityService,
    ScannerQueryService,
    ScannerRunRequest,
    ScannerRunService,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.scanners import (
    ScannerParameterType,
    ScannerRegistry,
    register_builtin_scanners,
)


def aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include a UTC offset")
    return parsed.astimezone(UTC)


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


def _parameters(
    registry: ScannerRegistry, scanner_key: str, values: list[str]
) -> dict[str, str | int | bool | None]:
    metadata = registry.create(scanner_key).metadata
    definitions = {item.name: item for item in metadata.parameter_definitions}
    result: dict[str, str | int | bool | None] = {}
    for raw in values:
        if "=" not in raw:
            raise ValueError("--param values must use name=value")
        name, value = raw.split("=", 1)
        definition = definitions.get(name)
        if definition is None:
            raise ValueError(f"unknown scanner parameter: {name}")
        if value.lower() == "null":
            result[name] = None
        elif definition.parameter_type is ScannerParameterType.INTEGER:
            result[name] = int(value)
        elif definition.parameter_type is ScannerParameterType.BOOLEAN:
            if value.lower() not in {"true", "false"}:
                raise ValueError(f"parameter '{name}' must be true or false")
            result[name] = value.lower() == "true"
        else:
            result[name] = value
    return result


async def execute(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    database = DatabaseService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    registry = ScannerRegistry()
    register_builtin_scanners(registry)
    try:
        if args.command == "run":
            outcome = await ScannerRunService(factory, registry).run(
                ScannerRunRequest(
                    scanner_key=args.scanner_key,
                    parameters=_parameters(registry, args.scanner_key, args.param),
                    instrument_ids=tuple(args.instrument_id),
                    timeframe=MarketTimeframe.DAY_1,
                    as_of=args.as_of,
                    idempotency_key=args.idempotency_key,
                    correlation_id=uuid4(),
                )
            )
            return {
                "run": outcome.run,
                "results": outcome.results,
                "replayed": outcome.replayed,
                "warning": "research-only historical scan; no order is created",
            }
        query = ScannerQueryService(factory)
        if args.command == "list":
            items, total = await query.list_runs(
                scanner_key=args.scanner_key,
                status=args.status,
                instrument_id=None,
                created_from=None,
                created_to=None,
                offset=0,
                limit=args.limit,
            )
            return {"items": items, "total": total}
        if args.command == "show":
            run = await query.get(args.scan_run_id)
            if run is None:
                raise ApplicationError("SCAN_RUN_NOT_FOUND", "scan run does not exist")
            return {"run": run, "results": await query.results(args.scan_run_id)}
        if args.command == "verify-integrity":
            issues = await ScannerIntegrityService(factory).verify(args.scan_run_id)
            return {"scan_run_id": args.scan_run_id, "valid": not issues, "issues": issues}
        raise ValueError("unknown command")
    finally:
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-scanners")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--scanner-key", required=True)
    run.add_argument("--instrument-id", type=UUID, action="append", required=True)
    run.add_argument("--as-of", type=aware_datetime, required=True)
    run.add_argument("--idempotency-key", required=True)
    run.add_argument("--param", action="append", default=[])
    listing = commands.add_parser("list")
    listing.add_argument("--scanner-key")
    listing.add_argument("--status")
    listing.add_argument("--limit", type=int, default=20, choices=range(1, 101))
    for name in ("show", "verify-integrity"):
        command = commands.add_parser(name)
        command.add_argument("--scan-run-id", type=UUID, required=True)
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
