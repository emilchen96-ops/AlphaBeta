"""Safe local market-data maintenance commands for M03."""

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import NoReturn, cast
from uuid import UUID, uuid4

from alphadesk_api.application.catalog import InstrumentCatalogService
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.historical_market_data import (
    HistoricalMarketDataBackfillService,
    InstrumentUniverseSyncService,
)
from alphadesk_api.application.market_data import (
    MarketDataIngestionService,
    MarketDataQueryService,
)
from alphadesk_api.application.market_data_operations import (
    DailyMarketDataUpdateService,
    MarketDataQualityIntegrityService,
    MarketDataQualityQueryService,
    MarketDataQualityService,
    MarketDataReadinessService,
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
from alphadesk_domain.market import InstrumentMapping, MarketSyncRun
from alphadesk_domain.market_adapters import MarketDataAdapter, MarketDataAdapterError


def aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include a UTC offset")
    return parsed.astimezone(UTC)


def date_or_datetime(value: str) -> datetime:
    try:
        return datetime.combine(date.fromisoformat(value), datetime.min.time(), tzinfo=UTC)
    except ValueError:
        return aware_datetime(value)


def daily_timeframe(value: str) -> MarketTimeframe:
    normalized = "DAY_1" if value.upper() == "DAY" else value.upper()
    if normalized != MarketTimeframe.DAY_1.value:
        raise argparse.ArgumentTypeError("timeframe must be DAY or DAY_1")
    return MarketTimeframe.DAY_1


def read_symbol_file(path_value: str | None) -> set[str] | None:
    if path_value is None:
        return None
    path = Path(path_value)
    if not path.is_file():
        raise ValueError("codes file does not exist")
    if path.stat().st_size > 1_000_000:
        raise ValueError("codes file exceeds 1 MB")
    values = {
        item.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        for item in line.replace(",", " ").split()
        if item.strip()
    }
    if not values or len(values) > 10_000:
        raise ValueError("codes file must contain 1 to 10000 symbols")
    return values


def serialize_sync_run(run: MarketSyncRun) -> dict[str, object]:
    values = asdict(run)
    return {key: value.value if hasattr(value, "value") else value for key, value in values.items()}


def report_backfill_progress(current: int, total: int, symbol: str, state: str) -> None:
    print(
        json.dumps(
            {"progress": {"current": current, "total": total, "symbol": symbol, "state": state}},
            ensure_ascii=False,
        ),
        file=sys.stderr,
        flush=True,
    )


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
    universes = InstrumentUniverseSyncService(uow_factory)
    historical = HistoricalMarketDataBackfillService(
        uow_factory,
        future_tolerance_seconds=settings.market_future_tolerance_seconds,
    )
    daily_updates = DailyMarketDataUpdateService(
        uow_factory,
        default_start_date=settings.market_daily_default_start_date,
        max_instruments=settings.market_backfill_max_instruments,
        batch_size=settings.market_backfill_batch_size,
        max_retries=settings.market_backfill_max_retries,
        request_interval_seconds=settings.market_backfill_request_interval_seconds,
        future_tolerance_seconds=settings.market_future_tolerance_seconds,
    )
    readiness = MarketDataReadinessService(
        uow_factory, backtest_minimum_bars=settings.market_data_backtest_minimum_bars
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
            source_code = (args.provider or args.source).upper()
            selected_adapter = adapter_for(source_code)
            if selected_adapter.source_code == "BAOSTOCK":
                instrument_sync_result = await universes.sync_instruments(
                    adapter=selected_adapter,
                    correlation_id=uuid4(),
                    limit=args.limit,
                    symbols=read_symbol_file(args.codes_file),
                    dry_run=args.dry_run,
                )
                return asdict(instrument_sync_result)
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
        if args.command == "create-research-universe":
            universe_result = await universes.create_research_universe(
                correlation_id=uuid4(),
                limit=args.limit,
                symbols=read_symbol_file(args.codes_file),
                dry_run=args.dry_run,
            )
            return {
                "name": universe_result.name,
                "instrument_count": len(universe_result.instrument_ids),
                "symbols_preview": list(universe_result.symbols[:20]),
                "created": universe_result.created,
                "dry_run": universe_result.dry_run,
            }
        if args.command == "backfill":
            selected_adapter = adapter_for(args.provider)
            if args.limit > settings.market_backfill_max_instruments:
                raise ApplicationError(
                    "D01_BACKFILL_INSTRUMENT_LIMIT",
                    f"单次补数最多 {settings.market_backfill_max_instruments} 个标的",
                )
            selected_instruments = await universes.resolve_universe(
                universe=args.universe,
                limit=args.limit,
                instrument_ids=args.instrument_id,
                symbols=read_symbol_file(args.codes_file),
            )
            backfill_result = await historical.backfill(
                adapter=selected_adapter,
                instruments=selected_instruments,
                universe=args.universe,
                timeframe=args.timeframe,
                start=args.start,
                end=args.end or datetime.now(UTC),
                batch_size=args.batch_size or settings.market_backfill_batch_size,
                continue_on_error=args.continue_on_error,
                correlation_id=uuid4(),
                max_retries=(
                    settings.market_backfill_max_retries
                    if args.max_retries is None
                    else args.max_retries
                ),
                request_interval_seconds=(
                    settings.market_backfill_request_interval_seconds
                    if args.request_interval_ms is None
                    else args.request_interval_ms / 1000
                ),
                dry_run=args.dry_run,
                progress=None if args.dry_run else report_backfill_progress,
            )
            return {
                **asdict(backfill_result),
                "run": (
                    None if backfill_result.run is None else serialize_sync_run(backfill_result.run)
                ),
            }
        if args.command == "update-daily":
            selected_instruments = await universes.resolve_universe(
                universe=args.universe,
                limit=args.max_instruments,
                instrument_ids=args.instrument_id,
                symbols=read_symbol_file(args.codes_file),
            )
            daily_result = await daily_updates.update(
                adapter=adapter_for(args.provider),
                instruments=selected_instruments,
                universe_key=args.universe,
                target_date=args.target_date,
                continue_on_error=args.continue_on_error,
                dry_run=args.dry_run,
                correlation_id=uuid4(),
                progress=None if args.dry_run else report_backfill_progress,
            )
            return {
                **asdict(daily_result),
                "run": (None if daily_result.run is None else serialize_sync_run(daily_result.run)),
            }
        if args.command == "verify-quality":
            selected_instruments = await universes.resolve_universe(
                universe=args.universe,
                limit=args.max_instruments,
            )
            quality_result = await MarketDataQualityService(
                uow_factory,
                stale_calendar_days=settings.market_data_stale_calendar_days,
                minimum_bars=settings.market_data_backtest_minimum_bars,
            ).verify(
                instruments=selected_instruments,
                universe_key=args.universe,
                provider=args.provider,
                correlation_id=uuid4(),
            )
            integrity = await MarketDataQualityIntegrityService(uow_factory).verify(
                quality_result.run.id
            )
            return {
                "run": asdict(quality_result.run),
                "issue_type_counts": dict(
                    Counter(item.issue_type for item in quality_result.issues)
                ),
                "integrity_mismatches": integrity,
            }
        if args.command == "show-readiness":
            selected_instruments = await universes.resolve_universe(
                universe=args.universe,
                limit=args.max_instruments,
            )
            readiness_values = await readiness.readiness(
                instruments=selected_instruments, provider=args.provider
            )
            return {"capabilities": [asdict(item) for item in readiness_values]}
        if args.command == "show-quality-run":
            query = MarketDataQualityQueryService(uow_factory)
            quality_run = await query.run(args.run_id)
            issues, total = await query.issues(args.run_id, page=1, page_size=args.issue_limit)
            integrity = await MarketDataQualityIntegrityService(uow_factory).verify(args.run_id)
            return {
                "run": asdict(quality_run),
                "issues": [asdict(item) for item in issues],
                "issue_total": total,
                "integrity_mismatches": integrity,
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
            ingestion_run = await ingestion.sync_bars(
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
                                "run_id": str(ingestion_run.id),
                                "completed_at": (
                                    None
                                    if ingestion_run.completed_at is None
                                    else ingestion_run.completed_at.isoformat()
                                ),
                            }
                        ),
                    )
                finally:
                    await redis_service.close()
            return {
                "run_id": str(ingestion_run.id),
                "status": ingestion_run.status.value,
                "received": ingestion_run.total_received,
                "inserted": ingestion_run.total_inserted,
                "updated": ingestion_run.total_updated,
                "rejected": ingestion_run.total_rejected,
            }
        if args.command in {"sync-status", "list-sync-runs"}:
            sync_runs = await MarketDataQueryService(uow_factory).sync_runs(args.limit)
            return {"runs": [serialize_sync_run(item) for item in sync_runs]}
        if args.command == "show-sync-run":
            sync_run = await MarketDataQueryService(uow_factory).sync_run(args.run_id)
            return {"run": serialize_sync_run(sync_run)}
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
    instruments.add_argument("--provider")
    instruments.add_argument("--limit", type=int)
    instruments.add_argument("--codes-file")
    instruments.add_argument("--dry-run", action="store_true")
    research = commands.add_parser("create-research-universe")
    research.add_argument("--limit", type=int, default=300)
    research.add_argument("--codes-file")
    research.add_argument("--dry-run", action="store_true")
    backfill = commands.add_parser("backfill")
    backfill.add_argument("--provider", default="baostock")
    backfill.add_argument(
        "--universe",
        choices=("research", "manual", "all_active_a_share"),
        default="research",
    )
    backfill.add_argument("--instrument-id", action="append", type=UUID)
    backfill.add_argument("--codes-file")
    backfill.add_argument("--limit", type=int, default=300)
    backfill.add_argument("--timeframe", type=daily_timeframe, default=MarketTimeframe.DAY_1)
    backfill.add_argument("--start", type=date_or_datetime, required=True)
    backfill.add_argument("--end", type=date_or_datetime)
    backfill.add_argument("--batch-size", type=int)
    backfill.add_argument(
        "--continue-on-error", action=argparse.BooleanOptionalAction, default=True
    )
    backfill.add_argument("--max-retries", type=int)
    backfill.add_argument("--request-interval-ms", type=int)
    backfill.add_argument("--dry-run", action="store_true")
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
    list_runs = commands.add_parser("list-sync-runs")
    list_runs.add_argument("--limit", type=int, default=20, choices=range(1, 101))
    show_run = commands.add_parser("show-sync-run")
    show_run.add_argument("--run-id", type=UUID, required=True)
    update_daily = commands.add_parser("update-daily")
    update_daily.add_argument("--provider", default="baostock")
    update_daily.add_argument(
        "--universe", choices=("research", "manual", "all_active_a_share"), default="research"
    )
    update_daily.add_argument("--instrument-id", action="append", type=UUID)
    update_daily.add_argument("--codes-file")
    update_daily.add_argument("--target-date", type=date.fromisoformat)
    update_daily.add_argument("--max-instruments", type=int, default=300, choices=range(1, 501))
    update_daily.add_argument(
        "--continue-on-error", action=argparse.BooleanOptionalAction, default=True
    )
    update_daily.add_argument("--dry-run", action="store_true")
    verify_quality = commands.add_parser("verify-quality")
    verify_quality.add_argument("--provider", default="baostock")
    verify_quality.add_argument(
        "--universe", choices=("research", "all_active_a_share"), default="research"
    )
    verify_quality.add_argument("--timeframe", type=daily_timeframe, default=MarketTimeframe.DAY_1)
    verify_quality.add_argument("--max-instruments", type=int, default=300, choices=range(1, 501))
    show_readiness = commands.add_parser("show-readiness")
    show_readiness.add_argument("--provider", default="baostock")
    show_readiness.add_argument(
        "--universe", choices=("research", "all_active_a_share"), default="research"
    )
    show_readiness.add_argument("--max-instruments", type=int, default=300, choices=range(1, 501))
    show_quality = commands.add_parser("show-quality-run")
    show_quality.add_argument("--run-id", type=UUID, required=True)
    show_quality.add_argument("--issue-limit", type=int, default=100, choices=range(1, 201))
    return parser


def fail(message: str, code: str = "MARKET_DATA_COMMAND_FAILED") -> NoReturn:
    print(
        json.dumps(
            {"status": "error", "error": {"code": code, "message": message}}, ensure_ascii=False
        )
    )
    raise SystemExit(2)


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(execute(args, get_settings()))
    except ApplicationError as exc:
        fail(exc.message, exc.code)
    except MarketDataAdapterError as exc:
        fail(str(exc), "MARKET_PROVIDER_ERROR")
    except (OSError, RuntimeError, ValueError) as exc:
        fail(str(exc))
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
