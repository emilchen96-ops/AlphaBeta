from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphadesk_api.application.ai_research import (
    AIResearchAnalysisService,
    AIResearchIntegrityService,
    AnalysisRequest,
)
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.information import (
    InformationIngestionService,
    ManualInformationRequest,
)
from alphadesk_api.infrastructure.models import (
    AccountCashBalanceModel,
    FillModel,
    OrderModel,
    PositionModel,
    ResearchEvidenceModel,
    ResearchInsightModel,
    RiskDecisionModel,
    SignalModel,
)
from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from alphadesk_domain.ai_research import (
    AIAnalysisStatus,
    AIAnalysisType,
    AIEvidenceReference,
    AIImpactDirection,
    AIProviderResponse,
    AIResearchError,
    AIResearchOutput,
    AIResearchProvider,
    AIResearchRequest,
    DisabledAIResearchProvider,
    FakeAIResearchProvider,
)
from alphadesk_domain.information import MarketEventDirection, MarketEventType

NOW = datetime(2026, 7, 19, 1, tzinfo=UTC)


def factory(value: async_sessionmaker[AsyncSession]) -> UnitOfWorkFactory:
    return cast(UnitOfWorkFactory, lambda: SqlAlchemyUnitOfWork(value))


async def seed_information(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    outcome = await InformationIngestionService(factory(session_factory)).add_manual(
        ManualInformationRequest(
            source_name=f"A01 fixture {uuid4()}",
            title="A01 grounded source",
            content="A01 original source fact for evidence verification.",
            source_url="https://example.test/a01",
            published_at=NOW,
            instrument_ids=(),
            themes=(),
            event_type=MarketEventType.COMPANY_ANNOUNCEMENT,
            direction=MarketEventDirection.UNKNOWN,
            summary=None,
            importance=Decimal("0.5"),
            correlation_id=uuid4(),
        )
    )
    return outcome.item.id, outcome.event.id


def request(item_id: UUID, event_id: UUID, key: str) -> AnalysisRequest:
    return AnalysisRequest(
        analysis_type=AIAnalysisType.EVENT_SUMMARY,
        event_ids=(event_id,),
        information_item_ids=(item_id,),
        instrument_ids=(),
        question=None,
        idempotency_key=key,
        correlation_id=uuid4(),
    )


class SequencedProvider:
    provider_key = "sequenced-fake"
    model_name = "sequenced-v1"
    configured = True

    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, value: AIResearchRequest) -> AIProviderResponse:
        self.calls += 1
        if self.calls == 1:
            raise AIResearchError("AI_PROVIDER_TIMEOUT", "temporary", transient=True)
        return await FakeAIResearchProvider().analyze(value)


class InvalidEvidenceProvider:
    provider_key = "invalid-fake"
    model_name = "invalid-v1"
    configured = True

    async def analyze(self, value: AIResearchRequest) -> AIProviderResponse:
        del value
        return AIProviderResponse(
            output=AIResearchOutput(
                title="invalid evidence",
                summary="This must fail before any insight is persisted.",
                entities=(),
                instruments=(),
                themes=(),
                impact_direction=AIImpactDirection.UNKNOWN,
                importance_score=Decimal("10"),
                confidence=Decimal("0.1"),
                key_facts=(),
                uncertainties=("invalid source",),
                research_questions=(),
                evidence_references=(
                    AIEvidenceReference(
                        information_item_id=uuid4(),
                        evidence_text="not an input",
                    ),
                ),
            )
        )


@pytest.mark.integration
@pytest.mark.a01
@pytest.mark.asyncio
async def test_grounded_success_idempotency_cost_integrity_and_no_trading_effects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    item_id, event_id = await seed_information(session_factory)
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
    provider = FakeAIResearchProvider()
    service = AIResearchAnalysisService(factory(session_factory), provider)
    first = await service.analyze(request(item_id, event_id, f"a01-{uuid4()}"))
    assert first.run.status is AIAnalysisStatus.COMPLETED
    assert first.insight is not None and len(first.evidence) == 1
    assert first.evidence[0].information_item_id == item_id
    assert first.run.input_token_count == 100
    assert first.run.output_token_count == 80
    assert first.run.estimated_cost == Decimal("0")
    replay = await service.analyze(request(item_id, event_id, first.run.idempotency_key))
    assert replay.replayed and replay.run.id == first.run.id and provider.calls == 1
    with pytest.raises(ApplicationError, match="idempotency key"):
        changed = request(item_id, event_id, first.run.idempotency_key)
        await service.analyze(
            AnalysisRequest(
                analysis_type=AIAnalysisType.RESEARCH_QUESTION,
                event_ids=changed.event_ids,
                information_item_ids=changed.information_item_ids,
                instrument_ids=(),
                question="What changed?",
                idempotency_key=changed.idempotency_key,
                correlation_id=uuid4(),
            )
        )
    assert await AIResearchIntegrityService(factory(session_factory)).verify(first.run.id) == []
    async with session_factory() as session:
        after = [
            await session.scalar(select(func.count()).select_from(model)) for model in protected
        ]
    assert after == before


@pytest.mark.integration
@pytest.mark.a01
@pytest.mark.asyncio
async def test_retry_once_and_failures_leave_no_partial_insight(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    item_id, event_id = await seed_information(session_factory)
    transient = SequencedProvider()
    successful = await AIResearchAnalysisService(
        factory(session_factory), cast(AIResearchProvider, transient)
    ).analyze(request(item_id, event_id, f"retry-{uuid4()}"))
    assert successful.run.status is AIAnalysisStatus.COMPLETED
    assert transient.calls == 2

    invalid = await AIResearchAnalysisService(
        factory(session_factory), InvalidEvidenceProvider()
    ).analyze(request(item_id, event_id, f"invalid-{uuid4()}"))
    disabled = await AIResearchAnalysisService(
        factory(session_factory), DisabledAIResearchProvider()
    ).analyze(request(item_id, event_id, f"disabled-{uuid4()}"))
    assert invalid.run.status is AIAnalysisStatus.FAILED and invalid.insight is None
    assert invalid.run.error_code == "AI_EVIDENCE_REFERENCE_INVALID"
    assert disabled.run.status is AIAnalysisStatus.FAILED and disabled.insight is None
    assert disabled.run.error_code == "AI_PROVIDER_DISABLED"
    async with session_factory() as session:
        partial_insights = await session.scalar(
            select(func.count())
            .select_from(ResearchInsightModel)
            .where(ResearchInsightModel.analysis_run_id.in_([invalid.run.id, disabled.run.id]))
        )
        dangling_evidence = await session.scalar(
            select(func.count())
            .select_from(ResearchEvidenceModel)
            .where(
                ResearchEvidenceModel.insight_id.in_(
                    select(ResearchInsightModel.id).where(
                        ResearchInsightModel.analysis_run_id.in_([invalid.run.id, disabled.run.id])
                    )
                )
            )
        )
    assert partial_insights == 0 and dangling_evidence == 0
