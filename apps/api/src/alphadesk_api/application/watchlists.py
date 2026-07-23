"""Single-user watchlist application service with audited transactions."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from alphadesk_api.application.common import (
    ApplicationError,
    UnitOfWorkFactory,
    append_event_and_audit,
)
from alphadesk_domain.entities import Instrument, Watchlist, WatchlistItem


class WatchlistService:
    def __init__(self, uow_factory: UnitOfWorkFactory, *, item_limit: int = 200) -> None:
        self._uow_factory = uow_factory
        self._item_limit = item_limit

    async def list_all(self) -> list[Watchlist]:
        async with self._uow_factory() as uow:
            return await uow.watchlists.list_all()

    async def detail(
        self, watchlist_id: UUID
    ) -> tuple[Watchlist, list[tuple[WatchlistItem, Instrument]]]:
        async with self._uow_factory() as uow:
            watchlist = await uow.watchlists.get_by_id(watchlist_id)
            if watchlist is None:
                raise ApplicationError("WATCHLIST_NOT_FOUND", "自选列表不存在")
            items = await uow.watchlists.list_items(watchlist_id)
            instruments = await uow.instruments.get_many([item.instrument_id for item in items])
            by_id = {instrument.id: instrument for instrument in instruments}
            return watchlist, [(item, by_id[item.instrument_id]) for item in items]

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        realtime_enabled: bool = False,
        correlation_id: UUID,
    ) -> Watchlist:
        async with self._uow_factory() as uow:
            if await uow.watchlists.get_by_name(name.strip()) is not None:
                raise ApplicationError("WATCHLIST_NAME_CONFLICT", "自选列表名称已存在")
            entity = Watchlist(
                name=name,
                description=description,
                realtime_enabled=realtime_enabled,
            )
            await uow.watchlists.add(entity)
            await append_event_and_audit(
                uow,
                event_type="WATCHLIST_CREATED",
                entity_type="Watchlist",
                entity_id=entity.id,
                correlation_id=correlation_id,
                payload={"name": entity.name},
            )
            await uow.commit()
            return entity

    async def update(
        self,
        watchlist_id: UUID,
        *,
        name: str,
        description: str | None,
        realtime_enabled: bool = False,
        correlation_id: UUID,
    ) -> Watchlist:
        async with self._uow_factory() as uow:
            current = await uow.watchlists.get_by_id(watchlist_id)
            if current is None:
                raise ApplicationError("WATCHLIST_NOT_FOUND", "自选列表不存在")
            conflict = await uow.watchlists.get_by_name(name.strip())
            if conflict is not None and conflict.id != watchlist_id:
                raise ApplicationError("WATCHLIST_NAME_CONFLICT", "自选列表名称已存在")
            updated = replace(
                current,
                name=name,
                description=description,
                realtime_enabled=realtime_enabled,
                updated_at=datetime.now(UTC),
            )
            await uow.watchlists.update(updated)
            await append_event_and_audit(
                uow,
                event_type="WATCHLIST_UPDATED",
                entity_type="Watchlist",
                entity_id=watchlist_id,
                correlation_id=correlation_id,
                payload={"name": updated.name},
            )
            await uow.commit()
            return updated

    async def delete(self, watchlist_id: UUID, correlation_id: UUID) -> None:
        async with self._uow_factory() as uow:
            current = await uow.watchlists.get_by_id(watchlist_id)
            if current is None:
                raise ApplicationError("WATCHLIST_NOT_FOUND", "自选列表不存在")
            await uow.watchlists.delete(watchlist_id)
            await append_event_and_audit(
                uow,
                event_type="WATCHLIST_DELETED",
                entity_type="Watchlist",
                entity_id=watchlist_id,
                correlation_id=correlation_id,
                payload={"name": current.name},
            )
            await uow.commit()

    async def add_item(
        self,
        watchlist_id: UUID,
        *,
        instrument_id: UUID,
        note: str | None,
        correlation_id: UUID,
    ) -> WatchlistItem:
        async with self._uow_factory() as uow:
            if await uow.watchlists.get_by_id(watchlist_id) is None:
                raise ApplicationError("WATCHLIST_NOT_FOUND", "自选列表不存在")
            if await uow.instruments.get_by_id(instrument_id) is None:
                raise ApplicationError("INSTRUMENT_NOT_FOUND", "金融标的不存在")
            items = await uow.watchlists.list_items(watchlist_id)
            if len(items) >= self._item_limit:
                raise ApplicationError("WATCHLIST_LIMIT_EXCEEDED", "自选股数量已达上限")
            if any(item.instrument_id == instrument_id for item in items):
                raise ApplicationError("WATCHLIST_ITEM_ALREADY_EXISTS", "该标的已在自选列表中")
            entity = WatchlistItem(
                watchlist_id=watchlist_id,
                instrument_id=instrument_id,
                sort_order=len(items),
                note=self._validated_note(note),
            )
            await uow.watchlists.add_item(entity)
            await append_event_and_audit(
                uow,
                event_type="WATCHLIST_ITEM_ADDED",
                entity_type="WatchlistItem",
                entity_id=entity.id,
                correlation_id=correlation_id,
                payload={"watchlist_id": str(watchlist_id), "instrument_id": str(instrument_id)},
            )
            await uow.commit()
            return entity

    async def update_item(
        self,
        watchlist_id: UUID,
        item_id: UUID,
        *,
        note: str | None,
        correlation_id: UUID,
    ) -> WatchlistItem:
        async with self._uow_factory() as uow:
            current = await uow.watchlists.get_item(item_id)
            if current is None or current.watchlist_id != watchlist_id:
                raise ApplicationError("WATCHLIST_ITEM_NOT_FOUND", "自选股条目不存在")
            updated = replace(current, note=self._validated_note(note))
            await uow.watchlists.update_item(updated)
            await append_event_and_audit(
                uow,
                event_type="WATCHLIST_ITEM_UPDATED",
                entity_type="WatchlistItem",
                entity_id=item_id,
                correlation_id=correlation_id,
                payload={"watchlist_id": str(watchlist_id)},
            )
            await uow.commit()
            return updated

    async def remove_item(self, watchlist_id: UUID, item_id: UUID, correlation_id: UUID) -> None:
        async with self._uow_factory() as uow:
            current = await uow.watchlists.get_item(item_id)
            if current is None or current.watchlist_id != watchlist_id:
                raise ApplicationError("WATCHLIST_ITEM_NOT_FOUND", "自选股条目不存在")
            await uow.watchlists.remove_item(item_id)
            remaining = await uow.watchlists.list_items(watchlist_id)
            await uow.watchlists.reorder(watchlist_id, [item.id for item in remaining])
            await append_event_and_audit(
                uow,
                event_type="WATCHLIST_ITEM_REMOVED",
                entity_type="WatchlistItem",
                entity_id=item_id,
                correlation_id=correlation_id,
                payload={"watchlist_id": str(watchlist_id)},
            )
            await uow.commit()

    async def reorder(self, watchlist_id: UUID, item_ids: list[UUID], correlation_id: UUID) -> None:
        async with self._uow_factory() as uow:
            current = await uow.watchlists.list_items(watchlist_id)
            if await uow.watchlists.get_by_id(watchlist_id) is None:
                raise ApplicationError("WATCHLIST_NOT_FOUND", "自选列表不存在")
            unique_ids = set(item_ids)
            if len(item_ids) != len(unique_ids) or {item.id for item in current} != unique_ids:
                raise ApplicationError("WATCHLIST_REORDER_INVALID", "排序条目必须完整且不重复")
            await uow.watchlists.reorder(watchlist_id, item_ids)
            await append_event_and_audit(
                uow,
                event_type="WATCHLIST_REORDERED",
                entity_type="Watchlist",
                entity_id=watchlist_id,
                correlation_id=correlation_id,
                payload={"item_ids": [str(item_id) for item_id in item_ids]},
            )
            await uow.commit()

    @staticmethod
    def _validated_note(note: str | None) -> str | None:
        if note is None:
            return None
        normalized = note.strip()
        if len(normalized) > 500:
            raise ApplicationError("WATCHLIST_NOTE_TOO_LONG", "备注不能超过500个字符")
        return normalized or None
