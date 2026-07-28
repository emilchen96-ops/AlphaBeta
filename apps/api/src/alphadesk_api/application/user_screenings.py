# ruff: noqa: RUF001
"""SC02-C versioned screening plans and user-facing workflow orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.screenings import ScreeningRunOutcome, ScreeningRunService
from alphadesk_api.application.watchlists import WatchlistService
from alphadesk_domain.screening import ConditionCatalog, ScreeningError
from alphadesk_domain.screening_specs import (
    ScreeningParserSource,
    ScreeningPreviewRenderer,
    screening_spec_from_mapping,
)
from alphadesk_domain.user_screenings import (
    UserScreeningDefinition,
    UserScreeningRunLink,
    UserScreeningStatus,
    UserScreeningVersion,
)


def _safe_name(value: str) -> str:
    result = value.strip()
    if not result:
        raise ApplicationError("USER_SCREENING_NAME_REQUIRED", "请输入方案名称")
    return result


class UserScreeningService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        catalog: ConditionCatalog,
        *,
        source_code: str = "MINIQMT",
    ) -> None:
        self._uow_factory = uow_factory
        self._catalog = catalog
        self._runs = ScreeningRunService(uow_factory, catalog, source_code=source_code)
        self._renderer = ScreeningPreviewRenderer(catalog)

    async def _validated_snapshot(
        self, payload: dict[str, object]
    ) -> tuple[dict[str, object], str]:
        try:
            spec = screening_spec_from_mapping(payload, self._catalog)
            snapshot = spec.snapshot(self._catalog)
        except ScreeningError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        preview = self._renderer.render(
            spec,
            parser_source=ScreeningParserSource.LOCAL_RULES,
            data_ready=True,
            data_readiness_message="运行时会按筛选日期检查本地MiniQMT历史日线。",
            can_execute=True,
        )
        return snapshot, preview.summary

    async def create(
        self,
        *,
        name: str,
        description: str | None,
        source_text: str | None,
        screening_spec: dict[str, object],
        origin: str,
    ) -> dict[str, Any]:
        snapshot, summary = await self._validated_snapshot(screening_spec)
        normalized = _safe_name(name)
        now = datetime.now(UTC)
        definition = UserScreeningDefinition(
            id=uuid4(),
            name=normalized,
            description=(description or "").strip() or None,
            source_text=(source_text or "").strip() or None,
            origin=origin,
            status=UserScreeningStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        version = UserScreeningVersion(
            id=uuid4(),
            screening_id=definition.id,
            version_number=1,
            screening_spec=snapshot,
            source_text=definition.source_text,
            summary=summary,
            created_at=now,
        )
        async with self._uow_factory() as uow:
            if await uow.user_screenings.get_by_name(normalized) is not None:
                raise ApplicationError(
                    "USER_SCREENING_NAME_CONFLICT",
                    "同名选股方案已经存在，请换一个名称或编辑原方案",
                )
            await uow.user_screenings.add_definition(definition)
            await uow.user_screenings.add_version(version)
            await uow.commit()
        return self._dto(definition, version)

    async def get(self, screening_id: UUID) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            definition = await uow.user_screenings.get_definition(screening_id)
            version = await uow.user_screenings.get_version(screening_id)
        if definition is None or version is None:
            raise ApplicationError("USER_SCREENING_NOT_FOUND", "没有找到该选股方案")
        return self._dto(definition, version)

    async def list(self, *, page: int, page_size: int, include_archived: bool) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            definitions, total = await uow.user_screenings.list(
                include_archived=include_archived,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            items = []
            for definition in definitions:
                version = await uow.user_screenings.get_version(definition.id)
                if version is not None:
                    items.append(self._dto(definition, version))
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    async def update(
        self,
        screening_id: UUID,
        *,
        name: str,
        description: str | None,
        source_text: str | None,
        screening_spec: dict[str, object],
        origin: str,
    ) -> dict[str, Any]:
        snapshot, summary = await self._validated_snapshot(screening_spec)
        normalized = _safe_name(name)
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            definition = await uow.user_screenings.get_definition(screening_id)
            if definition is None:
                raise ApplicationError("USER_SCREENING_NOT_FOUND", "没有找到该选股方案")
            if definition.status is UserScreeningStatus.ARCHIVED:
                raise ApplicationError("USER_SCREENING_ARCHIVED", "请先恢复归档方案再编辑")
            conflict = await uow.user_screenings.get_by_name(normalized)
            if conflict is not None and conflict.id != screening_id:
                raise ApplicationError("USER_SCREENING_NAME_CONFLICT", "同名选股方案已经存在")
            definition.name = normalized
            definition.description = (description or "").strip() or None
            definition.source_text = (source_text or "").strip() or None
            definition.origin = origin
            definition.current_version += 1
            definition.status = UserScreeningStatus.ACTIVE
            definition.updated_at = now
            version = UserScreeningVersion(
                id=uuid4(),
                screening_id=screening_id,
                version_number=definition.current_version,
                screening_spec=snapshot,
                source_text=definition.source_text,
                summary=summary,
                created_at=now,
            )
            await uow.user_screenings.update_definition(definition)
            await uow.user_screenings.add_version(version)
            await uow.commit()
        return self._dto(definition, version)

    async def clone(self, screening_id: UUID) -> dict[str, Any]:
        source = await self.get(screening_id)
        base = f"{source['name']}（副本）"
        candidate = base
        suffix = 2
        async with self._uow_factory() as uow:
            while await uow.user_screenings.get_by_name(candidate) is not None:
                candidate = f"{base}{suffix}"
                suffix += 1
        return await self.create(
            name=candidate,
            description=source["description"],
            source_text=source["source_text"],
            screening_spec=source["screening_spec"],
            origin="CLONED",
        )

    async def set_status(self, screening_id: UUID, status: UserScreeningStatus) -> dict[str, Any]:
        async with self._uow_factory() as uow:
            definition = await uow.user_screenings.get_definition(screening_id)
            version = await uow.user_screenings.get_version(screening_id)
            if definition is None or version is None:
                raise ApplicationError("USER_SCREENING_NOT_FOUND", "没有找到该选股方案")
            definition.status = status
            definition.updated_at = datetime.now(UTC)
            await uow.user_screenings.update_definition(definition)
            await uow.commit()
        return self._dto(definition, version)

    async def run(
        self,
        screening_id: UUID,
        *,
        as_of_date: date,
        correlation_id: UUID,
        idempotency_key: str | None,
    ) -> ScreeningRunOutcome:
        async with self._uow_factory() as uow:
            definition = await uow.user_screenings.get_definition(screening_id)
            version = await uow.user_screenings.get_version(screening_id)
        if definition is None or version is None:
            raise ApplicationError("USER_SCREENING_NOT_FOUND", "没有找到该选股方案")
        if definition.status is UserScreeningStatus.ARCHIVED:
            raise ApplicationError("USER_SCREENING_ARCHIVED", "已归档方案不能运行")
        try:
            spec = screening_spec_from_mapping(version.screening_spec, self._catalog)
        except ScreeningError as exc:
            raise ApplicationError(exc.code, str(exc)) from exc
        outcome = await self._runs.enqueue(
            replace(
                spec,
                name=definition.name,
                as_of_date=as_of_date,
                origin="USER_SAVED",
            ),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        if not outcome.replayed:
            now = datetime.now(UTC)
            async with self._uow_factory() as uow:
                current = await uow.user_screenings.get_definition(screening_id)
                if current is None:
                    raise ApplicationError("USER_SCREENING_NOT_FOUND", "没有找到该选股方案")
                current.last_used_at = now
                current.updated_at = now
                await uow.user_screenings.update_definition(current)
                await uow.user_screenings.add_run_link(
                    UserScreeningRunLink(
                        scan_run_id=outcome.run.id,
                        screening_id=screening_id,
                        screening_version_id=version.id,
                    )
                )
                await uow.commit()
        return outcome

    @staticmethod
    def _dto(definition: UserScreeningDefinition, version: UserScreeningVersion) -> dict[str, Any]:
        return {
            "id": definition.id,
            "name": definition.name,
            "description": definition.description,
            "source_text": definition.source_text,
            "origin": definition.origin,
            "current_version": definition.current_version,
            "status": definition.status.value,
            "screening_spec": version.screening_spec,
            "summary": version.summary,
            "created_at": definition.created_at,
            "updated_at": definition.updated_at,
            "last_used_at": definition.last_used_at,
        }


class ScreeningWatchlistService:
    MAX_BATCH = 200

    def __init__(self, uow_factory: UnitOfWorkFactory, *, item_limit: int) -> None:
        self._uow_factory = uow_factory
        self._watchlists = WatchlistService(uow_factory, item_limit=item_limit)

    async def add(
        self,
        *,
        scan_run_id: UUID,
        instrument_ids: list[UUID],
        watchlist_id: UUID | None,
        new_watchlist_name: str | None,
        realtime_monitor: bool,
        correlation_id: UUID,
    ) -> dict[str, object]:
        unique_ids = list(dict.fromkeys(instrument_ids))
        if not unique_ids or len(unique_ids) > self.MAX_BATCH:
            raise ApplicationError(
                "SCREENING_WATCHLIST_BATCH_INVALID",
                f"请选择1至{self.MAX_BATCH}只股票",
            )
        async with self._uow_factory() as uow:
            run = await uow.scan_runs.get_by_id(scan_run_id)
            result_ids = {
                item.instrument_id for item in await uow.scan_results.list_by_run(scan_run_id)
            }
        if run is None or not run.screening_spec:
            raise ApplicationError("SCREENING_RUN_NOT_FOUND", "筛选记录不存在")
        if not set(unique_ids).issubset(result_ids):
            raise ApplicationError("SCREENING_RESULT_INVALID", "只能添加本次入选的股票")
        target_id = watchlist_id
        if target_id is None:
            target_name = "盘中监控" if realtime_monitor else (new_watchlist_name or "").strip()
            if not target_name:
                raise ApplicationError("WATCHLIST_REQUIRED", "请选择或新建一个自选分组")
            existing = next(
                (item for item in await self._watchlists.list_all() if item.name == target_name),
                None,
            )
            if existing is None:
                existing = await self._watchlists.create(
                    name=target_name,
                    description="由智能选股结果创建",
                    realtime_enabled=realtime_monitor,
                    correlation_id=correlation_id,
                )
            target_id = existing.id
        succeeded = existed = failed = 0
        for instrument_id in unique_ids:
            try:
                await self._watchlists.add_item(
                    target_id,
                    instrument_id=instrument_id,
                    note="来自智能选股",
                    correlation_id=correlation_id,
                )
                succeeded += 1
            except ApplicationError as exc:
                if exc.code == "WATCHLIST_ITEM_ALREADY_EXISTS":
                    existed += 1
                else:
                    failed += 1
        return {
            "watchlist_id": target_id,
            "succeeded": succeeded,
            "already_exists": existed,
            "failed": failed,
        }
