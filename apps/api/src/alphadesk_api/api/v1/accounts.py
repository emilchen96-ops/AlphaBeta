"""M04 simulated-account APIs; no order or fill write endpoints are exposed."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel

from alphadesk_api.api.v1.market_common import (
    request_correlation_id,
    to_app_error,
    uow_factory,
)
from alphadesk_api.application.accounting import (
    AccountQueryService,
    AccountReconciliationService,
    AccountValuationService,
    CashFundingService,
    SimulatedAccountService,
)
from alphadesk_api.application.common import ApplicationError
from alphadesk_api.application.market_data import MarketDataQueryService
from alphadesk_api.schemas.accounting import (
    AccountCreateRequest,
    AccountDetailResponse,
    AccountResponse,
    AccountSnapshotResponse,
    AccountSummaryResponse,
    AccountUpdateRequest,
    CashBalanceResponse,
    CashLedgerEntryResponse,
    FundingRequest,
    LedgerTransactionResponse,
    PageResponse,
    PositionLedgerEntryResponse,
    PositionResponse,
    ReconciliationResponse,
)
from alphadesk_domain.enums import AccountStatus, AccountType

router = APIRouter(prefix="/accounts", tags=["simulated-accounts"])


def _validated[ResponseT: BaseModel](response_type: type[ResponseT], entity: object) -> ResponseT:
    return response_type.model_validate(entity)


def _page(items: list[BaseModel], page: int, page_size: int, total: int) -> PageResponse:
    return PageResponse(items=items, page=page, page_size=page_size, total=total)


def _offset(page: int, page_size: int) -> int:
    return (page - 1) * page_size


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(request: Request, body: AccountCreateRequest) -> AccountResponse:
    try:
        account = await SimulatedAccountService(uow_factory(request)).create(
            **body.model_dump(), correlation_id=request_correlation_id(request)
        )
        return _validated(AccountResponse, account)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("", response_model=PageResponse)
async def list_accounts(
    request: Request,
    account_status: Annotated[AccountStatus | None, Query(alias="status")] = None,
    account_type: Annotated[AccountType, Query()] = AccountType.SIMULATED,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResponse:
    if account_type is not AccountType.SIMULATED:
        raise to_app_error(ApplicationError("ACCOUNT_NOT_SIMULATED", "M04 只返回模拟账户"))
    accounts = await SimulatedAccountService(uow_factory(request)).list_all()
    if account_status is not None:
        accounts = [item for item in accounts if item.status is account_status]
    total = len(accounts)
    items = accounts[_offset(page, page_size) : _offset(page, page_size) + page_size]
    return _page([_validated(AccountResponse, item) for item in items], page, page_size, total)


@router.get("/{account_id}", response_model=AccountDetailResponse)
async def get_account(request: Request, account_id: UUID) -> AccountDetailResponse:
    try:
        account, balances, positions = await AccountQueryService(uow_factory(request)).detail(
            account_id
        )
        return AccountDetailResponse(
            **_validated(AccountResponse, account).model_dump(),
            cash_balances=[_validated(CashBalanceResponse, item) for item in balances],
            positions=[_validated(PositionResponse, item) for item in positions],
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(
    request: Request, account_id: UUID, body: AccountUpdateRequest
) -> AccountResponse:
    try:
        account = await SimulatedAccountService(uow_factory(request)).update(
            account_id=account_id,
            **body.model_dump(),
            correlation_id=request_correlation_id(request),
        )
        return _validated(AccountResponse, account)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


async def _fund(
    request: Request, account_id: UUID, body: FundingRequest, *, deposit: bool
) -> LedgerTransactionResponse:
    try:
        transaction = await CashFundingService(uow_factory(request)).post(
            account_id=account_id,
            amount=body.amount,
            is_deposit=deposit,
            idempotency_key=body.idempotency_key,
            description=body.description,
            correlation_id=request_correlation_id(request),
        )
        return _validated(LedgerTransactionResponse, transaction)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/{account_id}/deposits", response_model=LedgerTransactionResponse)
async def deposit(
    request: Request, account_id: UUID, body: FundingRequest
) -> LedgerTransactionResponse:
    return await _fund(request, account_id, body, deposit=True)


@router.post("/{account_id}/withdrawals", response_model=LedgerTransactionResponse)
async def withdraw(
    request: Request, account_id: UUID, body: FundingRequest
) -> LedgerTransactionResponse:
    return await _fund(request, account_id, body, deposit=False)


@router.get("/{account_id}/transactions", response_model=PageResponse)
async def transactions(
    request: Request,
    account_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResponse:
    try:
        items, total = await AccountQueryService(uow_factory(request)).transactions(
            account_id, _offset(page, page_size), page_size
        )
        return _page(
            [_validated(LedgerTransactionResponse, item) for item in items],
            page,
            page_size,
            total,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{account_id}/cash-ledger", response_model=PageResponse)
async def cash_ledger(
    request: Request,
    account_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResponse:
    try:
        items, total = await AccountQueryService(uow_factory(request)).cash_ledger(
            account_id, _offset(page, page_size), page_size
        )
        return _page(
            [_validated(CashLedgerEntryResponse, item) for item in items],
            page,
            page_size,
            total,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{account_id}/positions", response_model=list[PositionResponse])
async def positions(request: Request, account_id: UUID) -> list[PositionResponse]:
    try:
        _, _, items = await AccountQueryService(uow_factory(request)).detail(account_id)
        return [_validated(PositionResponse, item) for item in items]
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{account_id}/position-ledger", response_model=PageResponse)
async def position_ledger(
    request: Request,
    account_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResponse:
    try:
        items, total = await AccountQueryService(uow_factory(request)).position_ledger(
            account_id, _offset(page, page_size), page_size
        )
        return _page(
            [_validated(PositionLedgerEntryResponse, item) for item in items],
            page,
            page_size,
            total,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/{account_id}/valuation-snapshots", response_model=AccountSnapshotResponse)
async def create_valuation_snapshot(request: Request, account_id: UUID) -> AccountSnapshotResponse:
    settings = request.app.state.settings
    market_data = MarketDataQueryService(
        uow_factory(request), minute_stale_seconds=settings.market_minute_stale_seconds
    )
    try:
        result = await AccountValuationService(uow_factory(request), market_data).value(
            account_id=account_id, correlation_id=request_correlation_id(request)
        )
        return _validated(AccountSnapshotResponse, result.snapshot)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{account_id}/valuation-snapshots", response_model=PageResponse)
async def valuation_snapshots(
    request: Request,
    account_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResponse:
    try:
        items, total = await AccountQueryService(uow_factory(request)).snapshots(
            account_id, _offset(page, page_size), page_size
        )
        return _page(
            [_validated(AccountSnapshotResponse, item) for item in items],
            page,
            page_size,
            total,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{account_id}/summary", response_model=AccountSummaryResponse)
async def summary(request: Request, account_id: UUID) -> AccountSummaryResponse:
    try:
        account, balances, positions_, snapshot, reconciliation = await AccountQueryService(
            uow_factory(request)
        ).summary(account_id)
        return AccountSummaryResponse(
            account=_validated(AccountResponse, account),
            cash_balances=[_validated(CashBalanceResponse, item) for item in balances],
            positions=[_validated(PositionResponse, item) for item in positions_],
            latest_snapshot=(
                None if snapshot is None else _validated(AccountSnapshotResponse, snapshot)
            ),
            latest_reconciliation=(
                None
                if reconciliation is None
                else _validated(ReconciliationResponse, reconciliation)
            ),
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.post("/{account_id}/reconciliations", response_model=ReconciliationResponse)
async def reconcile(request: Request, account_id: UUID) -> ReconciliationResponse:
    try:
        result = await AccountReconciliationService(uow_factory(request)).run(
            account_id=account_id, correlation_id=request_correlation_id(request)
        )
        return _validated(ReconciliationResponse, result.run)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{account_id}/reconciliations", response_model=PageResponse)
async def reconciliations(
    request: Request,
    account_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResponse:
    try:
        items, total = await AccountQueryService(uow_factory(request)).reconciliations(
            account_id, _offset(page, page_size), page_size
        )
        return _page(
            [_validated(ReconciliationResponse, item) for item in items],
            page,
            page_size,
            total,
        )
    except ApplicationError as exc:
        raise to_app_error(exc) from exc


@router.get("/{account_id}/reconciliations/latest", response_model=ReconciliationResponse)
async def latest_reconciliation(request: Request, account_id: UUID) -> ReconciliationResponse:
    try:
        _, _, _, _, reconciliation = await AccountQueryService(uow_factory(request)).summary(
            account_id
        )
        if reconciliation is None:
            raise ApplicationError("RECONCILIATION_NOT_FOUND", "账户尚无核对记录")
        return _validated(ReconciliationResponse, reconciliation)
    except ApplicationError as exc:
        raise to_app_error(exc) from exc
