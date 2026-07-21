"""A01 grounded AI orchestration, queries and integrity checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_domain.ai_research import (
    OUTPUT_SCHEMA_VERSION,
    PROMPT_TEMPLATE_KEY,
    PROMPT_VERSION,
    AIAnalysisRun,
    AIAnalysisStatus,
    AIAnalysisType,
    AIProviderResponse,
    AIResearchDocument,
    AIResearchError,
    AIResearchProvider,
    AIResearchRequest,
    ResearchEvidence,
    ResearchInsight,
    analysis_fingerprint,
)
from alphadesk_domain.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisRequest:
    analysis_type: AIAnalysisType
    event_ids: tuple[UUID, ...]
    information_item_ids: tuple[UUID, ...]
    instrument_ids: tuple[UUID, ...]
    question: str | None
    idempotency_key: str
    correlation_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisOutcome:
    run: AIAnalysisRun
    insight: ResearchInsight | None
    evidence: tuple[ResearchEvidence, ...]
    replayed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class InsightDetail:
    insight: ResearchInsight
    run: AIAnalysisRun
    evidence: tuple[ResearchEvidence, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadedInputs:
    documents: tuple[AIResearchDocument, ...]
    raw_document_ids: tuple[UUID, ...]
    information_item_ids: frozenset[UUID]
    event_ids: frozenset[UUID]
    instrument_ids: tuple[UUID, ...]


def _question(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


class AIResearchAnalysisService:
    def __init__(self, uow_factory: UnitOfWorkFactory, provider: AIResearchProvider) -> None:
        self._uow_factory = uow_factory
        self._provider = provider

    async def analyze(self, request: AnalysisRequest) -> AnalysisOutcome:
        inputs = await self._load_inputs(request)
        question = _question(request.question)
        if request.analysis_type is AIAnalysisType.RESEARCH_QUESTION and question is None:
            raise ApplicationError("AI_QUESTION_REQUIRED", "research question is required")
        fingerprint = analysis_fingerprint(
            {
                "provider": self._provider.provider_key,
                "model": self._provider.model_name,
                "analysis_type": request.analysis_type.value,
                "prompt_version": PROMPT_VERSION,
                "input_document_ids": [str(item) for item in inputs.raw_document_ids],
                "input_event_ids": [str(item) for item in sorted(inputs.event_ids, key=str)],
                "instrument_ids": [str(item) for item in inputs.instrument_ids],
                "question": question,
                "output_schema_version": OUTPUT_SCHEMA_VERSION,
            }
        )
        async with self._uow_factory() as uow:
            existing = await uow.ai_analysis_runs.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ApplicationError(
                        "AI_ANALYSIS_IDEMPOTENCY_CONFLICT",
                        "idempotency key belongs to another analysis request",
                    )
                return await self._outcome(uow, existing, replayed=True)
            run = AIAnalysisRun(
                provider_key=self._provider.provider_key,
                model_name=self._provider.model_name,
                analysis_type=request.analysis_type,
                prompt_template_key=PROMPT_TEMPLATE_KEY,
                prompt_version=PROMPT_VERSION,
                input_document_ids=inputs.raw_document_ids,
                input_event_ids=tuple(sorted(inputs.event_ids, key=str)),
                instrument_ids=inputs.instrument_ids,
                user_question=question,
                status=AIAnalysisStatus.CREATED,
                request_fingerprint=fingerprint,
                idempotency_key=request.idempotency_key,
                correlation_id=request.correlation_id,
            )
            run.mark_running(datetime.now(UTC))
            await uow.ai_analysis_runs.add(run)
            await uow.commit()
        provider_request = AIResearchRequest(
            analysis_type=request.analysis_type,
            documents=inputs.documents,
            instrument_ids=inputs.instrument_ids,
            question=question,
        )
        try:
            response = await self._call_provider(provider_request)
            self._validate_output(response, inputs)
            return await self._persist_success(run.id, response)
        except (AIResearchError, RuntimeError, ValueError) as exc:
            code = exc.code if isinstance(exc, AIResearchError) else "AI_OUTPUT_INVALID"
            await self._mark_failed(run.id, code, "AI analysis failed")
            async with self._uow_factory() as uow:
                failed = await uow.ai_analysis_runs.get_by_id(run.id)
                if failed is None:
                    raise ApplicationError(
                        "AI_ANALYSIS_RUN_NOT_FOUND", "analysis run is missing"
                    ) from exc
                return await self._outcome(uow, failed, replayed=False)

    async def _call_provider(self, request: AIResearchRequest) -> AIProviderResponse:
        try:
            return await self._provider.analyze(request)
        except AIResearchError as exc:
            if not exc.transient:
                raise
        return await self._provider.analyze(request)

    def _validate_output(self, response: AIProviderResponse, inputs: LoadedInputs) -> None:
        output = response.output
        if output.schema_version != OUTPUT_SCHEMA_VERSION:
            raise AIResearchError("AI_OUTPUT_SCHEMA_INVALID", "output schema is invalid")
        for reference in output.evidence_references:
            if (
                reference.information_item_id is not None
                and reference.information_item_id not in inputs.information_item_ids
            ) or (
                reference.market_event_id is not None
                and reference.market_event_id not in inputs.event_ids
            ):
                raise AIResearchError(
                    "AI_EVIDENCE_REFERENCE_INVALID",
                    "AI output references a source outside this analysis",
                )

    async def _load_inputs(self, request: AnalysisRequest) -> LoadedInputs:
        item_ids = set(request.information_item_ids)
        event_ids = set(request.event_ids)
        documents: dict[UUID, AIResearchDocument] = {}
        async with self._uow_factory() as uow:
            instruments = await uow.instruments.get_many(list(set(request.instrument_ids)))
            if len(instruments) != len(set(request.instrument_ids)):
                raise ApplicationError("AI_INSTRUMENT_NOT_FOUND", "instrument does not exist")
            event_map = {}
            for event_id in sorted(event_ids, key=str):
                event = await uow.market_events.get_by_id(event_id)
                if event is None:
                    raise ApplicationError("AI_EVENT_NOT_FOUND", "market event does not exist")
                event_map[event_id] = event
                item_ids.add(event.information_item_id)
            for item_id in sorted(item_ids, key=str):
                item = await uow.information_items.get_by_id(item_id)
                if item is None:
                    raise ApplicationError(
                        "AI_INFORMATION_ITEM_NOT_FOUND", "information item does not exist"
                    )
                raw = await uow.raw_documents.get_by_id(item.raw_document_id)
                if raw is None:
                    raise ApplicationError("AI_INPUT_INTEGRITY_ERROR", "raw document is missing")
                source = await uow.information_sources.get_by_id(raw.source_id)
                if source is None:
                    raise ApplicationError("AI_INPUT_INTEGRITY_ERROR", "source is missing")
                related = tuple(
                    sorted(
                        (
                            event_id
                            for event_id, event in event_map.items()
                            if event.information_item_id == item.id
                        ),
                        key=str,
                    )
                )
                documents[raw.id] = AIResearchDocument(
                    information_item_id=item.id,
                    raw_document_id=raw.id,
                    title=item.normalized_title,
                    content=item.normalized_content,
                    source_name=source.display_name,
                    market_event_ids=related,
                )
        if not documents:
            raise ApplicationError("AI_INPUT_EMPTY", "at least one information source is required")
        return LoadedInputs(
            documents=tuple(documents[item] for item in sorted(documents, key=str)),
            raw_document_ids=tuple(sorted(documents, key=str)),
            information_item_ids=frozenset(item_ids),
            event_ids=frozenset(event_ids),
            instrument_ids=tuple(sorted(set(request.instrument_ids), key=str)),
        )

    async def _persist_success(self, run_id: UUID, response: AIProviderResponse) -> AnalysisOutcome:
        output = response.output
        structured_output = output.structured()
        structured_output["provider_warnings"] = list(response.warnings)
        structured_output["usage"] = {
            "input_token_count": response.input_token_count,
            "output_token_count": response.output_token_count,
            "total_token_count": response.total_token_count,
            "estimated_cost": (
                None
                if response.estimated_cost is None
                else format(response.estimated_cost.normalize(), "f")
            ),
            "cost_currency": response.cost_currency,
        }
        async with self._uow_factory() as uow:
            run = await uow.ai_analysis_runs.get_by_id(run_id)
            if run is None:
                raise ApplicationError("AI_ANALYSIS_RUN_NOT_FOUND", "analysis run is missing")
            insight = ResearchInsight(
                analysis_run_id=run.id,
                insight_type=run.analysis_type.value,
                title=output.title,
                summary=output.summary,
                impact_direction=output.impact_direction,
                importance_score=output.importance_score,
                confidence=output.confidence,
                key_facts=output.key_facts,
                uncertainties=tuple((*output.uncertainties, *response.warnings)),
                research_questions=output.research_questions,
                structured_output=structured_output,
            )
            evidence = [
                ResearchEvidence(
                    insight_id=insight.id,
                    information_item_id=item.information_item_id,
                    market_event_id=item.market_event_id,
                    evidence_text=item.evidence_text,
                    evidence_location=item.evidence_location,
                )
                for item in output.evidence_references
            ]
            await uow.research_insights.append(insight)
            await uow.research_evidence.append_many(evidence)
            run.mark_completed(datetime.now(UTC), response)
            await uow.ai_analysis_runs.update(run)
            await uow.commit()
            return AnalysisOutcome(
                run=run, insight=insight, evidence=tuple(evidence), replayed=False
            )

    async def _mark_failed(self, run_id: UUID, code: str, message: str) -> None:
        async with self._uow_factory() as uow:
            run = await uow.ai_analysis_runs.get_by_id(run_id)
            if run is not None:
                run.mark_failed(datetime.now(UTC), code, message)
                await uow.ai_analysis_runs.update(run)
                await uow.commit()

    async def _outcome(
        self, uow: UnitOfWork, run: AIAnalysisRun, *, replayed: bool
    ) -> AnalysisOutcome:
        insight = await uow.research_insights.get_by_run(run.id)
        evidence = (
            [] if insight is None else await uow.research_evidence.list_by_insight(insight.id)
        )
        return AnalysisOutcome(
            run=run, insight=insight, evidence=tuple(evidence), replayed=replayed
        )


class AIResearchQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def run(self, run_id: UUID) -> AnalysisOutcome | None:
        async with self._uow_factory() as uow:
            run = await uow.ai_analysis_runs.get_by_id(run_id)
            if run is None:
                return None
            insight = await uow.research_insights.get_by_run(run.id)
            evidence = (
                [] if insight is None else await uow.research_evidence.list_by_insight(insight.id)
            )
            return AnalysisOutcome(
                run=run, insight=insight, evidence=tuple(evidence), replayed=False
            )

    async def runs(
        self,
        *,
        analysis_type: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[AIAnalysisRun], int]:
        async with self._uow_factory() as uow:
            return await uow.ai_analysis_runs.list(
                analysis_type=analysis_type, status=status, offset=offset, limit=limit
            )

    async def insight(self, insight_id: UUID) -> InsightDetail | None:
        async with self._uow_factory() as uow:
            insight = await uow.research_insights.get_by_id(insight_id)
            if insight is None:
                return None
            run = await uow.ai_analysis_runs.get_by_id(insight.analysis_run_id)
            if run is None:
                raise ApplicationError("AI_INTEGRITY_ERROR", "analysis run is missing")
            evidence = await uow.research_evidence.list_by_insight(insight.id)
            return InsightDetail(insight=insight, run=run, evidence=tuple(evidence))

    async def insights(self, *, offset: int, limit: int) -> tuple[list[ResearchInsight], int]:
        async with self._uow_factory() as uow:
            return await uow.research_insights.list(offset=offset, limit=limit)


class AIResearchIntegrityService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def verify(self, run_id: UUID) -> list[dict[str, str]]:
        async with self._uow_factory() as uow:
            run = await uow.ai_analysis_runs.get_by_id(run_id)
            if run is None:
                raise ApplicationError("AI_ANALYSIS_RUN_NOT_FOUND", "analysis run is missing")
            insight = await uow.research_insights.get_by_run(run.id)
            evidence = (
                [] if insight is None else await uow.research_evidence.list_by_insight(insight.id)
            )
            allowed_items = set()
            for raw_id in run.input_document_ids:
                item = await uow.information_items.get_by_raw_document(raw_id)
                if item is not None:
                    allowed_items.add(item.id)
        issues: list[dict[str, str]] = []
        if run.status is AIAnalysisStatus.COMPLETED and insight is None:
            issues.append({"code": "COMPLETED_WITHOUT_INSIGHT", "message": str(run.id)})
        if run.status is AIAnalysisStatus.FAILED and insight is not None:
            issues.append({"code": "FAILED_WITH_PARTIAL_INSIGHT", "message": str(run.id)})
        if insight is not None and insight.analysis_run_id != run.id:
            issues.append({"code": "INSIGHT_RUN_MISMATCH", "message": str(insight.id)})
        if insight is not None and (
            insight.schema_version != OUTPUT_SCHEMA_VERSION
            or insight.structured_output.get("schema_version") != OUTPUT_SCHEMA_VERSION
        ):
            issues.append({"code": "OUTPUT_SCHEMA_INVALID", "message": str(insight.id)})
        if run.prompt_version != PROMPT_VERSION:
            issues.append({"code": "PROMPT_VERSION_UNKNOWN", "message": run.prompt_version})
        if any(
            value is not None and value < 0
            for value in (run.input_token_count, run.output_token_count)
        ):
            issues.append({"code": "TOKEN_COUNT_INVALID", "message": str(run.id)})
        for evidence_item in evidence:
            if (
                evidence_item.information_item_id is not None
                and evidence_item.information_item_id not in allowed_items
            ) or (
                evidence_item.market_event_id is not None
                and evidence_item.market_event_id not in set(run.input_event_ids)
            ):
                issues.append({"code": "EVIDENCE_OUTSIDE_INPUT", "message": str(evidence_item.id)})
        return issues
