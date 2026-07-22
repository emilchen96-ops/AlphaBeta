"""Safe offline D03 intraday maintenance CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from alphadesk_api.application.catalog import InstrumentCatalogService
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.intraday import (
    IntradayAggregationService,
    IntradayMarketDataImportService,
    IntradayOverviewService,
    IntradayQualityService,
    ensure_fixture_catalog,
    fixture_rows,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.intraday_provider import (
    FixtureIntradayMarketDataProvider,
    LocalFileIntradayMarketDataProvider,
)
from alphadesk_domain.enums import MarketDataSourceStatus, MarketProviderTier, MarketTimeframe
from alphadesk_domain.intraday import INTRADAY_TIMEFRAMES, IntradayConflictPolicy

ALIASES = {
    "1m": MarketTimeframe.MINUTE_1,
    "5m": MarketTimeframe.MINUTE_5,
    "15m": MarketTimeframe.MINUTE_15,
    "30m": MarketTimeframe.MINUTE_30,
    "60m": MarketTimeframe.MINUTE_60,
}


def aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must contain an explicit UTC offset")
    return parsed


def timeframes(value: str) -> tuple[MarketTimeframe, ...]:
    try:
        return tuple(ALIASES[item.strip().lower()] for item in value.split(",") if item.strip())
    except KeyError as exc:
        raise argparse.ArgumentTypeError("timeframes must be 1m,5m,15m,30m,60m") from exc


def json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return str(value)


async def resolve_instrument_id(factory: UnitOfWorkFactory, value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        pass
    async with factory() as uow:
        instruments, _ = await uow.instruments.search(
            keyword=value.strip().upper(),
            exchange=None,
            market="CN",
            asset_type="STOCK",
            is_active=True,
            offset=0,
            limit=100,
        )
    exact = [item for item in instruments if item.symbol.upper() == value.strip().upper()]
    if len(exact) != 1:
        raise ValueError("--instrument must be one exact A-share symbol or UUID")
    return exact[0].id


async def execute(args: argparse.Namespace, settings: Settings) -> object:
    database = DatabaseService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    try:
        if args.command == "generate-fixture":
            if not args.dry_run:
                await ensure_fixture_catalog(factory)
            return asdict(
                await IntradayMarketDataImportService(
                    factory, batch_size=settings.intraday_import_batch_size
                ).run(
                    FixtureIntradayMarketDataProvider(fixture_rows()),
                    source_code="D03_FIXTURE",
                    source_timezone="Asia/Shanghai",
                    target_timeframes=args.aggregate,
                    conflict_policy=IntradayConflictPolicy(args.conflict_policy),
                    dry_run=args.dry_run,
                    correlation_id=uuid4(),
                )
            )
        if args.command in {"import-file", "import-directory"}:
            catalog = InstrumentCatalogService(factory)
            await catalog.ensure_source(
                source_code="LOCAL_INTRADAY",
                name="Local offline intraday files",
                status=MarketDataSourceStatus.ACTIVE,
                priority=10,
                supports_realtime=False,
                supported_timeframes=INTRADAY_TIMEFRAMES,
                provider_tier=MarketProviderTier.DEMO,
            )
            paths = (
                [Path(args.path)]
                if args.command == "import-file"
                else sorted(Path(args.path).glob("*.csv"))  # noqa: ASYNC240
            )
            results = []
            for path in paths:
                provider = LocalFileIntradayMarketDataProvider(
                    path,
                    source_timezone=args.source_timezone,
                    max_bytes=settings.intraday_import_max_file_size_mb * 1024 * 1024,
                    max_rows=1_000_000,
                    allowed_root=path.resolve().parent,
                )
                results.append(
                    asdict(
                        await IntradayMarketDataImportService(
                            factory, batch_size=settings.intraday_import_batch_size
                        ).run(
                            provider,
                            source_code="LOCAL_INTRADAY",
                            source_timezone=args.source_timezone,
                            target_timeframes=args.aggregate,
                            conflict_policy=IntradayConflictPolicy(args.conflict_policy),
                            continue_on_error=args.continue_on_error,
                            dry_run=args.dry_run,
                            correlation_id=uuid4(),
                        )
                    )
                )
            return {"files": len(paths), "results": results}
        if args.command == "aggregate":
            aggregation_result = await IntradayAggregationService(factory).run(
                instrument_id=await resolve_instrument_id(factory, args.instrument),
                source_code=args.source,
                start_at=args.start,
                end_at=args.end,
                targets=args.targets,
                dry_run=args.dry_run,
                correlation_id=uuid4(),
            )
            return {"result": aggregation_result[:2]}
        if args.command == "verify-quality":
            return asdict(
                await IntradayQualityService(factory).run(
                    instrument_id=await resolve_instrument_id(factory, args.instrument),
                    source_code=args.source,
                    timeframe=args.timeframe,
                    start_at=args.start,
                    end_at=args.end,
                    correlation_id=uuid4(),
                )
            )
        if args.command == "coverage":
            return {"items": await IntradayOverviewService(factory).coverage(args.source)}
        if args.command == "readiness":
            return {"items": await IntradayOverviewService(factory).readiness(args.source)}
        raise ValueError("unsupported command")
    finally:
        await database.close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="AlphaDesk D03 offline intraday data CLI")
    sub = root.add_subparsers(dest="command", required=True)
    for command in ("import-file", "import-directory"):
        item = sub.add_parser(command)
        item.add_argument("--path", required=True)
        item.add_argument("--source-timezone")
        item.add_argument("--aggregate", type=timeframes, default=())
        item.add_argument(
            "--conflict-policy",
            choices=[item.value for item in IntradayConflictPolicy],
            default="keep_existing",
        )
        item.add_argument(
            "--continue-on-error", action=argparse.BooleanOptionalAction, default=True
        )
        item.add_argument("--dry-run", action="store_true")
    fixture = sub.add_parser("generate-fixture")
    fixture.add_argument("--aggregate", type=timeframes, default=INTRADAY_TIMEFRAMES[1:])
    fixture.add_argument(
        "--conflict-policy",
        choices=[item.value for item in IntradayConflictPolicy],
        default="keep_existing",
    )
    fixture.add_argument("--dry-run", action="store_true")
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--instrument", "--instrument-id", dest="instrument", required=True)
    aggregate.add_argument("--source", default="D03_FIXTURE")
    aggregate.add_argument("--start", type=aware, required=True)
    aggregate.add_argument("--end", type=aware, required=True)
    aggregate.add_argument("--targets", type=timeframes, required=True)
    aggregate.add_argument("--dry-run", action="store_true")
    quality = sub.add_parser("verify-quality")
    quality.add_argument("--instrument", "--instrument-id", dest="instrument", required=True)
    quality.add_argument("--source", default="D03_FIXTURE")
    quality.add_argument(
        "--timeframe", type=lambda value: ALIASES[value], default=MarketTimeframe.MINUTE_1
    )
    quality.add_argument("--start", type=aware, required=True)
    quality.add_argument("--end", type=aware, required=True)
    for command in ("coverage", "readiness"):
        sub.add_parser(command).add_argument("--source", default="D03_FIXTURE")
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        print(
            json.dumps(
                asyncio.run(execute(args, get_settings())), ensure_ascii=False, default=json_default
            )
        )
    except (ApplicationError, ValueError, OSError) as exc:
        print(
            json.dumps(
                {"error": getattr(exc, "code", type(exc).__name__), "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
