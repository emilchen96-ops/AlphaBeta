"""Local N01 information-center maintenance commands."""

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, NoReturn, cast
from uuid import UUID, uuid4

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.information import (
    InformationIngestionService,
    InformationIntegrityService,
    InformationQueryService,
    ManualInformationRequest,
    ThemeInput,
)
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_domain.information import (
    InformationSourceType,
    MarketEventDirection,
    MarketEventType,
)


def aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include a UTC offset")
    return parsed.astimezone(UTC)


def theme(value: str) -> ThemeInput:
    if "=" not in value:
        raise argparse.ArgumentTypeError("theme must use key=name")
    key, name = value.split("=", 1)
    return ThemeInput(theme_key=key, theme_name=name)


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


async def execute(args: argparse.Namespace, settings: Settings) -> dict[str, object]:
    database = DatabaseService(settings)
    factory = cast(UnitOfWorkFactory, database.unit_of_work)
    ingestion = InformationIngestionService(factory)
    try:
        if args.command == "add-manual":
            outcome = await ingestion.add_manual(
                ManualInformationRequest(
                    source_name=args.source_name,
                    title=args.title,
                    content=args.content,
                    source_url=args.source_url,
                    published_at=args.published_at,
                    instrument_ids=tuple(args.instrument_id),
                    themes=tuple(args.theme),
                    event_type=MarketEventType(args.event_type),
                    direction=MarketEventDirection(args.direction),
                    summary=args.summary,
                    importance=args.importance,
                    correlation_id=uuid4(),
                )
            )
            return {"outcome": outcome}
        if args.command == "ingest-rss":
            source = await ingestion.ensure_source(
                display_name=args.source_name,
                source_type=InformationSourceType.RSS,
                base_url=args.url,
            )
            run = await ingestion.ingest_source(source.id, uuid4())
            return {"source": source, "run": run}
        query = InformationQueryService(factory)
        if args.command == "list":
            items, total = await query.items(
                search=args.search,
                source_id=None,
                instrument_id=args.instrument_id,
                theme_key=args.theme_key,
                offset=0,
                limit=args.limit,
            )
            return {"items": items, "total": total}
        if args.command == "verify-integrity":
            issues = await InformationIntegrityService(factory).verify_item(args.item_id)
            return {"item_id": args.item_id, "valid": not issues, "issues": issues}
        raise ValueError("unknown command")
    finally:
        await database.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadesk-information")
    commands = parser.add_subparsers(dest="command", required=True)
    manual = commands.add_parser("add-manual")
    manual.add_argument("--source-name", required=True)
    manual.add_argument("--title", required=True)
    manual.add_argument("--content", required=True)
    manual.add_argument("--source-url")
    manual.add_argument("--published-at", type=aware_datetime)
    manual.add_argument("--instrument-id", action="append", type=UUID, default=[])
    manual.add_argument("--theme", action="append", type=theme, default=[])
    manual.add_argument(
        "--event-type", choices=[item.value for item in MarketEventType], default="OTHER"
    )
    manual.add_argument(
        "--direction", choices=[item.value for item in MarketEventDirection], default="UNKNOWN"
    )
    manual.add_argument("--summary")
    manual.add_argument("--importance", type=Decimal)
    rss = commands.add_parser("ingest-rss")
    rss.add_argument("--source-name", required=True)
    rss.add_argument("--url", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--search")
    listing.add_argument("--instrument-id", type=UUID)
    listing.add_argument("--theme-key")
    listing.add_argument("--limit", type=int, choices=range(1, 101), default=20)
    verify = commands.add_parser("verify-integrity")
    verify.add_argument("--item-id", type=UUID, required=True)
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
