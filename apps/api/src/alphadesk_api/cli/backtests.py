"""Development/test CLI for BT01 local daily backtests."""

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from alphadesk_api.application.backtests import (
    BacktestIntegrityService,
    BacktestQueryService,
    BacktestService,
    CreateBacktestRequest,
)
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.strategies import StrategyResearchService
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.backtest import BacktestExecutionPriceMode
from alphadesk_domain.broker import AshareSimpleFeeModel, FixedBasisPointsSlippageModel
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import (
    AdjustmentType,
    MarketDataQualityStatus,
    MarketDataSourceStatus,
    MarketProviderTier,
    MarketTimeframe,
    OrderType,
    TimeInForce,
)
from alphadesk_domain.market import MarketBar, MarketDataSource
from alphadesk_domain.strategy import StrategyBar, StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies


def _json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(cast(Any, value))
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _parameters(values: list[str]) -> dict[str, str | int | bool]:
    result: dict[str, str | int | bool] = {}
    for item in values:
        name, separator, raw = item.partition("=")
        if not separator or not name.strip():
            raise ValueError("--parameter must use name=value")
        if raw.lower() in ("true", "false"):
            result[name] = raw.lower() == "true"
        else:
            try:
                result[name] = int(raw)
            except ValueError:
                result[name] = raw
    return result


async def _run(
    factory: UnitOfWorkFactory,
    registry: StrategyRegistry,
    settings: Settings,
    *,
    strategy_key: str,
    instrument_ids: tuple[UUID, ...],
    start_at: datetime,
    end_at: datetime,
    initial_cash: Decimal,
    raw_parameters: dict[str, str | int | bool],
    idempotency_key: str,
    data_source_code: str | None = None,
) -> dict[str, object]:
    parameter_service = StrategyResearchService(factory, registry)
    result = await BacktestService(factory, registry, settings).run(
        CreateBacktestRequest(
            strategy_key=strategy_key,
            parameters=parameter_service.parameters(strategy_key, raw_parameters),
            instrument_ids=instrument_ids,
            timeframe=MarketTimeframe.DAY_1,
            start_at=start_at,
            end_at=end_at,
            initial_cash=initial_cash,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            execution_price_mode=BacktestExecutionPriceMode.SIGNAL_CLOSE_LIMIT,
            maximum_entry_gap_ratio=None,
            fee_configuration=AshareSimpleFeeModel(),
            slippage_configuration=FixedBasisPointsSlippageModel(basis_points=Decimal("2")),
            maximum_volume_participation=Decimal("0.1"),
            benchmark_symbol=None,
            data_source_code=data_source_code,
            idempotency_key=idempotency_key,
            correlation_id=uuid4(),
        )
    )
    return {
        "run": BacktestQueryService._run_view(result.run),
        "metrics": None if result.metrics is None else asdict(result.metrics),
        "replayed": result.replayed,
    }


async def _run_demo(
    factory: UnitOfWorkFactory, registry: StrategyRegistry, settings: Settings
) -> dict[str, object]:
    if settings.environment not in ("development", "test"):
        raise ValueError("BT01 demo is restricted to development/test")
    selected, selected_bars = await _ensure_demo_history(factory)
    start_at = selected_bars[0].timestamp
    end_at = selected_bars[-1].timestamp + timedelta(days=2)
    result = await _run(
        factory,
        registry,
        settings,
        strategy_key="sma_crossover",
        instrument_ids=(selected.id,),
        start_at=start_at,
        end_at=end_at,
        initial_cash=Decimal("100000"),
        raw_parameters={"short_window": 2, "long_window": 3, "quantity": "100"},
        idempotency_key="bt01-deterministic-demo-v1",
        data_source_code="BT01_DEMO",
    )
    run_view = cast(dict[str, object], result["run"])
    run_id = cast(UUID, run_view["id"])
    query = BacktestQueryService(factory)
    result["demo_data"] = True
    result["signals"] = len(await query.signals(run_id))
    result["orders"] = len(await query.orders(run_id))
    result["fills"] = len(await query.fills(run_id))
    result["integrity"] = asdict(await BacktestIntegrityService(factory).verify(run_id))
    return result


async def _ensure_demo_history(
    factory: UnitOfWorkFactory,
) -> tuple[Instrument, list[StrategyBar]]:
    """Idempotently seed an explicitly labelled, deterministic local-only demo."""

    start = datetime(2024, 1, 2, tzinfo=UTC)
    dates = (0, 1, 2, 3, 4, 7, 8, 9, 10)
    closes = tuple(Decimal(value) for value in ("10", "10", "10", "12", "13", "12", "9", "8", "9"))
    opens = tuple(Decimal(value) for value in ("10", "10", "10", "10", "12", "13", "12", "9", "8"))
    async with factory() as uow:
        source = await uow.market_data_sources.get_by_code("BT01_DEMO")
        if source is None:
            source = MarketDataSource(
                source_code="BT01_DEMO",
                name="BT01 deterministic local demo",
                status=MarketDataSourceStatus.ACTIVE,
                priority=999,
                supports_realtime=False,
                supported_timeframes=(MarketTimeframe.DAY_1,),
                provider_tier=MarketProviderTier.DEMO,
                metadata={"scope": "BT01_DEMO", "network_access": False},
            )
            await uow.market_data_sources.add(source)
        instrument = await uow.instruments.get_by_business_key("BT01", "DEMO001")
        if instrument is None:
            instrument = Instrument(
                symbol="DEMO001",
                exchange="BT01",
                market="CN_DEMO",
                name="BT01 deterministic demo instrument",
                asset_type="STOCK",
                currency="CNY",
                lot_size=Decimal("100"),
                price_tick=Decimal("0.01"),
                timezone="Asia/Shanghai",
                metadata={"scope": "BT01_DEMO", "not_real_market_data": True},
            )
            await uow.instruments.add(instrument)
        bars = [
            MarketBar(
                instrument_id=instrument.id,
                source_id=source.id,
                timeframe=MarketTimeframe.DAY_1,
                adjustment_type=AdjustmentType.NONE,
                bar_time=start + timedelta(days=offset),
                open=open_price,
                high=max(open_price, close) + Decimal("1"),
                low=min(open_price, close) - Decimal("1"),
                close=close,
                volume=Decimal("100000"),
                received_at=start + timedelta(days=offset, hours=16),
                quality_status=MarketDataQualityStatus.NORMAL,
                quality_flags={"scope": "BT01_DEMO", "deterministic": True},
            )
            for offset, open_price, close in zip(dates, opens, closes, strict=True)
        ]
        await uow.market_bars.upsert_many(bars)
        await uow.commit()
        selected_bars = await uow.historical_bars.list_bars(
            instrument_ids=(instrument.id,),
            timeframe=MarketTimeframe.DAY_1,
            start_at=start,
            end_at=start + timedelta(days=12),
        )
    return instrument, selected_bars


async def execute(args: argparse.Namespace, settings: Settings) -> object:
    if settings.environment not in ("development", "test"):
        raise ValueError("BT01 CLI is restricted to development/test")
    database = DatabaseService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    query = BacktestQueryService(factory)
    try:
        if args.command == "run":
            return await _run(
                factory,
                registry,
                settings,
                strategy_key=args.strategy_key,
                instrument_ids=tuple(args.instrument),
                start_at=args.start,
                end_at=args.end,
                initial_cash=args.initial_cash,
                raw_parameters=_parameters(args.parameter),
                idempotency_key=args.idempotency_key,
            )
        if args.command == "run-demo":
            return await _run_demo(factory, registry, settings)
        if args.command == "list":
            return await query.list(page=1, page_size=args.limit, status=None)
        if args.command == "show":
            return await query.detail(args.backtest_id)
        if args.command == "metrics":
            return asdict(await query.metrics(args.backtest_id))
        if args.command == "verify-integrity":
            return asdict(await BacktestIntegrityService(factory).verify(args.backtest_id))
        raise ValueError("unsupported command")
    finally:
        await database.close()


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AlphaDesk BT01 daily backtests")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--strategy-key", required=True)
    run.add_argument("--instrument", type=UUID, action="append", required=True)
    run.add_argument("--start", type=_date, required=True)
    run.add_argument("--end", type=_date, required=True)
    run.add_argument("--initial-cash", type=Decimal, required=True)
    run.add_argument("--parameter", action="append", default=[])
    run.add_argument("--idempotency-key", required=True)
    list_command = commands.add_parser("list")
    list_command.add_argument("--limit", type=int, default=20)
    for name in ("show", "metrics", "verify-integrity"):
        command = commands.add_parser(name)
        command.add_argument("--backtest-id", type=UUID, required=True)
    commands.add_parser("run-demo")
    return parser


def main() -> NoReturn:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = asyncio.run(execute(args, get_settings()))
    except (ApplicationError, ValueError) as exc:
        parser.exit(1, f"BT01 failed: {exc}\n")
    print(json.dumps(result, default=_json, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(0)


if __name__ == "__main__":
    main()
