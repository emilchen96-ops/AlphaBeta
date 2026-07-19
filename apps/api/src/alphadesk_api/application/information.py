"""N01 ingestion, event generation, queries and integrity checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_domain.entities import Instrument
from alphadesk_domain.information import (
    EventInstrumentLink,
    EventThemeLink,
    InformationError,
    InformationIngestionRun,
    InformationIngestionStatus,
    InformationItem,
    InformationSource,
    InformationSourceType,
    MarketEvent,
    MarketEventDirection,
    MarketEventType,
    RawDocument,
    RawDocumentDraft,
    normalize_text,
    normalized_content_hash,
)
from alphadesk_domain.information_adapters import (
    InformationSourceAdapter,
    ManualInformationAdapter,
    RSSInformationAdapter,
)
from alphadesk_domain.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True, kw_only=True)
class ThemeInput:
    theme_key: str
    theme_name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualInformationRequest:
    source_name: str
    title: str
    content: str
    source_url: str | None
    published_at: datetime | None
    instrument_ids: tuple[UUID, ...]
    themes: tuple[ThemeInput, ...]
    event_type: MarketEventType
    direction: MarketEventDirection
    summary: str | None
    importance: Decimal | None
    correlation_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class InformationOutcome:
    source: InformationSource
    raw_document: RawDocument
    item: InformationItem
    event: MarketEvent
    duplicate: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class InformationDetail:
    source: InformationSource
    raw_document: RawDocument
    item: InformationItem
    event: MarketEvent
    instruments: tuple[Instrument, ...]
    instrument_links: tuple[EventInstrumentLink, ...]
    theme_links: tuple[EventThemeLink, ...]


def _source_key(name: str, source_type: InformationSourceType) -> str:
    normalized = normalize_text(name, "source_name").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")[:48]
    suffix = sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{source_type.value.lower()}-{slug or suffix}-{suffix}"


class MarketEventService:
    @staticmethod
    def build(
        item: InformationItem,
        *,
        event_type: MarketEventType,
        direction: MarketEventDirection,
        summary: str | None,
        importance: Decimal | None,
    ) -> MarketEvent:
        return MarketEvent(
            information_item_id=item.id,
            event_type=event_type,
            title=item.normalized_title,
            summary=summary,
            event_at=item.published_at,
            direction=direction,
            importance=importance,
        )


class InformationIngestionService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        rss_adapter: InformationSourceAdapter | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._rss_adapter = rss_adapter or RSSInformationAdapter()

    async def ensure_source(
        self,
        *,
        display_name: str,
        source_type: InformationSourceType,
        base_url: str | None,
    ) -> InformationSource:
        key = _source_key(display_name, source_type)
        async with self._uow_factory() as uow:
            existing = await uow.information_sources.get_by_key(key)
            if existing is not None:
                if base_url is not None and existing.base_url != base_url:
                    existing.base_url = base_url
                    existing.updated_at = datetime.now(UTC)
                    await uow.information_sources.update(existing)
                    await uow.commit()
                return existing
            source = InformationSource(
                source_key=key,
                display_name=display_name,
                source_type=source_type,
                base_url=base_url,
            )
            await uow.information_sources.add(source)
            await uow.commit()
            return source

    async def add_manual(self, request: ManualInformationRequest) -> InformationOutcome:
        source = await self.ensure_source(
            display_name=request.source_name,
            source_type=InformationSourceType.MANUAL,
            base_url=None,
        )
        draft = ManualInformationAdapter().create(
            title=request.title,
            content=request.content,
            source_url=request.source_url,
            published_at=request.published_at,
        )
        return await self._ingest_draft(
            source,
            draft,
            instrument_ids=request.instrument_ids,
            themes=request.themes,
            event_type=request.event_type,
            direction=request.direction,
            summary=request.summary,
            importance=request.importance,
            ingestion_run_id=None,
        )

    async def ingest_source(self, source_id: UUID, correlation_id: UUID) -> InformationIngestionRun:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            source = await uow.information_sources.get_by_id(source_id)
            if source is None:
                raise ApplicationError("INFORMATION_SOURCE_NOT_FOUND", "source does not exist")
            if source.source_type is not InformationSourceType.RSS or not source.enabled:
                raise ApplicationError("INFORMATION_SOURCE_NOT_RSS", "source is not enabled RSS")
            run = InformationIngestionRun(
                source_id=source.id,
                status=InformationIngestionStatus.RUNNING,
                started_at=now,
                correlation_id=correlation_id,
            )
            await uow.information_ingestion_runs.add(run)
            await uow.commit()
        try:
            drafts = await self._rss_adapter.fetch(source)
        except InformationError as exc:
            await self._fail_run(run.id, "RSS ingestion failed")
            raise ApplicationError(exc.code, str(exc)) from exc
        inserted = duplicates = failed = 0
        for draft in drafts:
            try:
                outcome = await self._ingest_draft(
                    source,
                    draft,
                    instrument_ids=(),
                    themes=(),
                    event_type=MarketEventType.OTHER,
                    direction=MarketEventDirection.UNKNOWN,
                    summary=None,
                    importance=None,
                    ingestion_run_id=run.id,
                )
                if outcome.duplicate:
                    duplicates += 1
                else:
                    inserted += 1
            except (ApplicationError, InformationError, ValueError):
                failed += 1
        async with self._uow_factory() as uow:
            persisted = await uow.information_ingestion_runs.get_by_id(run.id)
            if persisted is None:
                raise ApplicationError("INFORMATION_INGESTION_RUN_NOT_FOUND", "run is missing")
            persisted.fetched_count = len(drafts)
            persisted.complete(
                datetime.now(UTC), inserted=inserted, duplicates=duplicates, failed=failed
            )
            await uow.information_ingestion_runs.update(persisted)
            await uow.commit()
            return persisted

    async def _fail_run(self, run_id: UUID, message: str) -> None:
        async with self._uow_factory() as uow:
            run = await uow.information_ingestion_runs.get_by_id(run_id)
            if run is not None:
                run.fail(datetime.now(UTC), message)
                await uow.information_ingestion_runs.update(run)
                await uow.commit()

    async def _ingest_draft(
        self,
        source: InformationSource,
        draft: RawDocumentDraft,
        *,
        instrument_ids: tuple[UUID, ...],
        themes: tuple[ThemeInput, ...],
        event_type: MarketEventType,
        direction: MarketEventDirection,
        summary: str | None,
        importance: Decimal | None,
        ingestion_run_id: UUID | None,
    ) -> InformationOutcome:
        title = normalize_text(draft.title, "title")
        content = normalize_text(draft.content, "content")
        content_hash = normalized_content_hash(title, content)
        received_at = datetime.now(UTC)
        async with self._uow_factory() as uow:
            duplicate = None
            if draft.external_id:
                duplicate = await uow.raw_documents.get_by_source_external(
                    source.id, draft.external_id
                )
            if duplicate is None:
                duplicate = await uow.raw_documents.get_by_hash(content_hash)
            if duplicate is not None:
                return await self._existing_outcome(uow, duplicate)
            normalized_ids = tuple(sorted(set(instrument_ids), key=str))
            instruments = await uow.instruments.get_many(list(normalized_ids))
            if len(instruments) != len(normalized_ids):
                raise ApplicationError(
                    "INFORMATION_INSTRUMENT_NOT_FOUND", "one or more instruments do not exist"
                )
            raw = RawDocument(
                source_id=source.id,
                external_id=draft.external_id,
                source_url=draft.source_url,
                title=draft.title,
                raw_content=draft.content,
                published_at=draft.published_at,
                received_at=received_at,
                content_hash=content_hash,
                language=draft.language,
                metadata=draft.metadata,
                ingestion_run_id=ingestion_run_id,
            )
            item = InformationItem(
                raw_document_id=raw.id,
                normalized_title=title,
                normalized_content=content,
                published_at=draft.published_at or received_at,
                received_at=received_at,
            )
            event = MarketEventService.build(
                item,
                event_type=event_type,
                direction=direction,
                summary=summary,
                importance=importance,
            )
            instrument_links = [
                EventInstrumentLink(event_id=event.id, instrument_id=item_id)
                for item_id in normalized_ids
            ]
            theme_links = [
                EventThemeLink(
                    event_id=event.id,
                    theme_key=theme.theme_key,
                    theme_name=theme.theme_name,
                )
                for theme in sorted(themes, key=lambda value: value.theme_key)
            ]
            await uow.raw_documents.add(raw)
            await uow.information_items.add(item)
            await uow.market_events.add(event)
            await uow.event_instrument_links.append_many(instrument_links)
            await uow.event_theme_links.append_many(theme_links)
            await uow.commit()
            return InformationOutcome(
                source=source,
                raw_document=raw,
                item=item,
                event=event,
                duplicate=False,
            )

    async def _existing_outcome(self, uow: UnitOfWork, raw: RawDocument) -> InformationOutcome:
        item = await uow.information_items.get_by_raw_document(raw.id)
        if item is None:
            raise ApplicationError("INFORMATION_INTEGRITY_ERROR", "raw document has no item")
        event = await uow.market_events.get_by_information_item(item.id)
        if event is None:
            raise ApplicationError("INFORMATION_INTEGRITY_ERROR", "item has no event")
        source = await uow.information_sources.get_by_id(raw.source_id)
        if source is None:
            raise ApplicationError("INFORMATION_INTEGRITY_ERROR", "source is missing")
        return InformationOutcome(
            source=source,
            raw_document=raw,
            item=item,
            event=event,
            duplicate=True,
        )


class InformationQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def sources(self) -> list[InformationSource]:
        async with self._uow_factory() as uow:
            return await uow.information_sources.list_all()

    async def item(self, item_id: UUID) -> InformationDetail | None:
        async with self._uow_factory() as uow:
            item = await uow.information_items.get_by_id(item_id)
            if item is None:
                return None
            return await self._detail(uow, item)

    async def items(
        self,
        *,
        search: str | None,
        source_id: UUID | None,
        instrument_id: UUID | None,
        theme_key: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[InformationDetail], int]:
        async with self._uow_factory() as uow:
            items, total = await uow.information_items.list(
                search=search,
                source_id=source_id,
                instrument_id=instrument_id,
                theme_key=theme_key,
                offset=offset,
                limit=limit,
            )
            return [await self._detail(uow, item) for item in items], total

    async def event(self, event_id: UUID) -> InformationDetail | None:
        async with self._uow_factory() as uow:
            event = await uow.market_events.get_by_id(event_id)
            if event is None:
                return None
            item = await uow.information_items.get_by_id(event.information_item_id)
            return None if item is None else await self._detail(uow, item)

    async def events(
        self,
        *,
        event_type: str | None,
        direction: str | None,
        instrument_id: UUID | None,
        theme_key: str | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[InformationDetail], int]:
        async with self._uow_factory() as uow:
            events, total = await uow.market_events.list(
                event_type=event_type,
                direction=direction,
                instrument_id=instrument_id,
                theme_key=theme_key,
                search=search,
                offset=offset,
                limit=limit,
            )
            items = []
            for event in events:
                item = await uow.information_items.get_by_id(event.information_item_id)
                if item is not None:
                    items.append(await self._detail(uow, item))
            return items, total

    async def _detail(self, uow: UnitOfWork, item: InformationItem) -> InformationDetail:
        raw = await uow.raw_documents.get_by_id(item.raw_document_id)
        event = await uow.market_events.get_by_information_item(item.id)
        if raw is None or event is None:
            raise ApplicationError(
                "INFORMATION_INTEGRITY_ERROR", "information facts are incomplete"
            )
        source = await uow.information_sources.get_by_id(raw.source_id)
        if source is None:
            raise ApplicationError("INFORMATION_INTEGRITY_ERROR", "source is missing")
        instrument_links = await uow.event_instrument_links.list_by_event(event.id)
        theme_links = await uow.event_theme_links.list_by_event(event.id)
        instruments = await uow.instruments.get_many(
            [link.instrument_id for link in instrument_links]
        )
        return InformationDetail(
            source=source,
            raw_document=raw,
            item=item,
            event=event,
            instruments=tuple(instruments),
            instrument_links=tuple(instrument_links),
            theme_links=tuple(theme_links),
        )


class InformationIntegrityService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._query = InformationQueryService(uow_factory)

    async def verify_item(self, item_id: UUID) -> list[dict[str, str]]:
        detail = await self._query.item(item_id)
        if detail is None:
            raise ApplicationError("INFORMATION_ITEM_NOT_FOUND", "information item does not exist")
        issues: list[dict[str, str]] = []
        expected = normalized_content_hash(
            detail.item.normalized_title, detail.item.normalized_content
        )
        if detail.raw_document.content_hash != expected:
            issues.append({"code": "CONTENT_HASH_MISMATCH", "message": str(item_id)})
        if detail.event.information_item_id != detail.item.id:
            issues.append({"code": "EVENT_ITEM_MISMATCH", "message": str(item_id)})
        instrument_ids = [item.instrument_id for item in detail.instrument_links]
        if len(instrument_ids) != len(set(instrument_ids)):
            issues.append({"code": "DUPLICATE_INSTRUMENT_LINK", "message": str(item_id)})
        theme_keys = [item.theme_key for item in detail.theme_links]
        if len(theme_keys) != len(set(theme_keys)):
            issues.append({"code": "DUPLICATE_THEME_LINK", "message": str(item_id)})
        return issues
