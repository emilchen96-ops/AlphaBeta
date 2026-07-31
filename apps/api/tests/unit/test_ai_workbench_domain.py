from datetime import date
from uuid import uuid4

import pytest

from alphadesk_api.application.ai_workbench import AIResearchTaskProcessor
from alphadesk_api.infrastructure.ai_workbench_provider import FakeWorkbenchProvider
from alphadesk_domain.ai_workbench import (
    MultiAgentResearchTask,
    ResearchAgentRole,
    ResearchDepth,
    ResearchTaskStatus,
    StructuredResearchRequest,
    roles_for_depth,
)


def task() -> MultiAgentResearchTask:
    return MultiAgentResearchTask(
        instrument_id=uuid4(),
        question="分析长信科技当前基本面、技术面和主要风险",
        depth=ResearchDepth.STANDARD,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 7, 1),
        provider_key="fake",
        model_name="fake-v1",
        idempotency_key=str(uuid4()),
        correlation_id=uuid4(),
    )


def test_depths_select_progressively_richer_role_groups() -> None:
    assert len(roles_for_depth(ResearchDepth.FAST)) == 4
    assert len(roles_for_depth(ResearchDepth.STANDARD)) == 6
    assert roles_for_depth(ResearchDepth.DEEP) == tuple(ResearchAgentRole)
    assert ResearchAgentRole.RISK_REVIEWER in roles_for_depth(ResearchDepth.FAST)
    assert ResearchAgentRole.RESEARCH_MANAGER in roles_for_depth(ResearchDepth.FAST)


def test_failed_task_can_be_requeued_without_changing_identity() -> None:
    value = task()
    value.fail("AI_PROVIDER_TIMEOUT", "temporary")
    value.retry()
    assert value.status is ResearchTaskStatus.CREATED
    assert value.progress_percent == 0
    assert value.error_code is None
    assert value.completed_at is None


@pytest.mark.asyncio
async def test_fake_provider_is_structured_and_explicitly_non_real() -> None:
    provider = FakeWorkbenchProvider()
    response = await provider.complete_structured(
        StructuredResearchRequest(
            role=ResearchAgentRole.RESEARCH_MANAGER,
            system_prompt="test",
            payload={
                "instrument": {"name": "长信科技"},
                "market_bars": [{"source_id": "market-bar:2026-07-01"}],
                "information": [],
            },
            schema_name="test",
            output_schema={},
        )
    )
    assert response.output["stance"] == "中性"
    assert response.output["citations"] == [
        {
            "source_id": "market-bar:2026-07-01",
            "source_type": "MARKET_BAR",
            "title": "最近一根本地历史日线",
        }
    ]
    assert "不是真实 AI 调研" in response.warnings[0]


def test_untraceable_citation_is_rejected() -> None:
    with pytest.raises(ValueError, match="无法追溯"):
        AIResearchTaskProcessor._validate_citations(
            {"citations": [{"source_id": "invented:source"}]},
            {"market_bars": [{"source_id": "market-bar:2026-07-01"}]},
        )
