"""Audited single-user watchlist API."""

from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from alphadesk_api.api.v1.instruments import instrument_response
from alphadesk_api.api.v1.market_common import (
    request_correlation_id,
    to_app_error,
    uow_factory,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.watchlists import WatchlistService
from alphadesk_api.schemas.market import (
    WatchlistCreateRequest,
    WatchlistDetailResponse,
    WatchlistItemCreateRequest,
    WatchlistItemResponse,
    WatchlistItemUpdateRequest,
    WatchlistReorderRequest,
    WatchlistResponse,
    WatchlistUpdateRequest,
)
from alphadesk_domain.entities import Watchlist

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


def watchlist_response(entity: Watchlist) -> WatchlistResponse:
    return WatchlistResponse(
        id=entity.id,
        name=entity.name,
        description=entity.description,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def service(request: Request) -> WatchlistService:
    return WatchlistService(
        uow_factory(request), item_limit=request.app.state.settings.watchlist_item_limit
    )


@router.get("", response_model=list[WatchlistResponse])
async def list_watchlists(request: Request) -> list[WatchlistResponse]:
    return [watchlist_response(item) for item in await service(request).list_all()]


@router.post("", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
async def create_watchlist(request: Request, payload: WatchlistCreateRequest) -> WatchlistResponse:
    try:
        entity = await service(request).create(
            name=payload.name,
            description=payload.description,
            correlation_id=request_correlation_id(request),
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return watchlist_response(entity)


@router.get("/{watchlist_id}", response_model=WatchlistDetailResponse)
async def get_watchlist(request: Request, watchlist_id: UUID) -> WatchlistDetailResponse:
    try:
        entity, items = await service(request).detail(watchlist_id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    base = watchlist_response(entity)
    return WatchlistDetailResponse(
        **base.model_dump(),
        items=[
            WatchlistItemResponse(
                id=item.id,
                watchlist_id=item.watchlist_id,
                instrument=instrument_response(instrument),
                sort_order=item.sort_order,
                note=item.note,
                created_at=item.created_at,
            )
            for item, instrument in items
        ],
    )


@router.patch("/{watchlist_id}", response_model=WatchlistResponse)
async def update_watchlist(
    request: Request, watchlist_id: UUID, payload: WatchlistUpdateRequest
) -> WatchlistResponse:
    try:
        entity = await service(request).update(
            watchlist_id,
            name=payload.name,
            description=payload.description,
            correlation_id=request_correlation_id(request),
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return watchlist_response(entity)


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(request: Request, watchlist_id: UUID) -> Response:
    try:
        await service(request).delete(watchlist_id, request_correlation_id(request))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{watchlist_id}/items",
    response_model=WatchlistItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_watchlist_item(
    request: Request, watchlist_id: UUID, payload: WatchlistItemCreateRequest
) -> WatchlistItemResponse:
    try:
        item = await service(request).add_item(
            watchlist_id,
            instrument_id=payload.instrument_id,
            note=payload.note,
            correlation_id=request_correlation_id(request),
        )
        _, detailed = await service(request).detail(watchlist_id)
        instrument = next(value for current, value in detailed if current.id == item.id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return WatchlistItemResponse(
        id=item.id,
        watchlist_id=item.watchlist_id,
        instrument=instrument_response(instrument),
        sort_order=item.sort_order,
        note=item.note,
        created_at=item.created_at,
    )


@router.patch("/{watchlist_id}/items/{item_id}", response_model=WatchlistItemResponse)
async def update_watchlist_item(
    request: Request,
    watchlist_id: UUID,
    item_id: UUID,
    payload: WatchlistItemUpdateRequest,
) -> WatchlistItemResponse:
    try:
        item = await service(request).update_item(
            watchlist_id,
            item_id,
            note=payload.note,
            correlation_id=request_correlation_id(request),
        )
        _, detailed = await service(request).detail(watchlist_id)
        instrument = next(value for current, value in detailed if current.id == item.id)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return WatchlistItemResponse(
        id=item.id,
        watchlist_id=item.watchlist_id,
        instrument=instrument_response(instrument),
        sort_order=item.sort_order,
        note=item.note,
        created_at=item.created_at,
    )


@router.delete("/{watchlist_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist_item(request: Request, watchlist_id: UUID, item_id: UUID) -> Response:
    try:
        await service(request).remove_item(watchlist_id, item_id, request_correlation_id(request))
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{watchlist_id}/items/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_watchlist_items(
    request: Request, watchlist_id: UUID, payload: WatchlistReorderRequest
) -> Response:
    try:
        await service(request).reorder(
            watchlist_id, payload.item_ids, request_correlation_id(request)
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
