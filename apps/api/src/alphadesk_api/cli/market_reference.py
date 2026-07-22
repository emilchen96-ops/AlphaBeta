"""Bounded D02 reference-data synchronization commands."""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date, timedelta
from typing import NoReturn, cast
from uuid import UUID

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.historical_market_data import InstrumentUniverseSyncService
from alphadesk_api.application.market_reference import (
    MarketReferenceQueryService,
    ReferenceMarketDataSyncService,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.market_reference import FixtureMarketReferenceProvider


async def execute(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    database = DatabaseService(settings)
    uow_factory = cast(UnitOfWorkFactory, database.unit_of_work)
    try:
        if args.command in {"status", "verify"}:
            value = await MarketReferenceQueryService(uow_factory).status()
            return asdict(value)
        if args.provider != "fixture":
            raise ApplicationError(
                "MARKET_REFERENCE_PROVIDER_NOT_CONFIGURED",
                "CLI 当前仅启用离线 Fixture; Tushare 需配置后联调",
            )
        provider = FixtureMarketReferenceProvider()
        service = ReferenceMarketDataSyncService(uow_factory, provider, "FIXTURE")
        end = args.end or date.today()
        start = args.start or end - timedelta(days=365)
        if args.command == "sync-calendar":
            result = await service.sync_calendar(
                start=start, end=end, exchanges=("SHSE", "SZSE"), dry_run=args.dry_run
            )
        else:
            instruments = await InstrumentUniverseSyncService(uow_factory).resolve_universe(
                universe="manual" if args.instrument else args.universe,
                limit=args.max_instruments,
                instrument_ids=args.instrument or None,
            )
            if not instruments:
                raise ApplicationError(
                    "MARKET_REFERENCE_DATA_NOT_READY",
                    "所选股票池没有可同步的 Instrument",
                )
            if args.command == "sync-adjustments":
                result = await service.sync_adjustments(
                    instruments=instruments, start=start, end=end, dry_run=args.dry_run
                )
            elif args.command == "sync-suspensions":
                result = await service.sync_suspensions(
                    instruments=instruments, start=start, end=end, dry_run=args.dry_run
                )
            else:
                result = await service.sync_lifecycle(instruments=instruments, dry_run=args.dry_run)
        return asdict(result)
    finally:
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-market-reference")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "sync-calendar",
        "sync-adjustments",
        "sync-suspensions",
        "sync-instrument-lifecycle",
    ):
        command = commands.add_parser(name)
        command.add_argument("--start", type=date.fromisoformat)
        command.add_argument("--end", type=date.fromisoformat)
        command.add_argument("--universe", default="research")
        command.add_argument("--instrument", action="append", type=UUID)
        command.add_argument("--provider", default="fixture")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--max-instruments", type=int, default=30, choices=range(1, 501))
    commands.add_parser("verify")
    commands.add_parser("status")
    return parser


def fail(message: str, code: str) -> NoReturn:
    print(json.dumps({"status": "error", "error": {"code": code, "message": message}}))
    raise SystemExit(2)


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(execute(args, get_settings()))
    except ApplicationError as exc:
        fail(exc.message, exc.code)
    except (OSError, RuntimeError, ValueError) as exc:
        fail(str(exc), "MARKET_REFERENCE_SYNC_FAILED")
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
