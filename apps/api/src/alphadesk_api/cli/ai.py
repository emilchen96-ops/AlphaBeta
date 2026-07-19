"""Local A01 grounded AI-research commands."""

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from alphadesk_api.application.ai_research import (
    AIResearchAnalysisService,
    AIResearchIntegrityService,
    AIResearchQueryService,
    AnalysisRequest,
)
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.ai_research import (
    AIAnalysisType,
    AIResearchProvider,
    DisabledAIResearchProvider,
    FakeAIResearchProvider,
)


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


def selected_provider(settings: Settings) -> AIResearchProvider:
    if settings.ai_research_provider == "fake":
        return FakeAIResearchProvider()
    return DisabledAIResearchProvider()


async def execute(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    database = DatabaseService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    try:
        provider = selected_provider(settings)
        if args.command == "provider-status":
            return {
                "provider_key": provider.provider_key,
                "model_name": provider.model_name,
                "configured": provider.configured,
                "real_provider_available": False,
            }
        if args.command == "analyze":
            analysis_outcome = await AIResearchAnalysisService(factory, provider).analyze(
                AnalysisRequest(
                    analysis_type=AIAnalysisType(args.analysis_type),
                    event_ids=tuple(args.event_id),
                    information_item_ids=tuple(args.information_item_id),
                    instrument_ids=tuple(args.instrument_id),
                    question=args.question,
                    idempotency_key=args.idempotency_key,
                    correlation_id=uuid4(),
                )
            )
            return {"outcome": analysis_outcome}
        query = AIResearchQueryService(factory)
        if args.command == "list":
            runs, total = await query.runs(
                analysis_type=args.analysis_type,
                status=args.status,
                offset=0,
                limit=args.limit,
            )
            return {"runs": runs, "total": total}
        if args.command == "show":
            found = await query.run(args.analysis_id)
            if found is None:
                raise ApplicationError("AI_ANALYSIS_RUN_NOT_FOUND", "analysis not found")
            return {"outcome": found}
        if args.command == "verify-integrity":
            issues = await AIResearchIntegrityService(factory).verify(args.analysis_id)
            return {"analysis_id": args.analysis_id, "valid": not issues, "issues": issues}
        raise ValueError("unknown command")
    finally:
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-ai")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("provider-status")
    analyze = commands.add_parser("analyze")
    analyze.add_argument(
        "--analysis-type",
        choices=[item.value for item in AIAnalysisType],
        required=True,
    )
    analyze.add_argument("--event-id", action="append", type=UUID, default=[])
    analyze.add_argument("--information-item-id", action="append", type=UUID, default=[])
    analyze.add_argument("--instrument-id", action="append", type=UUID, default=[])
    analyze.add_argument("--question")
    analyze.add_argument("--idempotency-key", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--analysis-type", choices=[item.value for item in AIAnalysisType])
    listing.add_argument("--status", choices=["CREATED", "RUNNING", "COMPLETED", "FAILED"])
    listing.add_argument("--limit", type=int, choices=range(1, 101), default=20)
    show = commands.add_parser("show")
    show.add_argument("--analysis-id", type=UUID, required=True)
    verify = commands.add_parser("verify-integrity")
    verify.add_argument("--analysis-id", type=UUID, required=True)
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
