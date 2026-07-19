from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.information import (
    InformationIngestionService,
    InformationQueryService,
    ManualInformationRequest,
    ThemeInput,
)
from alphadesk_api.infrastructure.models import (
    AccountCashBalanceModel,
    EventInstrumentLinkModel,
    EventThemeLinkModel,
    FillModel,
    InformationIngestionRunModel,
    InformationItemModel,
    MarketEventModel,
    OrderModel,
    PositionModel,
    RawDocumentModel,
    RiskDecisionModel,
    SignalModel,
)
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.entities import Instrument
from alphadesk_domain.information import (
    InformationError,
    InformationSource,
    InformationSourceType,
    MarketEventDirection,
    MarketEventType,
    RawDocumentDraft,
)

NOW = datetime(2026, 7, 18, 1, tzinfo=UTC)


class StaticAdapter:
    def __init__(self, draft: RawDocumentDraft) -> None:
        self.draft = draft

    async def fetch(self, source: InformationSource) -> list[RawDocumentDraft]:
        del source
        return [self.draft]


class FailingAdapter:
    async def fetch(self, source: InformationSource) -> list[RawDocumentDraft]:
        del source
        raise InformationError("INFORMATION_RSS_FETCH_FAILED", "RSS ingestion failed")


async def seed_instrument(factory: async_sessionmaker[AsyncSession]) -> Instrument:
    value = Instrument(
        symbol=f"N{uuid4().hex[:7]}",
        exchange="SSE",
        market="CN",
        name="N01 test",
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
    )
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.instruments.add(value)
        await uow.commit()
    return value


def factory(value: async_sessionmaker[AsyncSession]) -> UnitOfWorkFactory:
    return cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(value))


@pytest.mark.integration
@pytest.mark.n01
@pytest.mark.asyncio
async def test_manual_hash_dedup_links_search_and_no_trading_side_effects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    instrument = await seed_instrument(session_factory)
    protected = (
        SignalModel,
        RiskDecisionModel,
        OrderModel,
        FillModel,
        AccountCashBalanceModel,
        PositionModel,
    )
    async with session_factory() as session:
        before = [
            await session.scalar(select(func.count()).select_from(model)) for model in protected
        ]
        information_before = [
            await session.scalar(select(func.count()).select_from(model))
            for model in (
                RawDocumentModel,
                InformationItemModel,
                MarketEventModel,
                EventInstrumentLinkModel,
                EventThemeLinkModel,
            )
        ]
    request = ManualInformationRequest(
        source_name="N01 manual fixture",
        title="  公司  公告 ",
        content="原始   正文 内容",
        source_url="https://example.test/manual",
        published_at=NOW,
        instrument_ids=(instrument.id,),
        themes=(ThemeInput(theme_key="bank", theme_name="银行"),),
        event_type=MarketEventType.COMPANY_ANNOUNCEMENT,
        direction=MarketEventDirection.UNKNOWN,
        summary=None,
        importance=Decimal("0.8"),
        correlation_id=uuid4(),
    )
    service = InformationIngestionService(factory(session_factory))
    first = await service.add_manual(request)
    second = await service.add_manual(request)
    assert not first.duplicate and second.duplicate
    assert first.item.id == second.item.id and first.event.id == second.event.id
    details, total = await InformationQueryService(factory(session_factory)).items(
        search="公告",
        source_id=first.source.id,
        instrument_id=instrument.id,
        theme_key="bank",
        offset=0,
        limit=20,
    )
    assert total == len(details) == 1
    assert details[0].raw_document.title == "  公司  公告 "
    assert details[0].item.normalized_title == "公司 公告"
    async with session_factory() as session:
        information_after = [
            await session.scalar(select(func.count()).select_from(model))
            for model in (
                RawDocumentModel,
                InformationItemModel,
                MarketEventModel,
                EventInstrumentLinkModel,
                EventThemeLinkModel,
            )
        ]
        assert information_after == [(value or 0) + 1 for value in information_before]
        after = [
            await session.scalar(select(func.count()).select_from(model)) for model in protected
        ]
        assert after == before


@pytest.mark.integration
@pytest.mark.n01
@pytest.mark.asyncio
async def test_external_id_dedup_and_rss_failure_preserves_existing_facts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = InformationIngestionService(factory(session_factory))
    source = await base.ensure_source(
        display_name="N01 RSS fixture",
        source_type=InformationSourceType.RSS,
        base_url="https://example.test/rss.xml",
    )
    first = InformationIngestionService(
        factory(session_factory),
        StaticAdapter(
            RawDocumentDraft(
                title="RSS title",
                content="first content",
                external_id="rss-1",
                published_at=NOW,
            )
        ),
    )
    first_run = await first.ingest_source(source.id, uuid4())
    second = InformationIngestionService(
        factory(session_factory),
        StaticAdapter(
            RawDocumentDraft(
                title="RSS changed title",
                content="changed content",
                external_id="rss-1",
                published_at=NOW,
            )
        ),
    )
    second_run = await second.ingest_source(source.id, uuid4())
    assert first_run.inserted_count == 1
    assert second_run.duplicate_count == 1 and second_run.inserted_count == 0
    async with session_factory() as session:
        before = await session.scalar(select(func.count()).select_from(RawDocumentModel))
    with pytest.raises(ApplicationError, match="RSS ingestion failed"):
        await InformationIngestionService(factory(session_factory), FailingAdapter()).ingest_source(
            source.id, uuid4()
        )
    async with session_factory() as session:
        after = await session.scalar(select(func.count()).select_from(RawDocumentModel))
        failed_runs = await session.scalar(
            select(func.count())
            .select_from(InformationIngestionRunModel)
            .where(InformationIngestionRunModel.status == "FAILED")
        )
    assert after == before and (failed_runs or 0) >= 1
