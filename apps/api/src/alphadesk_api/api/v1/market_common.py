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
    "ACCOUNT_NOT_FOUND": 404,
    "CASH_BALANCE_NOT_FOUND": 404,
    "FILL_NOT_FOUND": 404,
    "ORDER_NOT_FOUND": 404,
    "RECONCILIATION_NOT_FOUND": 404,
    "ACCOUNT_CODE_CONFLICT": 409,
    "IDEMPOTENCY_KEY_CONFLICT": 409,
    "INSUFFICIENT_CASH": 409,
    "INSUFFICIENT_POSITION": 409,
    "ACCOUNT_DISABLED": 409,
    "ACCOUNT_NOT_SIMULATED": 409,
    "FILL_INTEGRITY_ERROR": 422,
    "FILL_AMOUNT_MISMATCH": 422,
    "LEDGER_INTEGRITY_ERROR": 500,
    "ORDER_IDEMPOTENCY_CONFLICT": 409,
    "ORDER_ACTION_IDEMPOTENCY_CONFLICT": 409,
    "ORDER_VERSION_CONFLICT": 409,
    "ORDER_ALREADY_CONFIRMED": 409,
    "ORDER_ALREADY_CANCELLED": 409,
    "ORDER_ALREADY_QUEUED": 409,
    "ORDER_COMMAND_ALREADY_EXISTS": 409,
    "OUTBOX_MESSAGE_ALREADY_EXISTS": 409,
    "ORDER_EXPIRED": 409,
    "ORDER_NOT_CONFIRMABLE": 409,
    "ORDER_NOT_CANCELLABLE": 409,
    "ORDER_TERMINAL_STATE": 409,
    "ORDER_ACCOUNT_NOT_ACTIVE": 409,
    "ORDER_ACCOUNT_TYPE_NOT_SUPPORTED": 409,
    "ORDER_INSTRUMENT_NOT_ACTIVE": 409,
    "ORDER_TRANSACTION_FAILED": 500,
    "ORDER_INTEGRITY_MISMATCH": 500,
    "ORDER_INVALID_QUANTITY": 422,
    "ORDER_INVALID_PRICE": 422,
    "ORDER_LOT_SIZE_VIOLATION": 422,
    "ORDER_PRICE_TICK_VIOLATION": 422,
    "ORDER_INVALID_DATETIME": 422,
    "ORDER_INVALID_REQUEST": 422,
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
