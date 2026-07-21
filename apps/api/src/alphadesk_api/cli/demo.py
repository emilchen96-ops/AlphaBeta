"""U01 one-click local research initialization and verification CLI."""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, NoReturn, cast
from uuid import UUID

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.demo import (
    ResearchDemoInitializationService,
    ResearchDemoVerificationService,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.redis import RedisService
from alphadesk_api.infrastructure.system_capabilities import SqlAlchemyCapabilityDataProvider
from alphadesk_domain.scanners import ScannerRegistry, register_builtin_scanners
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies


def _json(value: Any) -> Any:
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


async def execute(args: argparse.Namespace, settings: Settings) -> object:
    if settings.environment not in ("development", "test"):
        raise ValueError("U01 CLI is restricted to development/test")
    database = DatabaseService(settings)
    redis = RedisService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    strategies = StrategyRegistry()
    scanners = ScannerRegistry()
    register_builtin_strategies(strategies)
    register_builtin_scanners(scanners)
    try:
        if args.command == "initialize-research":
            return asdict(
                await ResearchDemoInitializationService(
                    factory, strategies, scanners, settings
                ).initialize(
                    mode=args.mode,
                    reset_demo=args.reset_demo,
                    dry_run=args.dry_run,
                )
            )
        if args.command == "verify-research":
            postgresql_ok, redis_ok = await asyncio.gather(database.ping(), redis.ping())
            return asdict(
                await ResearchDemoVerificationService(
                    SqlAlchemyCapabilityDataProvider(database.session_factory),
                    settings,
                    postgresql_ok=postgresql_ok,
                    redis_ok=redis_ok,
                ).verify()
            )
        raise ValueError("unsupported command")
    finally:
        await redis.close()
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-demo")
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("initialize-research")
    initialize.add_argument("--mode", choices=("existing-data", "fixture"), default="existing-data")
    initialize.add_argument("--reset-demo", action="store_true")
    initialize.add_argument("--dry-run", action="store_true")
    initialize.add_argument("--json", action="store_true")
    verify = commands.add_parser("verify-research")
    verify.add_argument("--json", action="store_true")
    return parser


def _print_human(result: dict[str, object]) -> None:
    print(f"AlphaDesk U01: {result.get('status', 'UNKNOWN')}")
    rows = cast(list[dict[str, object]], result.get("steps", result.get("items", [])))
    for item in rows:
        detail = item.get("message", item.get("reason", ""))
        print(f"[{item['status']}] {item.get('label', item['key'])}: {detail}")
    for action in cast(list[str], result.get("required_actions", [])):
        print(f"NEXT: {action}")


def main() -> NoReturn:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = cast(dict[str, object], asyncio.run(execute(args, get_settings())))
    except (ApplicationError, OSError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"U01 failed: {exc}\n")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, default=_json, indent=2))
    else:
        _print_human(result)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
