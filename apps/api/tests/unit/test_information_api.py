from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from typing import Self
from uuid import UUID

from fastapi.testclient import TestClient

from alphadesk_api.app_factory import create_app
from alphadesk_api.core.config import Settings
from alphadesk_domain.entities import Instrument
from alphadesk_domain.information import (
    EventInstrumentLink,
    EventThemeLink,
    InformationIngestionRun,
    InformationItem,
    InformationSource,
    MarketEvent,
    RawDocument,
)

INSTRUMENT_ID = UUID("11111111-1111-4111-8111-111111111111")


@dataclass
class Store:
    sources: list[InformationSource]
    raw: list[RawDocument]
    items: list[InformationItem]
    events: list[MarketEvent]
    instrument_links: list[EventInstrumentLink]
    theme_links: list[EventThemeLink]
    runs: list[InformationIngestionRun]
    instruments: list[Instrument]


class SourceRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def add(self, value: InformationSource) -> None:
        self.store.sources.append(deepcopy(value))

    async def update(self, value: InformationSource) -> None:
        self.store.sources = [
            deepcopy(value) if item.id == value.id else item for item in self.store.sources
        ]

    async def get_by_id(self, value: UUID) -> InformationSource | None:
        return deepcopy(next((item for item in self.store.sources if item.id == value), None))

    async def get_by_key(self, value: str) -> InformationSource | None:
        return deepcopy(
            next((item for item in self.store.sources if item.source_key == value), None)
        )

    async def list_all(self) -> list[InformationSource]:
        return deepcopy(self.store.sources)


class RawRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def add(self, value: RawDocument) -> None:
        self.store.raw.append(deepcopy(value))

    async def get_by_id(self, value: UUID) -> RawDocument | None:
        return deepcopy(next((item for item in self.store.raw if item.id == value), None))

    async def get_by_source_external(self, source_id: UUID, external_id: str) -> RawDocument | None:
        return deepcopy(
            next(
                (
                    item
                    for item in self.store.raw
                    if item.source_id == source_id and item.external_id == external_id
                ),
                None,
            )
        )

    async def get_by_hash(self, value: str) -> RawDocument | None:
        return deepcopy(next((item for item in self.store.raw if item.content_hash == value), None))


class ItemRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def add(self, value: InformationItem) -> None:
        self.store.items.append(deepcopy(value))

    async def get_by_id(self, value: UUID) -> InformationItem | None:
        return deepcopy(next((item for item in self.store.items if item.id == value), None))

    async def get_by_raw_document(self, value: UUID) -> InformationItem | None:
        return deepcopy(
            next((item for item in self.store.items if item.raw_document_id == value), None)
        )

    async def list(
        self, *, offset: int, limit: int, **filters: object
    ) -> tuple[list[InformationItem], int]:
        values = self.store.items
        search = filters.get("search")
        if search:
            query = str(search).lower()
            values = [
                item
                for item in values
                if query in item.normalized_title.lower()
                or query in item.normalized_content.lower()
            ]
        return deepcopy(values[offset : offset + limit]), len(values)


class EventRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def add(self, value: MarketEvent) -> None:
        self.store.events.append(deepcopy(value))

    async def get_by_id(self, value: UUID) -> MarketEvent | None:
        return deepcopy(next((item for item in self.store.events if item.id == value), None))

    async def get_by_information_item(self, value: UUID) -> MarketEvent | None:
        return deepcopy(
            next((item for item in self.store.events if item.information_item_id == value), None)
        )

    async def list(
        self, *, offset: int, limit: int, **filters: object
    ) -> tuple[list[MarketEvent], int]:
        values = self.store.events
        event_type = filters.get("event_type")
        if event_type:
            values = [item for item in values if item.event_type.value == event_type]
        return deepcopy(values[offset : offset + limit]), len(values)


class LinkRepo:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    async def append_many(self, values: list[object]) -> None:
        self.values.extend(deepcopy(values))

    async def list_by_event(self, event_id: UUID) -> list[object]:
        return deepcopy([item for item in self.values if item.event_id == event_id])


class RunRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def add(self, value: InformationIngestionRun) -> None:
        self.store.runs.append(deepcopy(value))

    async def update(self, value: InformationIngestionRun) -> None:
        self.store.runs = [
            deepcopy(value) if item.id == value.id else item for item in self.store.runs
        ]

    async def get_by_id(self, value: UUID) -> InformationIngestionRun | None:
        return deepcopy(next((item for item in self.store.runs if item.id == value), None))


class InstrumentRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def get_many(self, ids: list[UUID]) -> list[Instrument]:
        return deepcopy([item for item in self.store.instruments if item.id in set(ids)])


class FakeUow:
    def __init__(self, shared: Store) -> None:
        self.shared = shared
        self.local = deepcopy(shared)

    async def __aenter__(self) -> Self:
        self.information_sources = SourceRepo(self.local)
        self.raw_documents = RawRepo(self.local)
        self.information_items = ItemRepo(self.local)
        self.market_events = EventRepo(self.local)
        self.event_instrument_links = LinkRepo(self.local.instrument_links)
        self.event_theme_links = LinkRepo(self.local.theme_links)
        self.information_ingestion_runs = RunRepo(self.local)
        self.instruments = InstrumentRepo(self.local)
        return self

    async def commit(self) -> None:
        self.shared.sources = self.local.sources
        self.shared.raw = self.local.raw
        self.shared.items = self.local.items
        self.shared.events = self.local.events
        self.shared.instrument_links = self.local.instrument_links
        self.shared.theme_links = self.local.theme_links
        self.shared.runs = self.local.runs

    async def rollback(self) -> None:
        pass

    async def __aexit__(self, *args: object) -> None:
        pass


class DatabaseStub:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass

    def unit_of_work(self) -> FakeUow:
        return FakeUow(self.store)


class Probe:
    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


def client() -> Iterator[tuple[TestClient, Store]]:
    stock = Instrument(
        id=INSTRUMENT_ID,
        symbol="600000",
        exchange="SSE",
        market="CN",
        name="浦发银行",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
    )
    store = Store([], [], [], [], [], [], [], [stock])
    app = create_app(
        Settings(environment="test", postgres_host="unused", redis_host="unused"),
        database=DatabaseStub(store),
        redis_service=Probe(),
    )
    with TestClient(app) as value:
        yield value, store


def payload() -> dict[str, object]:
    return {
        "source_name": "用户手工来源",
        "title": " 公司  公告 ",
        "content": "公告 正文 内容",
        "source_url": "https://example.test/news/1",
        "published_at": "2026-07-18T01:00:00Z",
        "instrument_ids": [str(INSTRUMENT_ID)],
        "themes": [{"theme_key": "bank", "theme_name": "银行"}],
        "event_type": "COMPANY_ANNOUNCEMENT",
        "direction": "UNKNOWN",
        "importance": "0.8",
    }


def test_manual_dedup_links_queries_and_safety() -> None:
    iterator = client()
    api, store = next(iterator)
    try:
        first = api.post("/api/v1/information/manual", json=payload())
        second = api.post("/api/v1/information/manual", json=payload())
        assert first.status_code == second.status_code == 201
        assert first.json()["item_id"] == second.json()["item_id"]
        assert second.json()["duplicate"] is True
        assert first.json()["published_at"] != first.json()["received_at"]
        assert first.json()["instruments"][0]["symbol"] == "600000"
        assert first.json()["themes"] == [{"theme_key": "bank", "theme_name": "银行"}]
        assert all(value is False for value in first.json()["capabilities"].values())
        assert len(store.raw) == len(store.items) == len(store.events) == 1
        page = api.get("/api/v1/information-items?search=公告").json()
        assert page["total"] == 1
        event_page = api.get("/api/v1/market-events?event_type=COMPANY_ANNOUNCEMENT").json()
        assert event_page["total"] == 1
        item_id = first.json()["item_id"]
        assert api.get(f"/api/v1/information-items/{item_id}/integrity").json()["valid"]
    finally:
        iterator.close()
