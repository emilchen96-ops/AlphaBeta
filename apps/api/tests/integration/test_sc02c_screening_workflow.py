# ruff: noqa: RUF001
from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.common import UnitOfWorkFactory
from alphadesk_api.application.user_screenings import UserScreeningService
from alphadesk_api.infrastructure.models import UserScreeningVersionModel
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.screening import (
    builtin_condition_catalog,
    screening_template_catalog,
)
from alphadesk_domain.user_screenings import UserScreeningStatus


@pytest.mark.integration
@pytest.mark.asyncio
async def test_saved_screening_versions_clone_archive_and_restore(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    catalog = builtin_condition_catalog()
    factory = cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(session_factory))
    service = UserScreeningService(factory, catalog)
    template = screening_template_catalog()[0]
    snapshot = template.spec.snapshot(catalog)
    unique_name = f"SC02-C验收方案-{uuid4()}"

    created = await service.create(
        name=unique_name,
        description="首个版本",
        source_text="最近涨停后回踩并缩量",
        screening_spec=snapshot,
        origin="BUILTIN_TEMPLATE",
    )
    assert created["current_version"] == 1
    assert created["status"] == "ACTIVE"

    updated_snapshot = dict(snapshot)
    updated_snapshot["name"] = "用户调整后的涨停回踩"
    updated = await service.update(
        UUID(str(created["id"])),
        name=unique_name,
        description="第二个版本",
        source_text="回看30日的涨停回踩",
        screening_spec=updated_snapshot,
        origin="USER_CORRECTED",
    )
    assert updated["current_version"] == 2
    assert updated["description"] == "第二个版本"

    async with session_factory() as session:
        version_count = await session.scalar(
            select(func.count())
            .select_from(UserScreeningVersionModel)
            .where(UserScreeningVersionModel.screening_id == created["id"])
        )
    assert version_count == 2

    cloned = await service.clone(UUID(str(created["id"])))
    assert cloned["name"].startswith(f"{unique_name}（副本）")
    assert cloned["current_version"] == 1

    archived = await service.set_status(
        UUID(str(created["id"])),
        UserScreeningStatus.ARCHIVED,
    )
    assert archived["status"] == "ARCHIVED"
    restored = await service.set_status(
        UUID(str(created["id"])),
        UserScreeningStatus.ACTIVE,
    )
    assert restored["status"] == "ACTIVE"


def test_template_catalog_is_data_driven_and_all_specs_are_valid() -> None:
    catalog = builtin_condition_catalog()
    templates = screening_template_catalog()
    assert {item.template_key for item in templates} == {
        "limit_up_pullback",
        "bottom_volume_expansion",
        "volume_anomaly",
        "limit_up_retrace",
        "volume_breakout",
        "moving_average_trend",
    }
    for item in templates:
        assert item.spec.validate(catalog).required_history_bars > 0
        assert item.spec.snapshot(catalog)["origin"] == "BUILTIN_TEMPLATE"
