"""Safe local market-data maintenance commands for M03."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, cast
from uuid import uuid4

from alphadesk_api.application.catalog import InstrumentCatalogService
from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.market_data import (
    MarketDataIngestionService,
    MarketDataQueryService,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.free_market_cache import (
    HEARTBEAT_KEY,
    QUOTE_CHANNEL,
    STATUS_KEY,
    SUBSCRIPTIONS_KEY,
    read_json,
)
from alphadesk_api.infrastructure.market_data import (
    AkShareEastMoneyRealtimeAdapter,
    BaoStockHistoricalMarketDataAdapter,
    DemoCsvMarketDataAdapter,
    DisabledExternalMarketDataAdapter,
    LocalCsvMarketDataAdapter,
)
from alphadesk_api.infrastructure.redis import RedisService
from alphadesk_api.workers.free_market_data import FreeMarketDataWorker
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketTimeframe,
    SyncTriggerType,
)
from alphadesk_domain.market import InstrumentMapping
from alphadesk_domain.market_adapters import MarketDataAdapter


def aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include a UTC offset")
    return parsed.astimezone(UTC)


def adapter_for(source_code: str) -> MarketDataAdapter:
    normalized = source_code.upper()
    if normalized == "DEMO":
        return DemoCsvMarketDataAdapter()
    if normalized == "EXTERNAL_DISABLED":
        return DisabledExternalMarketDataAdapter()
    if normalized == "BAOSTOCK":
        return BaoStockHistoricalMarketDataAdapter()
    if normalized == "AKSHARE_EASTMONEY":
        return AkShareEastMoneyRealtimeAdapter()
    raise ValueError(f"no configured adapter for source {normalized}")


async def ensure_demo(catalog: InstrumentCatalogService) -> DemoCsvMarketDataAdapter:
    adapter = DemoCsvMarketDataAdapter()
    await catalog.ensure_source(
        source_code=adapter.source_code,
        name="AlphaDesk deterministic demo",
        status=MarketDataSourceStatus.ACTIVE,
        priority=0,
        supports_realtime=False,
        supported_timeframes=(MarketTimeframe.DAY_1, MarketTimeframe.MINUTE_1),
    )
    return adapter


async def ensure_baostock(
    catalog: InstrumentCatalogService,
    uow_factory: UnitOfWorkFactory,
    symbols: list[str],
) -> None:
    source = await catalog.ensure_source(
        source_code="BAOSTOCK",
        name="BaoStock free historical data",
        status=MarketDataSourceStatus.ACTIVE,
        priority=30,
        supports_realtime=False,
        supported_timeframes=(
            MarketTimeframe.DAY_1,
            MarketTimeframe.MINUTE_5,
            MarketTimeframe.MINUTE_15,
            MarketTimeframe.MINUTE_30,
            MarketTimeframe.MINUTE_60,
        ),
        provider_tier=MarketProviderTier.FREE_BEST_EFFORT,
    )
    mappings: list[InstrumentMapping] = []
    async with uow_factory() as uow:
        for symbol in symbols:
            exchange = (
                "SSE"
                if symbol.startswith("6")
                else "BSE"
                if symbol.startswith(("4", "8"))
                else "SZSE"
            )
            instrument = await uow.instruments.get_by_business_key(exchange, symbol.upper())
            if instrument is not None:
                mappings.append(
                    InstrumentMapping(
                        instrument_id=instrument.id,
                        source_id=source.id,
                        external_symbol=symbol.upper(),
                        external_exchange=exchange,
                        metadata={"provider_tier": "FREE_BEST_EFFORT"},
                    )
                )
        await uow.instrument_mappings.upsert_many(mappings)
        await uow.commit()


async def execute(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    database = DatabaseService(settings)
    uow_factory = cast(UnitOfWorkFactory, database.unit_of_work)
    catalog = InstrumentCatalogService(uow_factory)
    ingestion = MarketDataIngestionService(
        uow_factory,
        batch_size=settings.market_sync_batch_size,
        future_tolerance_seconds=settings.market_future_tolerance_seconds,
    )
    try:
        if args.command == "provider-check":
            selected_adapter = adapter_for(args.source)
            health = await selected_adapter.health_check()
            return {
                "source": selected_adapter.source_code,
                "provider_tier": "FREE_BEST_EFFORT",
                "usage": ["RESEARCH_ONLY", "NON_TRADING_GRADE"],
                "health": health.status.value,
                "checked_at": health.checked_at.isoformat(),
                "message": health.message,
            }
        if args.command in {"fetch-free-quotes", "free-market-run-once"}:
            worker = FreeMarketDataWorker(settings)
            try:
                return await worker.run_once()
            finally:
                await worker.close()
        if args.command == "free-market-status":
            redis_service = RedisService(settings)
            try:
                return {
                    "status": await read_json(redis_service.client, STATUS_KEY),
                    "heartbeat": await read_json(redis_service.client, HEARTBEAT_KEY),
                    "subscriptions": await read_json(redis_service.client, SUBSCRIPTIONS_KEY),
                }
            finally:
                await redis_service.close()
        if args.command == "seed-demo":
            adapter = await ensure_demo(catalog)
            instrument_count, mapping_count = await catalog.import_from_adapter(adapter, uuid4())
            runs = []
            for timeframe in (MarketTimeframe.DAY_1, MarketTimeframe.MINUTE_1):
                run = await ingestion.sync_bars(
                    adapter=adapter,
                    symbols=["600000", "000001", "510300"],
                    timeframe=timeframe,
                    adjustment=AdjustmentType.NONE,
                    start=datetime(2024, 1, 1, tzinfo=UTC),
                    end=datetime(2026, 1, 1, tzinfo=UTC),
                    trigger_type=SyncTriggerType.MANUAL,
                    correlation_id=uuid4(),
                )
                runs.append(run)
            return {
                "source": "DEMO",
                "instruments": instrument_count,
                "mappings": mapping_count,
                "runs": [
                    {
                        "timeframe": run.timeframe.value,
                        "status": run.status.value,
                        "received": run.total_received,
                        "inserted": run.total_inserted,
                        "updated": run.total_updated,
                    }
                    for run in runs
                ],
            }
        if args.command == "sync-instruments":
            selected_adapter = adapter_for(args.source)
            if selected_adapter.source_code == "DEMO":
                await ensure_demo(catalog)
            elif selected_adapter.source_code == "AKSHARE_EASTMONEY":
                await catalog.ensure_source(
                    source_code=selected_adapter.source_code,
                    name="AKShare EastMoney free snapshot",
                    status=MarketDataSourceStatus.ACTIVE,
                    priority=20,
                    supports_realtime=True,
                    supported_timeframes=(MarketTimeframe.MINUTE_1,),
                    provider_tier=MarketProviderTier.FREE_BEST_EFFORT,
                    supports_quotes=True,
                    supports_recent_minute_bars=True,
                )
            instruments, mappings = await catalog.import_from_adapter(selected_adapter, uuid4())
            return {
                "source": selected_adapter.source_code,
                "instruments": instruments,
                "mappings": mappings,
            }
        if args.command in {"sync-bars", "import-csv", "sync-daily", "sync-recent-minute-bars"}:
            if args.command == "import-csv":
                csv_adapter = LocalCsvMarketDataAdapter(
                    Path(args.path),
                    source_code=args.source,
                    timeframe=args.timeframe,
                    max_bytes=settings.market_csv_max_bytes,
                    max_rows=settings.market_csv_max_rows,
                )
                selected_adapter = csv_adapter
                symbols = csv_adapter.symbols
            elif args.command == "sync-daily":
                selected_adapter = adapter_for("BAOSTOCK")
                symbols = [value.strip() for value in args.symbols.split(",") if value.strip()]
                await ensure_baostock(catalog, uow_factory, symbols)
                args.timeframe = MarketTimeframe.DAY_1
                args.adjustment = AdjustmentType.NONE
            elif args.command == "sync-recent-minute-bars":
                selected_adapter = adapter_for("AKSHARE_EASTMONEY")
                symbols = [value.strip() for value in args.symbols.split(",") if value.strip()]
                args.timeframe = MarketTimeframe.MINUTE_1
                args.adjustment = AdjustmentType.NONE
            else:
                selected_adapter = adapter_for(args.source)
                symbols = [value.strip() for value in args.symbols.split(",") if value.strip()]
            run = await ingestion.sync_bars(
                adapter=selected_adapter,
                symbols=symbols,
                timeframe=args.timeframe,
                adjustment=args.adjustment,
                start=args.start,
                end=args.end,
                trigger_type=SyncTriggerType.CLI,
                correlation_id=uuid4(),
            )
            if args.command == "sync-recent-minute-bars":
                redis_service = RedisService(settings)
                try:
                    await redis_service.client.publish(
                        QUOTE_CHANNEL,
                        json.dumps(
                            {
                                "schema_version": 1,
                                "type": "minute_bar_updated",
                                "symbols": symbols,
                                "run_id": str(run.id),
                                "completed_at": (
                                    None
                                    if run.completed_at is None
                                    else run.completed_at.isoformat()
                                ),
                            }
                        ),
                    )
                finally:
                    await redis_service.close()
            return {
                "run_id": str(run.id),
                "status": run.status.value,
                "received": run.total_received,
                "inserted": run.total_inserted,
                "updated": run.total_updated,
                "rejected": run.total_rejected,
            }
        if args.command == "sync-status":
            values = await MarketDataQueryService(uow_factory).sync_runs(args.limit)
            return {
                "runs": [
                    {
                        "id": str(run.id),
                        "source_id": str(run.source_id),
                        "status": run.status.value,
                        "timeframe": run.timeframe.value,
                        "started_at": run.started_at.isoformat(),
                        "completed_at": (
                            None if run.completed_at is None else run.completed_at.isoformat()
                        ),
                    }
                    for run in values
                ]
            }
        raise ValueError("unknown command")
    finally:
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-market-data")
    commands = parser.add_subparsers(dest="command", required=True)
    provider = commands.add_parser("provider-check")
    provider.add_argument("--source", default="AKSHARE_EASTMONEY")
    commands.add_parser("fetch-free-quotes")
    commands.add_parser("free-market-status")
    commands.add_parser("free-market-run-once")
    commands.add_parser("seed-demo")
    instruments = commands.add_parser("sync-instruments")
    instruments.add_argument("--source", default="DEMO")
    bars = commands.add_parser("sync-bars")
    bars.add_argument("--source", default="DEMO")
    bars.add_argument("--symbols", required=True)
    csv_import = commands.add_parser("import-csv")
    csv_import.add_argument("path")
    csv_import.add_argument("--source", default="DEMO")
    daily = commands.add_parser("sync-daily")
    daily.add_argument("--symbols", required=True)
    minute = commands.add_parser("sync-recent-minute-bars")
    minute.add_argument("--symbols", required=True)
    for command in (bars, csv_import, daily, minute):
        command.add_argument("--timeframe", type=MarketTimeframe, default=MarketTimeframe.DAY_1)
        command.add_argument("--adjustment", type=AdjustmentType, default=AdjustmentType.NONE)
        command.add_argument("--start", type=aware_datetime, required=True)
        command.add_argument("--end", type=aware_datetime, required=True)
    status = commands.add_parser("sync-status")
    status.add_argument("--limit", type=int, default=20, choices=range(1, 101))
    return parser


def fail(message: str) -> NoReturn:
    print(json.dumps({"status": "error", "error": message}, ensure_ascii=False))
    raise SystemExit(2)


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(execute(args, get_settings()))
    except (OSError, RuntimeError, ValueError) as exc:
        fail(str(exc))
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
