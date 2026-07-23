"""Read-only instrument catalog API."""

import re
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
        listed_at=entity.listed_at,
        delisted_at=entity.delisted_at,
        lifecycle_status=(
            "DELISTED" if entity.delisted_at is not None or not entity.is_active else "ACTIVE"
        ),
        updated_at=entity.updated_at,
    )


@router.get("", response_model=InstrumentPageResponse)
async def list_instruments(
    request: Request,
    keyword: str | None = Query(default=None, max_length=100),
    exchange: str | None = Query(default=None, max_length=32),
    market: str | None = Query(default=None, max_length=32),
    asset_type: str | None = Query(default=None, max_length=32),
    is_active: bool | None = True,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
) -> InstrumentPageResponse:
    normalized_keyword = keyword.strip() if keyword else None
    normalized_exchange = exchange
    if normalized_keyword:
        match = re.fullmatch(
            r"(?P<symbol>\d{6})\.(?P<suffix>SH|SSE|SZ|SZSE|BJ|BSE)",
            normalized_keyword,
            flags=re.IGNORECASE,
        )
        if match:
            normalized_keyword = match.group("symbol")
            normalized_exchange = {
                "SH": "SSE",
                "SSE": "SSE",
                "SZ": "SZSE",
                "SZSE": "SZSE",
                "BJ": "BSE",
                "BSE": "BSE",
            }[match.group("suffix").upper()]
    maximum = request.app.state.settings.instrument_page_size_max
    settings = request.app.state.settings
    if page_size > maximum:
        page_size = maximum
    items, total = await InstrumentCatalogService(uow_factory(request)).search(
        keyword=normalized_keyword,
        exchange=normalized_exchange,
        market=market,
        asset_type=asset_type,
        is_active=is_active,
        page=page,
        page_size=page_size,
        source_code=(
            None
            if settings.environment == "test" or is_active is False
            else settings.authoritative_market_source
        ),
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
