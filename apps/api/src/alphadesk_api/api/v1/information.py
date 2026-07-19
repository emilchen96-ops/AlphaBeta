"""N01 information source, item and market-event endpoints."""

from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from alphadesk_api.api.v1.market_common import request_correlation_id, to_app_error, uow_factory
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.information import (
    InformationDetail,
    InformationIngestionService,
    InformationIntegrityService,
    InformationQueryService,
    ManualInformationRequest,
    ThemeInput,
)
from alphadesk_api.schemas.information import (
    InformationDetailResponse,
    InformationIngestionRunResponse,
    InformationIntegrityResponse,
    InformationPageResponse,
    InformationSourceResponse,
    ManualInformationBody,
)
from alphadesk_domain.information import InformationSource, MarketEventDirection, MarketEventType

router = APIRouter(tags=["information-center"])


def source_response(source: InformationSource) -> InformationSourceResponse:
    return InformationSourceResponse(
        source_id=source.id,
        source_key=source.source_key,
        display_name=source.display_name,
        source_type=source.source_type.value,
        base_url=source.base_url,
        enabled=source.enabled,
        configuration=source.configuration,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def detail_response(
    detail: InformationDetail, *, duplicate: bool = False
) -> InformationDetailResponse:
    return InformationDetailResponse(
        item_id=detail.item.id,
        raw_document_id=detail.raw_document.id,
        event_id=detail.event.id,
        source=source_response(detail.source),
        title=detail.item.normalized_title,
        content=detail.item.normalized_content,
        raw_title=detail.raw_document.title,
        raw_content=detail.raw_document.raw_content,
        source_url=detail.raw_document.source_url,
        published_at=detail.item.published_at,
        received_at=detail.item.received_at,
        event_type=detail.event.event_type.value,
        direction=detail.event.direction.value,
        summary=detail.event.summary,
        importance=(
            None
            if detail.event.importance is None
            else format(detail.event.importance.normalize(), "f")
        ),
        status=detail.item.status.value,
        instruments=[
            {
                "instrument_id": str(item.id),
                "symbol": item.symbol,
                "exchange": item.exchange,
                "name": item.name,
            }
            for item in detail.instruments
        ],
        themes=[
            {"theme_key": item.theme_key, "theme_name": item.theme_name}
            for item in detail.theme_links
        ],
        duplicate=duplicate,
        capabilities={
            "ai_analyzed": False,
            "facts_verified": False,
            "creates_signals": False,
            "creates_orders": False,
            "modifies_portfolio": False,
        },
    )


def decimal_or_none(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ApplicationError("INFORMATION_INVALID_IMPORTANCE", "importance is invalid") from exc
    if not parsed.is_finite():
        raise ApplicationError("INFORMATION_INVALID_IMPORTANCE", "importance must be finite")
    return parsed


@router.get("/information-sources", response_model=list[InformationSourceResponse])
async def list_information_sources(request: Request) -> list[InformationSourceResponse]:
    values = await InformationQueryService(uow_factory(request)).sources()
    return [source_response(item) for item in values]


@router.post(
    "/information/manual",
    response_model=InformationDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_manual_information(
    request: Request, body: ManualInformationBody
) -> InformationDetailResponse:
    try:
        try:
            event_type = MarketEventType(body.event_type)
            direction = MarketEventDirection(body.direction)
        except ValueError as exc:
            raise ApplicationError(
                "INFORMATION_INVALID_EVENT", "event type or direction invalid"
            ) from exc
        outcome = await InformationIngestionService(uow_factory(request)).add_manual(
            ManualInformationRequest(
                source_name=body.source_name,
                title=body.title,
                content=body.content,
                source_url=body.source_url,
                published_at=body.published_at,
                instrument_ids=tuple(body.instrument_ids),
                themes=tuple(
                    ThemeInput(theme_key=item.theme_key, theme_name=item.theme_name)
                    for item in body.themes
                ),
                event_type=event_type,
                direction=direction,
                summary=body.summary,
                importance=decimal_or_none(body.importance),
                correlation_id=request_correlation_id(request),
            )
        )
        detail = await InformationQueryService(uow_factory(request)).item(outcome.item.id)
        if detail is None:
            raise ApplicationError("INFORMATION_INTEGRITY_ERROR", "created item is missing")
        return detail_response(detail, duplicate=outcome.duplicate)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post(
    "/information-sources/{source_id}/ingest",
    response_model=InformationIngestionRunResponse,
)
async def ingest_information_source(
    request: Request, source_id: UUID
) -> InformationIngestionRunResponse:
    try:
        run = await InformationIngestionService(uow_factory(request)).ingest_source(
            source_id, request_correlation_id(request)
        )
        return InformationIngestionRunResponse(
            ingestion_run_id=run.id,
            source_id=run.source_id,
            status=run.status.value,
            fetched_count=run.fetched_count,
            inserted_count=run.inserted_count,
            duplicate_count=run.duplicate_count,
            failed_count=run.failed_count,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error_summary=run.error_summary,
            correlation_id=run.correlation_id,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/information-items", response_model=InformationPageResponse)
async def list_information_items(
    request: Request,
    search: str | None = None,
    source_id: UUID | None = None,
    instrument_id: UUID | None = None,
    theme_key: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> InformationPageResponse:
    values, total = await InformationQueryService(uow_factory(request)).items(
        search=search,
        source_id=source_id,
        instrument_id=instrument_id,
        theme_key=theme_key,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return InformationPageResponse(
        items=[detail_response(item) for item in values],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/information-items/{item_id}", response_model=InformationDetailResponse)
async def get_information_item(request: Request, item_id: UUID) -> InformationDetailResponse:
    detail = await InformationQueryService(uow_factory(request)).item(item_id)
    if detail is None:
        raise to_app_error(ApplicationError("INFORMATION_ITEM_NOT_FOUND", "item does not exist"))
    return detail_response(detail)


@router.get("/market-events", response_model=InformationPageResponse)
async def list_market_events(
    request: Request,
    event_type: str | None = None,
    direction: str | None = None,
    instrument_id: UUID | None = None,
    theme_key: str | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> InformationPageResponse:
    values, total = await InformationQueryService(uow_factory(request)).events(
        event_type=event_type,
        direction=direction,
        instrument_id=instrument_id,
        theme_key=theme_key,
        search=search,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return InformationPageResponse(
        items=[detail_response(item) for item in values],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/market-events/{event_id}", response_model=InformationDetailResponse)
async def get_market_event(request: Request, event_id: UUID) -> InformationDetailResponse:
    detail = await InformationQueryService(uow_factory(request)).event(event_id)
    if detail is None:
        raise to_app_error(ApplicationError("MARKET_EVENT_NOT_FOUND", "event does not exist"))
    return detail_response(detail)


@router.get("/information-items/{item_id}/integrity", response_model=InformationIntegrityResponse)
async def information_integrity(request: Request, item_id: UUID) -> InformationIntegrityResponse:
    try:
        issues = await InformationIntegrityService(uow_factory(request)).verify_item(item_id)
        return InformationIntegrityResponse(item_id=item_id, valid=not issues, issues=issues)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
