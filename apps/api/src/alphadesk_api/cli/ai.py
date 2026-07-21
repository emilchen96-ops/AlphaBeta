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
from alphadesk_api.infrastructure.ai_research_provider import (
    OpenAICompatibleResearchProvider,
    build_ai_research_provider,
    describe_ai_provider,
    test_ai_provider,
)
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.ai_research import (
    AIAnalysisStatus,
    AIAnalysisType,
    AIResearchProvider,
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
    return build_ai_research_provider(settings)


async def execute(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    database = DatabaseService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    provider = selected_provider(settings)
    try:
        if args.command == "provider-status":
            return {"provider": describe_ai_provider(provider)}
        if args.command == "test-provider":
            result = await test_ai_provider(provider)
            if not result.success:
                raise ApplicationError(
                    result.error_code or "AI_PROVIDER_UNAVAILABLE",
                    "AI provider connectivity test failed",
                )
            return {"provider_test": result}
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
            if analysis_outcome.run.status is AIAnalysisStatus.FAILED:
                raise ApplicationError(
                    analysis_outcome.run.error_code or "AI_ANALYSIS_FAILED",
                    analysis_outcome.run.error_message or "AI analysis failed",
                )
            return {
                "analysis_id": analysis_outcome.run.id,
                "status": analysis_outcome.run.status,
                "provider_key": analysis_outcome.run.provider_key,
                "model_name": analysis_outcome.run.model_name,
                "replayed": analysis_outcome.replayed,
                "summary": (
                    None
                    if analysis_outcome.insight is None
                    else analysis_outcome.insight.summary[:1000]
                ),
                "input_token_count": analysis_outcome.run.input_token_count,
                "output_token_count": analysis_outcome.run.output_token_count,
                "total_token_count": analysis_outcome.run.total_token_count,
                "estimated_cost": analysis_outcome.run.estimated_cost,
                "cost_currency": (
                    "USD" if analysis_outcome.run.estimated_cost is not None else None
                ),
            }
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
        if isinstance(provider, OpenAICompatibleResearchProvider):
            await provider.close()
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-ai")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("provider-status")
    commands.add_parser("test-provider")
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


def fail(message: str, *, code: str = "CLI_ERROR") -> NoReturn:
    print(
        json.dumps(
            {"status": "error", "error": {"code": code, "message": message}},
            ensure_ascii=False,
        )
    )
    raise SystemExit(2)


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(execute(args, get_settings()))
    except ApplicationError as exc:
        fail(exc.message, code=exc.code)
    except (OSError, RuntimeError, ValueError) as exc:
        fail(str(exc))
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, default=_json))


if __name__ == "__main__":
    main()
