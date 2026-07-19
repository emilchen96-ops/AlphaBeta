"""M04 simulated-account, ledger, valuation and reconciliation services."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from alphadesk_api.application.common import (
    ApplicationError,
    UnitOfWorkFactory,
    append_event_and_audit,
)
from alphadesk_api.application.market_data import MarketDataQueryService
from alphadesk_domain.accounting import (
    AccountReconciliationResult,
    AccountReconciliationRun,
    AccountSnapshot,
    AccountValuationResult,
    CashBalance,
    CashLedgerEntry,
    FillAccountingResult,
    LedgerTransaction,
    PositionLedgerEntry,
    assert_fill_amounts,
    calculate_fill_amounts,
)
from alphadesk_domain.entities import Fill, Position, TradingAccount
from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    AccountValuationStatus,
    AdjustmentType,
    CashLedgerEntryType,
    LedgerTransactionStatus,
    LedgerTransactionType,
    MarketDataQualityStatus,
    MarketTimeframe,
    OrderSide,
    PositionLedgerEntryType,
    ReconciliationStatus,
    SettlementPolicy,
)
from alphadesk_domain.unit_of_work import UnitOfWork

ZERO = Decimal("0")
AMOUNT_TOLERANCE = Decimal("0.00000001")


def _now() -> datetime:
    return datetime.now(UTC)


async def _require_account(uow: UnitOfWork, account_id: UUID) -> TradingAccount:
    account = await uow.accounts.get_by_id(account_id)
    if account is None:
        raise ApplicationError("ACCOUNT_NOT_FOUND", "模拟账户不存在")
    if account.account_type is not AccountType.SIMULATED:
        raise ApplicationError("ACCOUNT_NOT_SIMULATED", "M04 只允许操作模拟账户")
    return account


class SimulatedAccountService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def create(
        self,
        *,
        account_code: str,
        name: str,
        base_currency: str,
        initial_cash: Decimal,
        settlement_policy: SettlementPolicy,
        idempotency_key: str,
        correlation_id: UUID,
    ) -> TradingAccount:
        if initial_cash < ZERO:
            raise ApplicationError("INVALID_AMOUNT", "初始资金不能为负数")
        async with self._uow_factory() as uow:
            existing = await uow.accounts.get_by_creation_idempotency_key(idempotency_key)
            if existing is not None:
                if (
                    existing.account_code != account_code
                    or existing.name != name
                    or existing.base_currency != base_currency.upper()
                    or existing.settlement_policy is not settlement_policy
                ):
                    raise ApplicationError(
                        "IDEMPOTENCY_KEY_CONFLICT", "幂等键已被不同的账户请求使用"
                    )
                return existing
            if await uow.accounts.get_by_business_key(account_code) is not None:
                raise ApplicationError("ACCOUNT_CODE_CONFLICT", "账户编码已存在")
            now = _now()
            account = TradingAccount(
                account_code=account_code,
                name=name,
                account_type=AccountType.SIMULATED,
                status=AccountStatus.ACTIVE,
                broker_type="SIMULATED",
                base_currency=base_currency,
                settlement_policy=settlement_policy,
                creation_idempotency_key=idempotency_key,
                metadata={"scope": "M04", "real_trading": False},
                created_at=now,
                updated_at=now,
            )
            await uow.accounts.add(account)
            balance = CashBalance(
                account_id=account.id,
                currency=account.base_currency,
                total_cash=initial_cash,
                available_cash=initial_cash,
                frozen_cash=ZERO,
                as_of=now,
                created_at=now,
                updated_at=now,
            )
            await uow.cash_balances.add(balance)
            if initial_cash > ZERO:
                transaction = LedgerTransaction(
                    account_id=account.id,
                    transaction_type=LedgerTransactionType.INITIAL_DEPOSIT,
                    status=LedgerTransactionStatus.POSTED,
                    business_key=f"account:{account.id}:initial:{idempotency_key}",
                    correlation_id=correlation_id,
                    occurred_at=now,
                    posted_at=now,
                    description="模拟账户初始入金",
                    metadata={"scope": "M04"},
                )
                await uow.ledger_transactions.add(transaction)
                await uow.cash_ledger.append(
                    CashLedgerEntry(
                        ledger_transaction_id=transaction.id,
                        account_id=account.id,
                        currency=account.base_currency,
                        entry_type=CashLedgerEntryType.INITIAL_DEPOSIT,
                        total_delta=initial_cash,
                        available_delta=initial_cash,
                        frozen_delta=ZERO,
                        total_cash_after=initial_cash,
                        available_cash_after=initial_cash,
                        frozen_cash_after=ZERO,
                        correlation_id=correlation_id,
                        occurred_at=now,
                        metadata={"scope": "M04"},
                    )
                )
            await append_event_and_audit(
                uow,
                event_type="SIMULATED_ACCOUNT_CREATED",
                entity_type="TRADING_ACCOUNT",
                entity_id=account.id,
                correlation_id=correlation_id,
                payload={"account_code": account.account_code},
                source="ALPHADESK_M04",
            )
            await uow.commit()
            return account

    async def list_all(self) -> list[TradingAccount]:
        async with self._uow_factory() as uow:
            return [
                item
                for item in await uow.accounts.list_all()
                if item.account_type is AccountType.SIMULATED
            ]

    async def get(self, account_id: UUID) -> TradingAccount:
        async with self._uow_factory() as uow:
            return await _require_account(uow, account_id)

    async def update(
        self,
        *,
        account_id: UUID,
        name: str | None,
        status: AccountStatus | None,
        settlement_policy: SettlementPolicy | None,
        correlation_id: UUID,
    ) -> TradingAccount:
        async with self._uow_factory() as uow:
            account = await _require_account(uow, account_id)
            if status not in (None, AccountStatus.ACTIVE, AccountStatus.SUSPENDED):
                raise ApplicationError("ACCOUNT_STATUS_INVALID", "只允许启用或停用模拟账户")
            updated = replace(
                account,
                name=account.name if name is None else name,
                status=account.status if status is None else status,
                settlement_policy=(
                    account.settlement_policy if settlement_policy is None else settlement_policy
                ),
                updated_at=_now(),
            )
            await uow.accounts.update(updated)
            await append_event_and_audit(
                uow,
                event_type="SIMULATED_ACCOUNT_UPDATED",
                entity_type="TRADING_ACCOUNT",
                entity_id=updated.id,
                correlation_id=correlation_id,
                payload={"status": updated.status.value},
                source="ALPHADESK_M04",
            )
            await uow.commit()
            return updated


class AccountQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def detail(
        self, account_id: UUID
    ) -> tuple[TradingAccount, list[CashBalance], list[Position]]:
        async with self._uow_factory() as uow:
            account = await _require_account(uow, account_id)
            return (
                account,
                await uow.cash_balances.list_for_account(account_id),
                await uow.positions.list_for_account(account_id),
            )

    async def transactions(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[LedgerTransaction], int]:
        async with self._uow_factory() as uow:
            await _require_account(uow, account_id)
            return await uow.ledger_transactions.list_for_account(account_id, offset, limit)

    async def cash_ledger(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[CashLedgerEntry], int]:
        async with self._uow_factory() as uow:
            await _require_account(uow, account_id)
            return await uow.cash_ledger.list_for_account(account_id, offset, limit)

    async def position_ledger(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[PositionLedgerEntry], int]:
        async with self._uow_factory() as uow:
            await _require_account(uow, account_id)
            return await uow.position_ledger.list_for_account(account_id, offset, limit)

    async def snapshots(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[AccountSnapshot], int]:
        async with self._uow_factory() as uow:
            await _require_account(uow, account_id)
            return await uow.account_snapshots.list_for_account(account_id, offset, limit)

    async def reconciliations(
        self, account_id: UUID, offset: int, limit: int
    ) -> tuple[list[AccountReconciliationRun], int]:
        async with self._uow_factory() as uow:
            await _require_account(uow, account_id)
            return await uow.account_reconciliations.list_for_account(account_id, offset, limit)

    async def summary(
        self, account_id: UUID
    ) -> tuple[
        TradingAccount,
        list[CashBalance],
        list[Position],
        AccountSnapshot | None,
        AccountReconciliationRun | None,
    ]:
        async with self._uow_factory() as uow:
            account = await _require_account(uow, account_id)
            return (
                account,
                await uow.cash_balances.list_for_account(account_id),
                await uow.positions.list_for_account(account_id),
                await uow.account_snapshots.latest(account_id),
                await uow.account_reconciliations.latest(account_id),
            )


class CashFundingService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def post(
        self,
        *,
        account_id: UUID,
        amount: Decimal,
        is_deposit: bool,
        idempotency_key: str,
        correlation_id: UUID,
        description: str | None = None,
    ) -> LedgerTransaction:
        if amount <= ZERO:
            raise ApplicationError("INVALID_AMOUNT", "金额必须大于零")
        kind = "deposit" if is_deposit else "withdrawal"
        business_key = f"funding:{account_id}:{kind}:{idempotency_key}"
        async with self._uow_factory() as uow:
            account = await _require_account(uow, account_id)
            existing = await uow.ledger_transactions.get_by_business_key(business_key)
            if existing is not None:
                entry = await uow.cash_ledger.get_for_transaction(existing.id)
                expected = amount if is_deposit else -amount
                if entry is None or entry.total_delta != expected:
                    raise ApplicationError(
                        "IDEMPOTENCY_KEY_CONFLICT", "幂等键已被不同的资金请求使用"
                    )
                return existing
            balance = await uow.cash_balances.get_for_update(account_id, account.base_currency)
            if balance is None:
                raise ApplicationError("CASH_BALANCE_NOT_FOUND", "账户资金余额不存在")
            existing = await uow.ledger_transactions.get_by_business_key(business_key)
            if existing is not None:
                return existing
            delta = amount if is_deposit else -amount
            if not is_deposit and balance.available_cash < amount:
                raise ApplicationError("INSUFFICIENT_CASH", "可用资金不足")
            now = _now()
            updated = replace(
                balance,
                total_cash=balance.total_cash + delta,
                available_cash=balance.available_cash + delta,
                row_version=balance.row_version + 1,
                as_of=now,
                updated_at=now,
            )
            transaction = LedgerTransaction(
                account_id=account_id,
                transaction_type=(
                    LedgerTransactionType.DEPOSIT
                    if is_deposit
                    else LedgerTransactionType.WITHDRAWAL
                ),
                status=LedgerTransactionStatus.POSTED,
                business_key=business_key,
                correlation_id=correlation_id,
                occurred_at=now,
                posted_at=now,
                description=description,
                metadata={"idempotency_key": idempotency_key, "scope": "M04"},
            )
            await uow.cash_balances.update(updated)
            await uow.ledger_transactions.add(transaction)
            await uow.cash_ledger.append(
                CashLedgerEntry(
                    ledger_transaction_id=transaction.id,
                    account_id=account_id,
                    currency=account.base_currency,
                    entry_type=(
                        CashLedgerEntryType.DEPOSIT
                        if is_deposit
                        else CashLedgerEntryType.WITHDRAWAL
                    ),
                    total_delta=delta,
                    available_delta=delta,
                    frozen_delta=ZERO,
                    total_cash_after=updated.total_cash,
                    available_cash_after=updated.available_cash,
                    frozen_cash_after=updated.frozen_cash,
                    correlation_id=correlation_id,
                    occurred_at=now,
                    metadata={"scope": "M04"},
                )
            )
            await append_event_and_audit(
                uow,
                event_type="CASH_DEPOSIT_POSTED" if is_deposit else "CASH_WITHDRAWAL_POSTED",
                entity_type="LEDGER_TRANSACTION",
                entity_id=transaction.id,
                correlation_id=correlation_id,
                payload={"account_id": str(account_id), "amount": str(amount)},
                source="ALPHADESK_M04",
            )
            await uow.commit()
            return transaction


class FillAccountingService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._failure_injector = failure_injector or (lambda _: None)

    async def apply(self, *, fill_id: UUID) -> FillAccountingResult:
        async with self._uow_factory() as uow:
            result = await self.apply_in_uow(uow=uow, fill_id=fill_id)
            await uow.commit()
            return result

    async def apply_in_uow(self, *, uow: UnitOfWork, fill_id: UUID) -> FillAccountingResult:
        """Post one Fill using the caller's transaction without committing it."""

        fill = await uow.fills.get_by_id(fill_id)
        if fill is None:
            raise ApplicationError("FILL_NOT_FOUND", "成交事实不存在")
        order = await uow.orders.get_by_id(fill.order_id)
        if order is None:
            raise ApplicationError("ORDER_NOT_FOUND", "成交关联订单不存在")
        if order.account_id != fill.account_id or order.instrument_id != fill.instrument_id:
            raise ApplicationError("FILL_INTEGRITY_ERROR", "成交与订单归属不一致")
        existing = await uow.ledger_transactions.get_by_fill_id(fill.id)
        if existing is not None:
            return await self._existing_result(uow, fill, existing)
        account = await _require_account(uow, fill.account_id)
        if account.status is not AccountStatus.ACTIVE:
            raise ApplicationError("ACCOUNT_DISABLED", "模拟账户已停用")
        calculated = calculate_fill_amounts(
            quantity=fill.quantity,
            price=fill.price,
            commission=fill.commission,
            tax=fill.tax,
            other_fee=fill.other_fee,
            is_buy=order.side is OrderSide.BUY,
        )
        try:
            assert_fill_amounts(
                calculated=calculated,
                stored_gross=fill.gross_amount,
                stored_net=fill.net_amount,
                tolerance=AMOUNT_TOLERANCE,
            )
        except ValueError as exc:
            raise ApplicationError("FILL_AMOUNT_MISMATCH", str(exc)) from exc
        cash = await uow.cash_balances.get_for_update(account.id, account.base_currency)
        if cash is None:
            raise ApplicationError("CASH_BALANCE_NOT_FOUND", "账户资金余额不存在")
        existing = await uow.ledger_transactions.get_by_fill_id(fill.id)
        if existing is not None:
            return await self._existing_result(uow, fill, existing)
        position = await uow.positions.get_for_update(account.id, fill.instrument_id)
        now = fill.executed_at
        if order.side is OrderSide.BUY:
            if cash.available_cash < calculated.net_amount:
                raise ApplicationError("INSUFFICIENT_CASH", "买入成交所需可用资金不足")
            return await self._apply_buy(
                uow, account, cash, position, fill, calculated.net_amount, now
            )
        if position is None or position.available_quantity < fill.quantity:
            raise ApplicationError("INSUFFICIENT_POSITION", "卖出成交所需可用持仓不足")
        return await self._apply_sell(
            uow, account, cash, position, fill, calculated.net_amount, now
        )

    async def _apply_buy(
        self,
        uow: UnitOfWork,
        account: TradingAccount,
        cash: CashBalance,
        position: Position | None,
        fill: Fill,
        net_amount: Decimal,
        occurred_at: datetime,
    ) -> FillAccountingResult:
        cash_delta = -net_amount
        updated_cash = replace(
            cash,
            total_cash=cash.total_cash + cash_delta,
            available_cash=cash.available_cash + cash_delta,
            row_version=cash.row_version + 1,
            as_of=occurred_at,
            updated_at=_now(),
        )
        old_quantity = ZERO if position is None else position.total_quantity
        old_cost = ZERO if position is None else position.cost_basis
        new_quantity = old_quantity + fill.quantity
        new_cost = old_cost + net_amount
        available_delta = (
            fill.quantity if account.settlement_policy is SettlementPolicy.IMMEDIATE else ZERO
        )
        unsettled_delta = fill.quantity - available_delta
        if position is None:
            updated_position = Position(
                account_id=account.id,
                instrument_id=fill.instrument_id,
                total_quantity=new_quantity,
                available_quantity=available_delta,
                frozen_quantity=ZERO,
                unsettled_quantity=unsettled_delta,
                cost_basis=new_cost,
                average_cost=new_cost / new_quantity,
                market_value=None,
                realized_pnl=ZERO,
                unrealized_pnl=None,
                last_price=None,
                last_price_at=None,
                valuation_status=AccountValuationStatus.UNAVAILABLE,
                as_of=occurred_at,
            )
            await uow.positions.add(updated_position)
            old_realized = ZERO
        else:
            old_realized = position.realized_pnl
            updated_position = replace(
                position,
                total_quantity=new_quantity,
                available_quantity=position.available_quantity + available_delta,
                unsettled_quantity=position.unsettled_quantity + unsettled_delta,
                cost_basis=new_cost,
                average_cost=new_cost / new_quantity,
                market_value=None,
                unrealized_pnl=None,
                last_price=None,
                last_price_at=None,
                valuation_status=AccountValuationStatus.UNAVAILABLE,
                as_of=occurred_at,
                row_version=position.row_version + 1,
                updated_at=_now(),
            )
            await uow.positions.update(updated_position)
        return await self._append_fill_ledgers(
            uow=uow,
            account=account,
            fill=fill,
            transaction_type=LedgerTransactionType.BUY_FILL,
            cash_entry_type=CashLedgerEntryType.BUY_SETTLEMENT,
            position_entry_type=PositionLedgerEntryType.BUY,
            cash=updated_cash,
            position=updated_position,
            cash_delta=cash_delta,
            available_quantity_delta=available_delta,
            unsettled_quantity_delta=unsettled_delta,
            cost_basis_delta=net_amount,
            realized_pnl_delta=ZERO,
            old_realized=old_realized,
        )

    async def _apply_sell(
        self,
        uow: UnitOfWork,
        account: TradingAccount,
        cash: CashBalance,
        position: Position,
        fill: Fill,
        net_amount: Decimal,
        occurred_at: datetime,
    ) -> FillAccountingResult:
        removed_cost = position.average_cost * fill.quantity
        realized_delta = net_amount - removed_cost
        new_quantity = position.total_quantity - fill.quantity
        new_cost = position.cost_basis - removed_cost
        if new_quantity == ZERO:
            new_cost = ZERO
        updated_cash = replace(
            cash,
            total_cash=cash.total_cash + net_amount,
            available_cash=cash.available_cash + net_amount,
            row_version=cash.row_version + 1,
            as_of=occurred_at,
            updated_at=_now(),
        )
        updated_position = replace(
            position,
            total_quantity=new_quantity,
            available_quantity=position.available_quantity - fill.quantity,
            cost_basis=new_cost,
            average_cost=ZERO if new_quantity == ZERO else new_cost / new_quantity,
            market_value=None,
            realized_pnl=position.realized_pnl + realized_delta,
            unrealized_pnl=None,
            last_price=None,
            last_price_at=None,
            valuation_status=AccountValuationStatus.UNAVAILABLE,
            as_of=occurred_at,
            row_version=position.row_version + 1,
            updated_at=_now(),
        )
        await uow.positions.update(updated_position)
        return await self._append_fill_ledgers(
            uow=uow,
            account=account,
            fill=fill,
            transaction_type=LedgerTransactionType.SELL_FILL,
            cash_entry_type=CashLedgerEntryType.SELL_SETTLEMENT,
            position_entry_type=PositionLedgerEntryType.SELL,
            cash=updated_cash,
            position=updated_position,
            cash_delta=net_amount,
            available_quantity_delta=-fill.quantity,
            unsettled_quantity_delta=ZERO,
            cost_basis_delta=-removed_cost,
            realized_pnl_delta=realized_delta,
            old_realized=position.realized_pnl,
        )

    async def _append_fill_ledgers(
        self,
        *,
        uow: UnitOfWork,
        account: TradingAccount,
        fill: Fill,
        transaction_type: LedgerTransactionType,
        cash_entry_type: CashLedgerEntryType,
        position_entry_type: PositionLedgerEntryType,
        cash: CashBalance,
        position: Position,
        cash_delta: Decimal,
        available_quantity_delta: Decimal,
        unsettled_quantity_delta: Decimal,
        cost_basis_delta: Decimal,
        realized_pnl_delta: Decimal,
        old_realized: Decimal,
    ) -> FillAccountingResult:
        await uow.cash_balances.update(cash)
        posted_at = max(_now(), fill.executed_at)
        transaction = LedgerTransaction(
            account_id=account.id,
            transaction_type=transaction_type,
            status=LedgerTransactionStatus.POSTED,
            business_key=f"fill:{fill.id}",
            related_order_id=fill.order_id,
            related_fill_id=fill.id,
            correlation_id=fill.correlation_id,
            occurred_at=fill.executed_at,
            posted_at=posted_at,
            description="模拟成交记账",
            metadata={"scope": "M04", "broker_type": fill.broker_type},
        )
        await uow.ledger_transactions.add(transaction)
        await uow.cash_ledger.append(
            CashLedgerEntry(
                ledger_transaction_id=transaction.id,
                account_id=account.id,
                currency=account.base_currency,
                entry_type=cash_entry_type,
                total_delta=cash_delta,
                available_delta=cash_delta,
                frozen_delta=ZERO,
                gross_amount=fill.gross_amount,
                fee_amount=fill.commission + fill.tax + fill.other_fee,
                total_cash_after=cash.total_cash,
                available_cash_after=cash.available_cash,
                frozen_cash_after=cash.frozen_cash,
                related_fill_id=fill.id,
                correlation_id=fill.correlation_id,
                occurred_at=fill.executed_at,
                metadata={"net_cash_entry": True},
            )
        )
        self._failure_injector("after_cash_ledger")
        quantity_delta = (
            fill.quantity if position_entry_type is PositionLedgerEntryType.BUY else -fill.quantity
        )
        position_entry = PositionLedgerEntry(
            ledger_transaction_id=transaction.id,
            account_id=account.id,
            instrument_id=fill.instrument_id,
            entry_type=position_entry_type,
            quantity_delta=quantity_delta,
            available_quantity_delta=available_quantity_delta,
            frozen_quantity_delta=ZERO,
            unsettled_quantity_delta=unsettled_quantity_delta,
            cost_basis_delta=cost_basis_delta,
            realized_pnl_delta=realized_pnl_delta,
            total_quantity_after=position.total_quantity,
            available_quantity_after=position.available_quantity,
            frozen_quantity_after=position.frozen_quantity,
            unsettled_quantity_after=position.unsettled_quantity,
            cost_basis_after=position.cost_basis,
            average_cost_after=position.average_cost,
            realized_pnl_after=position.realized_pnl,
            related_fill_id=fill.id,
            correlation_id=fill.correlation_id,
            occurred_at=fill.executed_at,
            metadata={"scope": "M04"},
        )
        await uow.position_ledger.append(position_entry)
        self._failure_injector("after_position_ledger")
        await append_event_and_audit(
            uow,
            event_type="FILL_ACCOUNTING_POSTED",
            entity_type="FILL",
            entity_id=fill.id,
            correlation_id=fill.correlation_id,
            payload={
                "account_id": str(account.id),
                "transaction_id": str(transaction.id),
                "side": "BUY" if quantity_delta > ZERO else "SELL",
            },
            source="ALPHADESK_M04",
        )
        return FillAccountingResult(
            ledger_transaction_id=transaction.id,
            fill_id=fill.id,
            cash_delta=cash_delta,
            quantity_delta=quantity_delta,
            cost_basis_delta=cost_basis_delta,
            realized_pnl_delta=realized_pnl_delta,
            total_cash_after=cash.total_cash,
            total_quantity_after=position.total_quantity,
            average_cost_after=position.average_cost,
            realized_pnl_after=old_realized + realized_pnl_delta,
        )

    @staticmethod
    async def _existing_result(
        uow: UnitOfWork, fill: Fill, transaction: LedgerTransaction
    ) -> FillAccountingResult:
        cash = await uow.cash_ledger.get_for_transaction(transaction.id)
        position = await uow.position_ledger.get_for_transaction(transaction.id)
        if cash is None or position is None:
            raise ApplicationError("LEDGER_INTEGRITY_ERROR", "成交交易缺少账本分录")
        return FillAccountingResult(
            ledger_transaction_id=transaction.id,
            fill_id=fill.id,
            cash_delta=cash.total_delta,
            quantity_delta=position.quantity_delta,
            cost_basis_delta=position.cost_basis_delta,
            realized_pnl_delta=position.realized_pnl_delta,
            total_cash_after=cash.total_cash_after,
            total_quantity_after=position.total_quantity_after,
            average_cost_after=position.average_cost_after,
            realized_pnl_after=position.realized_pnl_after,
            idempotent=True,
        )


class AccountValuationService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        market_data: MarketDataQueryService,
    ) -> None:
        self._uow_factory = uow_factory
        self._market_data = market_data

    async def value(self, *, account_id: UUID, correlation_id: UUID) -> AccountValuationResult:
        async with self._uow_factory() as uow:
            account = await _require_account(uow, account_id)
            cash = await uow.cash_balances.get(account.id, account.base_currency)
            positions = await uow.positions.list_for_account(account.id)
        if cash is None:
            raise ApplicationError("CASH_BALANCE_NOT_FOUND", "账户资金余额不存在")
        open_positions = [item for item in positions if item.total_quantity > ZERO]
        bars_by_instrument = {}
        source_code: str | None = None
        stale = False
        if open_positions:
            try:
                source, bars = await self._market_data.latest(
                    instrument_ids=[item.instrument_id for item in open_positions],
                    timeframe=MarketTimeframe.DAY_1,
                    adjustment=AdjustmentType.NONE,
                    source_code=None,
                )
                source_code = source.source_code
                bars_by_instrument = {
                    bar.instrument_id: (bar, freshness) for bar, freshness in bars
                }
                stale = any(
                    freshness.status is not MarketDataQualityStatus.NORMAL for _, freshness in bars
                )
            except ApplicationError:
                bars_by_instrument = {}
        priced = []
        unpriced = []
        latest_price_time: datetime | None = None
        market_value = ZERO
        unrealized = ZERO
        now = _now()
        async with self._uow_factory() as uow:
            await _require_account(uow, account_id)
            current_positions = await uow.positions.list_for_account(account_id)
            for position in current_positions:
                if position.total_quantity == ZERO:
                    continue
                quote = bars_by_instrument.get(position.instrument_id)
                if quote is None:
                    unpriced.append(position.instrument_id)
                    updated = replace(
                        position,
                        market_value=None,
                        unrealized_pnl=None,
                        last_price=None,
                        last_price_at=None,
                        valuation_status=AccountValuationStatus.UNAVAILABLE,
                        updated_at=now,
                    )
                else:
                    bar, freshness = quote
                    value = position.total_quantity * bar.close
                    pnl = value - position.cost_basis
                    market_value += value
                    unrealized += pnl
                    priced.append(position.instrument_id)
                    latest_price_time = (
                        bar.bar_time
                        if latest_price_time is None
                        else max(latest_price_time, bar.bar_time)
                    )
                    updated = replace(
                        position,
                        market_value=value,
                        unrealized_pnl=pnl,
                        last_price=bar.close,
                        last_price_at=bar.bar_time,
                        valuation_status=(
                            AccountValuationStatus.COMPLETE
                            if freshness.status is MarketDataQualityStatus.NORMAL
                            else AccountValuationStatus.STALE
                        ),
                        updated_at=now,
                    )
                await uow.positions.update(updated)
            if not open_positions:
                status = AccountValuationStatus.COMPLETE
            elif unpriced and priced:
                status = AccountValuationStatus.PARTIAL
            elif unpriced:
                status = AccountValuationStatus.UNAVAILABLE
            elif stale:
                status = AccountValuationStatus.STALE
            else:
                status = AccountValuationStatus.COMPLETE
            numeric = status in (
                AccountValuationStatus.COMPLETE,
                AccountValuationStatus.STALE,
            )
            snapshot = AccountSnapshot(
                account_id=account_id,
                as_of=now,
                cash_total=cash.total_cash,
                cash_available=cash.available_cash,
                cash_frozen=cash.frozen_cash,
                positions_cost_basis=sum((item.cost_basis for item in current_positions), ZERO),
                positions_market_value=market_value if numeric else None,
                total_equity=cash.total_cash + market_value if numeric else None,
                realized_pnl=sum((item.realized_pnl for item in current_positions), ZERO),
                unrealized_pnl=unrealized if numeric else None,
                valuation_status=status,
                priced_position_count=len(priced),
                unpriced_position_count=len(unpriced),
                latest_price_time=latest_price_time,
                correlation_id=correlation_id,
                metadata={
                    "source_code": source_code,
                    "unpriced_instrument_ids": [str(item) for item in unpriced[:100]],
                    "partial_market_value": str(market_value),
                },
            )
            await uow.account_snapshots.append(snapshot)
            await append_event_and_audit(
                uow,
                event_type="ACCOUNT_VALUATION_COMPLETED",
                entity_type="TRADING_ACCOUNT",
                entity_id=account_id,
                correlation_id=correlation_id,
                payload={"valuation_status": status.value},
                source="ALPHADESK_M04",
            )
            await uow.commit()
        return AccountValuationResult(
            snapshot=snapshot,
            unpriced_instrument_ids=tuple(unpriced),
            source_code=source_code,
        )


class AccountReconciliationService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def run(self, *, account_id: UUID, correlation_id: UUID) -> AccountReconciliationResult:
        async with self._uow_factory() as uow:
            result = await self.run_in_uow(
                uow=uow, account_id=account_id, correlation_id=correlation_id
            )
            await uow.commit()
            return result

    async def run_in_uow(
        self, *, uow: UnitOfWork, account_id: UUID, correlation_id: UUID
    ) -> AccountReconciliationResult:
        """Reconcile projections in the caller's transaction without committing."""

        started = _now()
        await _require_account(uow, account_id)
        balances = await uow.cash_balances.list_for_account(account_id)
        positions = await uow.positions.list_for_account(account_id)
        cash_entries = await uow.cash_ledger.list_all_for_account(account_id)
        position_entries = await uow.position_ledger.list_all_for_account(account_id)
        expected_cash: dict[str, str] = {}
        for cash_entry in cash_entries:
            expected_cash[cash_entry.currency] = str(
                Decimal(expected_cash.get(cash_entry.currency, "0")) + cash_entry.total_delta
            )
        actual_cash = {item.currency: str(item.total_cash) for item in balances}
        expected_positions: dict[str, str] = {}
        for position_entry in position_entries:
            key = str(position_entry.instrument_id)
            expected_positions[key] = str(
                Decimal(expected_positions.get(key, "0")) + position_entry.quantity_delta
            )
        actual_positions = {str(item.instrument_id): str(item.total_quantity) for item in positions}
        discrepancies: list[dict[str, object]] = []
        for key in sorted(set(expected_cash) | set(actual_cash)):
            if Decimal(expected_cash.get(key, "0")) != Decimal(actual_cash.get(key, "0")):
                discrepancies.append(
                    {
                        "kind": "CASH",
                        "key": key,
                        "expected": expected_cash.get(key, "0"),
                        "actual": actual_cash.get(key, "0"),
                    }
                )
        for key in sorted(set(expected_positions) | set(actual_positions)):
            if Decimal(expected_positions.get(key, "0")) != Decimal(actual_positions.get(key, "0")):
                discrepancies.append(
                    {
                        "kind": "POSITION",
                        "key": key,
                        "expected": expected_positions.get(key, "0"),
                        "actual": actual_positions.get(key, "0"),
                    }
                )
        discrepancies = discrepancies[:100]
        completed = _now()
        run = AccountReconciliationRun(
            account_id=account_id,
            status=(
                ReconciliationStatus.MATCHED
                if not discrepancies
                else ReconciliationStatus.MISMATCHED
            ),
            started_at=started,
            completed_at=completed,
            expected_cash=expected_cash,
            actual_cash=actual_cash,
            expected_positions=expected_positions,
            actual_positions=actual_positions,
            discrepancy_count=len(discrepancies),
            discrepancies=discrepancies,
            correlation_id=correlation_id,
        )
        await uow.account_reconciliations.append(run)
        await append_event_and_audit(
            uow,
            event_type="ACCOUNT_RECONCILIATION_COMPLETED",
            entity_type="TRADING_ACCOUNT",
            entity_id=account_id,
            correlation_id=correlation_id,
            payload={"status": run.status.value, "count": run.discrepancy_count},
            source="ALPHADESK_M04",
        )
        return AccountReconciliationResult(run=run)
