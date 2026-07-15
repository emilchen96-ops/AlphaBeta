"""Route helpers for M03 application services."""

from typing import cast
from uuid import UUID

from fastapi import Request

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory, correlation_uuid
from alphadesk_api.core.errors import AppError
from alphadesk_api.infrastructure.database import DatabaseService

ERROR_STATUS = {
    "INSTRUMENT_NOT_FOUND": 404,
    "WATCHLIST_NOT_FOUND": 404,
    "WATCHLIST_ITEM_NOT_FOUND": 404,
    "MARKET_SOURCE_NOT_FOUND": 404,
    "MARKET_DATA_NOT_FOUND": 404,
    "WATCHLIST_NAME_CONFLICT": 409,
    "WATCHLIST_ITEM_ALREADY_EXISTS": 409,
    "WATCHLIST_LIMIT_EXCEEDED": 409,
    "WATCHLIST_REORDER_INVALID": 422,
    "WATCHLIST_NOTE_TOO_LONG": 422,
    "MARKET_SOURCE_DISABLED": 409,
    "MARKET_DATA_INVALID_RANGE": 422,
    "MARKET_DATA_LIMIT_EXCEEDED": 422,
    "MARKET_DATA_VALIDATION_FAILED": 422,
    "MARKET_SYNC_FAILED": 502,
}


def uow_factory(request: Request) -> UnitOfWorkFactory:
    database = cast(DatabaseService, request.app.state.database)
    return cast(UnitOfWorkFactory, database.unit_of_work)


def request_correlation_id(request: Request) -> UUID:
    return correlation_uuid(getattr(request.state, "correlation_id", None))


def to_app_error(exc: ApplicationError) -> AppError:
    return AppError(
        code=exc.code,
        message=exc.message,
        status_code=ERROR_STATUS.get(exc.code, 400),
    )
