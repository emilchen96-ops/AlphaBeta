"""MiniQMT read-only market-data CLI.  No trading commands are registered."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

import httpx

from alphadesk_api.agents.miniqmt_market_data import MiniQMTReadOnlyAgent
from alphadesk_api.core.config import get_settings


def aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("时间必须包含时区")
    return parsed


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="AlphaDesk MiniQMT只读行情CLI")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("market-status")
    sub.add_parser("rebuild-subscriptions")
    sub.add_parser("sync-subscriptions")
    sub.add_parser("list-subscriptions")
    agent = sub.add_parser("run-agent")
    agent.add_argument("--once", action="store_true")
    backfill = sub.add_parser("backfill-history")
    backfill.add_argument("--instrument", action="append", required=True)
    backfill.add_argument("--timeframe", choices=["DAY_1", "MINUTE_1"], required=True)
    backfill.add_argument("--start", type=aware, required=True)
    backfill.add_argument("--end", type=aware, required=True)
    return root


def execute(args: argparse.Namespace) -> object:
    settings = get_settings()
    if args.command == "run-agent":
        MiniQMTReadOnlyAgent(settings).run(once=args.once)
        return {
            "status": "STOPPED",
            "market_data_capability": "ENABLED",
            "trading_capability": "DISABLED",
        }
    headers = {}
    if settings.miniqmt_agent_token is not None:
        headers["X-AlphaDesk-Agent-Token"] = settings.miniqmt_agent_token.get_secret_value()
    with httpx.Client(
        base_url=settings.miniqmt_agent_api_url.rstrip("/"),
        headers=headers,
        timeout=30,
    ) as client:
        if args.command == "market-status":
            response = client.get("/api/v1/miniqmt/market-data/status")
        elif args.command == "rebuild-subscriptions":
            response = client.post("/api/v1/market-subscriptions/rebuild")
        elif args.command == "sync-subscriptions":
            response = client.post("/api/v1/market-subscriptions/sync")
        elif args.command == "list-subscriptions":
            desired = client.get("/api/v1/market-subscriptions/desired")
            active = client.get("/api/v1/market-subscriptions/active")
            desired.raise_for_status()
            active.raise_for_status()
            return {"desired": desired.json()["data"], "active": active.json()["data"]}
        elif args.command == "backfill-history":
            response = client.post(
                "/api/v1/miniqmt/history/backfill",
                json={
                    "instrument_ids": args.instrument,
                    "timeframe": args.timeframe,
                    "start_at": args.start.isoformat(),
                    "end_at": args.end.isoformat(),
                },
            )
        else:
            raise ValueError("unsupported command")
        response.raise_for_status()
        return response.json()["data"]


def main() -> None:
    try:
        print(json.dumps(execute(parser().parse_args()), ensure_ascii=False, default=str))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        print(
            json.dumps(
                {"error": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
