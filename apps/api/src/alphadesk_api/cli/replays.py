"""Development/test CLI for RT01 historical daily replays."""

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.replays import (
    CreateReplayRequest,
    ReplayControlRequest,
    ReplayIntegrityService,
    ReplayQueryService,
    ReplayService,
)
from alphadesk_api.application.strategies import StrategyResearchService
from alphadesk_api.cli.backtests import _ensure_demo_history, _parameters
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.broker import AshareSimpleFeeModel, FixedBasisPointsSlippageModel
from alphadesk_domain.enums import OrderType, TimeInForce
from alphadesk_domain.replay import ReplayControlActionType, ReplaySpeedMode
from alphadesk_domain.strategy import StrategyRegistry
from alphadesk_domain.strategy_examples import register_builtin_strategies


def _json(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(cast(Any, value))
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


async def _create(
    factory: UnitOfWorkFactory,
    registry: StrategyRegistry,
    settings: Settings,
    args: argparse.Namespace,
    *,
    data_source_code: str | None = None,
) -> dict[str, object]:
    parameters = StrategyResearchService(factory, registry).parameters(
        args.strategy_key, _parameters(args.parameter)
    )
    result = await ReplayService(factory, registry, settings).create(
        CreateReplayRequest(
            strategy_key=args.strategy_key,
            parameters=parameters,
            instrument_ids=tuple(args.instrument),
            start_at=args.start,
            end_at=args.end,
            initial_cash=args.initial_cash,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            fee_configuration=AshareSimpleFeeModel(),
            slippage_configuration=FixedBasisPointsSlippageModel(basis_points=Decimal("2")),
            maximum_volume_participation=Decimal("0.1"),
            speed_mode=ReplaySpeedMode(args.speed),
            idempotency_key=args.idempotency_key,
            data_source_code=data_source_code,
            correlation_id=uuid4(),
        )
    )
    detail = await ReplayQueryService(factory).detail(result.run.id)
    detail["replayed"] = result.replayed
    return detail


async def _control(
    factory: UnitOfWorkFactory,
    registry: StrategyRegistry,
    settings: Settings,
    args: argparse.Namespace,
    action: ReplayControlActionType,
) -> dict[str, object]:
    run = await ReplayService(factory, registry, settings).control(
        ReplayControlRequest(
            replay_run_id=args.replay_id,
            action_type=action,
            idempotency_key=args.idempotency_key,
            expected_run_version=args.expected_run_version,
            requested_speed=(
                ReplaySpeedMode(args.speed) if action is ReplayControlActionType.SET_SPEED else None
            ),
        )
    )
    return await ReplayQueryService(factory).detail(run.id)


async def _run_demo(
    factory: UnitOfWorkFactory, registry: StrategyRegistry, settings: Settings
) -> dict[str, object]:
    instrument, bars = await _ensure_demo_history(factory)
    args = argparse.Namespace(
        strategy_key="sma_crossover",
        parameter=["short_window=2", "long_window=3", "quantity=100.0"],
        instrument=[instrument.id],
        start=bars[0].timestamp,
        end=bars[-1].timestamp + timedelta(days=2),
        initial_cash=Decimal("100000"),
        speed="MANUAL",
        idempotency_key="rt01-deterministic-demo-v4",
    )
    created = await _create(factory, registry, settings, args, data_source_code="BT01_DEMO")
    replay_id = UUID(str(created["id"]))
    query = ReplayQueryService(factory)
    run = await query.require(replay_id)
    while run.current_session_index < run.total_sessions:
        await ReplayService(factory, registry, settings).control(
            ReplayControlRequest(
                replay_run_id=replay_id,
                action_type=ReplayControlActionType.STEP,
                idempotency_key=f"rt01-demo-step-{run.current_session_index}",
                expected_run_version=run.row_version,
            )
        )
        run = await query.require(replay_id)
    return {
        "run": await query.detail(replay_id),
        "signals": len(await query.signals(replay_id)),
        "orders": len(await query.orders(replay_id)),
        "fills": len(await query.fills(replay_id)),
        "integrity": asdict(await ReplayIntegrityService(factory).verify(replay_id)),
        "network_access": False,
        "real_trading": False,
    }


async def execute(args: argparse.Namespace, settings: Settings) -> object:
    if settings.environment not in ("development", "test"):
        raise ValueError("RT01 CLI is restricted to development/test")
    database = DatabaseService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    registry = StrategyRegistry()
    register_builtin_strategies(registry)
    query = ReplayQueryService(factory)
    try:
        if args.command == "create":
            return await _create(factory, registry, settings, args)
        if args.command == "list":
            return await query.list(page=1, page_size=args.limit, status=None)
        if args.command == "show":
            return await query.detail(args.replay_id)
        if args.command == "verify-integrity":
            return asdict(await ReplayIntegrityService(factory).verify(args.replay_id))
        if args.command == "run-demo":
            return await _run_demo(factory, registry, settings)
        actions = {
            "start": ReplayControlActionType.START,
            "pause": ReplayControlActionType.PAUSE,
            "resume": ReplayControlActionType.RESUME,
            "step": ReplayControlActionType.STEP,
            "set-speed": ReplayControlActionType.SET_SPEED,
            "stop": ReplayControlActionType.STOP,
        }
        if args.command in actions:
            return await _control(factory, registry, settings, args, actions[args.command])
        raise ValueError("unsupported command")
    finally:
        await database.close()


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AlphaDesk RT01 historical daily replay")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--strategy-key", required=True)
    create.add_argument("--instrument", type=UUID, action="append", required=True)
    create.add_argument("--start", type=_date, required=True)
    create.add_argument("--end", type=_date, required=True)
    create.add_argument("--initial-cash", type=Decimal, required=True)
    create.add_argument("--parameter", action="append", default=[])
    create.add_argument(
        "--speed", choices=[item.value for item in ReplaySpeedMode], default="MANUAL"
    )
    create.add_argument("--idempotency-key", required=True)
    list_command = commands.add_parser("list")
    list_command.add_argument("--limit", type=int, default=20)
    show = commands.add_parser("show")
    show.add_argument("--replay-id", type=UUID, required=True)
    verify = commands.add_parser("verify-integrity")
    verify.add_argument("--replay-id", type=UUID, required=True)
    commands.add_parser("run-demo")
    for name in ("start", "pause", "resume", "step", "set-speed", "stop"):
        command = commands.add_parser(name)
        command.add_argument("--replay-id", type=UUID, required=True)
        command.add_argument("--idempotency-key", required=True)
        command.add_argument("--expected-run-version", type=int, required=True)
        if name == "set-speed":
            command.add_argument(
                "--speed", choices=[item.value for item in ReplaySpeedMode], required=True
            )
    return parser


def main() -> NoReturn:
    parser = build_parser()
    try:
        result = asyncio.run(execute(parser.parse_args(), get_settings()))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=_json))
    except Exception as exc:
        parser.exit(1, f"RT01_ERROR: {exc}\n")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
