"""Read-only instrument catalog API."""

from uuid import UUID

from fastapi import APIRouter, Query, Request

from alphadesk_api.api.v1.market_common import to_app_error, uow_factory
from alphadesk_api.application.catalog import InstrumentCatalogService
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.schemas.market import (
    InstrumentDetailResponse,
    InstrumentMappingResponse,
    InstrumentPageResponse,
    InstrumentResponse,
)
from alphadesk_domain.entities import Instrument

router = APIRouter(prefix="/instruments", tags=["instruments"])


def instrument_response(entity: Instrument) -> InstrumentResponse:
    return InstrumentResponse(
        id=entity.id,
        symbol=entity.symbol,
        exchange=entity.exchange,
        market=entity.market,
        name=entity.name,
        asset_type=entity.asset_type,
        currency=entity.currency,
        lot_size=entity.lot_size,
        price_tick=entity.price_tick,
        timezone=entity.timezone,
        is_active=entity.is_active,
        updated_at=entity.updated_at,
    )


@router.get("", response_model=InstrumentPageResponse)
async def list_instruments(
    request: Request,
    keyword: str | None = Query(default=None, max_length=100),
    exchange: str | None = Query(default=None, max_length=32),
    market: str | None = Query(default=None, max_length=32),
    asset_type: str | None = Query(default=None, max_length=32),
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
) -> InstrumentPageResponse:
    maximum = request.app.state.settings.instrument_page_size_max
    if page_size > maximum:
        page_size = maximum
    items, total = await InstrumentCatalogService(uow_factory(request)).search(
        keyword=keyword,
        exchange=exchange,
        market=market,
        asset_type=asset_type,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return InstrumentPageResponse(
        items=[instrument_response(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{instrument_id}", response_model=InstrumentDetailResponse)
async def get_instrument(request: Request, instrument_id: UUID) -> InstrumentDetailResponse:
    try:
        entity, mappings = await InstrumentCatalogService(uow_factory(request)).get(instrument_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    base = instrument_response(entity)
    return InstrumentDetailResponse(
        **base.model_dump(),
        mappings=[
            InstrumentMappingResponse(
                source_id=mapping.source_id,
                external_symbol=mapping.external_symbol,
                external_exchange=mapping.external_exchange,
                is_primary=mapping.is_primary,
            )
            for mapping in mappings
        ],
    )
