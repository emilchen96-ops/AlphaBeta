"""B01-B atomic simulated execution, persistence, accounting and integrity services."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import NAMESPACE_URL, UUID, uuid5

from alphadesk_api.application.accounting import (
    AccountReconciliationService,
    FillAccountingService,
)
from alphadesk_api.application.common import (
    ApplicationError,
    UnitOfWorkFactory,
    append_event_and_audit,
)
from alphadesk_domain.accounting import (
    AccountReconciliationResult,
    AccountSnapshot,
    FillAccountingResult,
)
from alphadesk_domain.broker import (
    BrokerAccountSnapshot,
    BrokerDomainError,
    BrokerExecutionStatus,
    BrokerOrderRequest,
    ExecutionMarketSnapshot,
    SimulatedBrokerAdapter,
    TradingStatus,
    execution_fingerprint,
)
from alphadesk_domain.entities import (
    Fill,
    Order,
    OrderCommand,
    OrderStateTransition,
    OutboxMessage,
)
from alphadesk_domain.enums import (
    AccountType,
    AccountValuationStatus,
    CommandStatus,
    CommandType,
    OrderActorType,
    OrderSide,
    OrderStatus,
    OutboxStatus,
    ReconciliationStatus,
)
from alphadesk_domain.order_workflow import InvalidOrderTransition, OrderStateMachine
from alphadesk_domain.simulated_execution import BrokerExecutionAttempt
from alphadesk_domain.unit_of_work import UnitOfWork
from alphadesk_domain.values import as_utc

ZERO = Decimal("0")
LOCAL_CONSUMER = "LOCAL_SIMULATED_BROKER"
LOCAL_SUPPRESSION_REASON = "LOCAL_SIMULATED_EXECUTION"
BACKTEST_SUPPRESSION_REASON = "BACKTEST_ENGINE"
EXECUTABLE_STATUSES = frozenset(
    {OrderStatus.QUEUED, OrderStatus.BROKER_ACCEPTED, OrderStatus.PARTIALLY_FILLED}
)
EXECUTOR_REJECTION_CODES = frozenset(
    {
        "BROKER_INSTRUMENT_MISMATCH",
        "BROKER_MARKET_NOT_TRADING",
        "BROKER_MARKET_DATA_STALE",
    }
)
FailureInjector = Callable[[str], None]


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatedExecutionRequest:
    order_id: UUID
    execution_market_snapshot: ExecutionMarketSnapshot
    idempotency_key: str
    correlation_id: UUID
    requested_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatedExecutionMarketInput:
    order_id: UUID
    idempotency_key: str
    correlation_id: UUID
    timestamp: datetime
    trading_status: TradingStatus
    source: str
    is_stale: bool
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    last_price: Decimal | None = None
    bid_price: Decimal | None = None
    ask_price: Decimal | None = None
    available_volume: Decimal | None = None
    price_limit_up: Decimal | None = None
    price_limit_down: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatedExecutionIntegrityIssue:
    order_id: UUID
    code: str
    message: str
    execution_attempt_id: UUID | None = None
    fill_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SimulatedExecutionResult:
    attempt: BrokerExecutionAttempt
    order: Order
    fills: tuple[Fill, ...]
    accounting_results: tuple[FillAccountingResult, ...]
    reconciliation: AccountReconciliationResult | None
    integrity_issues: tuple[SimulatedExecutionIntegrityIssue, ...]
    idempotent: bool = False


def _no_failure(_: str) -> None:
    return None


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return as_utc(value, "fingerprint_time").isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _safe_model_config(model: object) -> dict[str, object]:
    result: dict[str, object] = {"version": str(getattr(model, "version", "unknown"))}
    if not is_dataclass(model):
        return result
    blocked = ("credential", "password", "path", "secret", "token", "url")
    for item in fields(model):
        if any(word in item.name.lower() for word in blocked):
            continue
        result[item.name] = _canonical(getattr(model, item.name))
    return result


def _application_fingerprint(
    *,
    adapter: SimulatedBrokerAdapter,
    request: BrokerOrderRequest,
    market: ExecutionMarketSnapshot,
) -> str:
    fee_model = adapter.fee_model
    slippage_model = adapter.slippage_model
    base = execution_fingerprint(
        broker_key=adapter.metadata.broker_key,
        request=request,
        market=market,
        fee_model_version=str(fee_model.version),
        slippage_model_version=str(slippage_model.version),
    )
    payload = {
        "schema_version": 1,
        "base_fingerprint": base,
        "broker_version": adapter.metadata.version,
        "fee_model": _safe_model_config(fee_model),
        "slippage_model": _safe_model_config(slippage_model),
    }
    encoded = json.dumps(
        _canonical(payload), ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _market_snapshot(snapshot: ExecutionMarketSnapshot) -> dict[str, object]:
    allowed = (
        "instrument_id",
        "timestamp",
        "trading_status",
        "source",
        "is_stale",
        "open",
        "high",
        "low",
        "close",
        "last_price",
        "bid_price",
        "ask_price",
        "available_volume",
        "price_limit_up",
        "price_limit_down",
    )
    raw = asdict(snapshot)
    return {name: _canonical(raw[name]) for name in allowed}


def _account_snapshot(snapshot: BrokerAccountSnapshot) -> dict[str, object]:
    return {
        "account_id": str(snapshot.account_id),
        "account_type": snapshot.account_type.value,
        "account_status": snapshot.account_status.value,
        "cash_available": str(snapshot.cash_available),
        "position_quantity": str(snapshot.position_quantity),
        "sellable_quantity": str(snapshot.sellable_quantity),
        "snapshot_at": _canonical(snapshot.snapshot_at),
    }


class SimulatedBrokerExecutionService:
    """Execute one local order in one PostgreSQL transaction."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        adapter: SimulatedBrokerAdapter | None = None,
        failure_injector: FailureInjector = _no_failure,
    ) -> None:
        self._uow_factory = uow_factory
        self._adapter = adapter or SimulatedBrokerAdapter()
        self._failure_injector = failure_injector
        self._accounting = FillAccountingService(uow_factory, failure_injector)
        self._reconciliation = AccountReconciliationService(uow_factory)

    async def execute_market_input(
        self, request: SimulatedExecutionMarketInput
    ) -> SimulatedExecutionResult:
        async with self._uow_factory() as uow:
            order = await uow.orders.get_by_id(request.order_id)
            if order is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
        try:
            snapshot = ExecutionMarketSnapshot(
                instrument_id=order.instrument_id,
                timestamp=request.timestamp,
                trading_status=request.trading_status,
                source=request.source,
                is_stale=request.is_stale,
                open=request.open,
                high=request.high,
                low=request.low,
                close=request.close,
                last_price=request.last_price,
                bid_price=request.bid_price,
                ask_price=request.ask_price,
                available_volume=request.available_volume,
                price_limit_up=request.price_limit_up,
                price_limit_down=request.price_limit_down,
            )
        except (BrokerDomainError, ValueError) as exc:
            raise ApplicationError("BROKER_EXECUTION_INVALID_REQUEST", str(exc)) from exc
        return await self.execute(
            SimulatedExecutionRequest(
                order_id=request.order_id,
                execution_market_snapshot=snapshot,
                idempotency_key=request.idempotency_key,
                correlation_id=request.correlation_id,
                requested_at=request.timestamp,
            )
        )

    async def execute(self, request: SimulatedExecutionRequest) -> SimulatedExecutionResult:
        try:
            requested_at = as_utc(request.requested_at, "requested_at")
        except ValueError as exc:
            raise ApplicationError("BROKER_EXECUTION_INVALID_REQUEST", str(exc)) from exc
        key = request.idempotency_key.strip()
        if not key or len(key) > 128:
            raise ApplicationError("BROKER_EXECUTION_INVALID_REQUEST", "idempotency_key is invalid")
        async with self._uow_factory() as uow:
            await uow.broker_execution_attempts.lock_idempotency_key(key)
            order = await uow.orders.get_for_update(request.order_id)
            if order is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
            command = await uow.order_commands.get_submit_command_for_update(order.id)
            if command is None or command.command_type is not CommandType.SUBMIT_ORDER:
                raise ApplicationError(
                    "BROKER_SUBMIT_COMMAND_NOT_FOUND", "submit command was not found"
                )
            instrument = await uow.instruments.get_by_id(order.instrument_id)
            if instrument is None:
                raise ApplicationError("INSTRUMENT_NOT_FOUND", "instrument was not found")
            existing = await uow.broker_execution_attempts.get_by_idempotency_key(key)
            if existing is not None:
                return await self._idempotent_result(
                    uow=uow,
                    request=request,
                    order=order,
                    command=command,
                    symbol=instrument.symbol,
                    exchange=instrument.exchange,
                    existing=existing,
                )
            if order.status not in EXECUTABLE_STATUSES:
                raise ApplicationError("BROKER_ORDER_NOT_EXECUTABLE", "order is not executable")
            outbox = await uow.outbox.get_submit_for_order_for_update(order.id)
            if outbox is None:
                raise ApplicationError("BROKER_OUTBOX_NOT_FOUND", "submit outbox was not found")
            self._validate_consumption(command, outbox, order.status)
            account = await uow.accounts.get_for_update(order.account_id)
            if account is None:
                raise ApplicationError("ACCOUNT_NOT_FOUND", "account was not found")
            if account.account_type is not AccountType.SIMULATED:
                raise ApplicationError(
                    "BROKER_ACCOUNT_NOT_SUPPORTED", "only simulated accounts are supported"
                )
            cash = await uow.cash_balances.get_for_update(account.id, account.base_currency)
            if cash is None:
                raise ApplicationError(
                    "CASH_BALANCE_NOT_FOUND", "account cash balance was not found"
                )
            position = await uow.positions.get_for_update(account.id, order.instrument_id)
            existing_fills = await uow.fills.list_by_order(order.id)
            previously_filled = sum((fill.quantity for fill in existing_fills), ZERO)
            remaining = order.requested_quantity - previously_filled
            if remaining <= ZERO:
                raise ApplicationError(
                    "BROKER_ORDER_NOT_EXECUTABLE", "order has no remaining quantity"
                )
            broker_account = BrokerAccountSnapshot(
                account_id=account.id,
                account_type=account.account_type,
                account_status=account.status,
                cash_available=cash.available_cash,
                position_quantity=ZERO if position is None else position.total_quantity,
                sellable_quantity=ZERO if position is None else position.available_quantity,
                snapshot_at=requested_at,
            )
            broker_request = self._broker_request(
                order=order,
                command=command,
                symbol=instrument.symbol,
                exchange=instrument.exchange,
                quantity=remaining,
                correlation_id=request.correlation_id,
            )
            fingerprint = _application_fingerprint(
                adapter=self._adapter,
                request=broker_request,
                market=request.execution_market_snapshot,
            )
            broker_result = self._adapter.submit(
                broker_request, request.execution_market_snapshot, broker_account
            )
            attempt_number = await uow.broker_execution_attempts.next_attempt_number(order.id)
            attempt = BrokerExecutionAttempt(
                idempotency_key=key,
                request_fingerprint=fingerprint,
                broker_key=self._adapter.metadata.broker_key,
                broker_version=self._adapter.metadata.version,
                execution_mode=self._adapter.metadata.execution_mode,
                order_id=order.id,
                command_id=command.command_id,
                account_id=account.id,
                instrument_id=instrument.id,
                attempt_number=attempt_number,
                input_order_status=order.status,
                result_status=broker_result.status,
                requested_quantity=order.requested_quantity,
                previously_filled_quantity=previously_filled,
                attempted_quantity=remaining,
                filled_quantity=broker_result.filled_quantity,
                remaining_quantity=remaining - broker_result.filled_quantity,
                average_fill_price=broker_result.average_fill_price,
                rejection_code=broker_result.rejection_code,
                message=broker_result.message,
                market_snapshot=_market_snapshot(request.execution_market_snapshot),
                account_snapshot=_account_snapshot(broker_account),
                fee_model_version=str(self._adapter.fee_model.version),
                slippage_model_version=str(self._adapter.slippage_model.version),
                correlation_id=request.correlation_id,
                started_at=requested_at,
                completed_at=max(requested_at, broker_result.evaluated_at),
                created_at=requested_at,
            )
            await uow.broker_execution_attempts.add(attempt)
            await append_event_and_audit(
                uow,
                event_type="SIMULATED_EXECUTION_ATTEMPT_RECORDED",
                entity_type="BROKER_EXECUTION_ATTEMPT",
                entity_id=attempt.id,
                correlation_id=request.correlation_id,
                payload={
                    "order_id": str(order.id),
                    "attempt_number": attempt.attempt_number,
                    "result_status": attempt.result_status.value,
                },
                source="ALPHADESK_B01",
                actor_type=OrderActorType.BROKER,
                occurred_at=requested_at,
            )
            self._failure_injector("after_execution_attempt")

            await self._advance_pre_fill_state(
                uow=uow,
                order=order,
                attempt=attempt,
                command=command,
                occurred_at=requested_at,
            )
            self._failure_injector("after_order_transition")

            fills: list[Fill] = []
            accounting_results: list[FillAccountingResult] = []
            reconciliation: AccountReconciliationResult | None = None
            if broker_result.fills:
                next_sequence = len(existing_fills) + 1
                for offset, draft in enumerate(broker_result.fills):
                    sequence = next_sequence + offset
                    fill = Fill(
                        id=uuid5(
                            NAMESPACE_URL,
                            f"alphadesk:simulated:{attempt.id}:fill:{sequence}",
                        ),
                        order_id=order.id,
                        account_id=account.id,
                        instrument_id=instrument.id,
                        broker_type=self._adapter.metadata.broker_key,
                        broker_fill_id=f"SIMULATED:{attempt.id}:{sequence}",
                        execution_attempt_id=attempt.id,
                        command_id=command.command_id,
                        sequence_number=sequence,
                        execution_reference=f"SIMULATED:{attempt.id}:{sequence}",
                        quantity=draft.quantity,
                        price=draft.price,
                        gross_amount=draft.gross_amount,
                        commission=draft.commission,
                        tax=draft.stamp_duty,
                        other_fee=draft.transfer_fee + draft.other_fee,
                        net_amount=(
                            draft.gross_amount + draft.total_fee
                            if order.side is OrderSide.BUY
                            else draft.gross_amount - draft.total_fee
                        ),
                        executed_at=draft.executed_at,
                        received_at=requested_at,
                        correlation_id=request.correlation_id,
                        metadata={
                            "scope": "B01-B",
                            "reference_price": str(draft.reference_price),
                            "reference_price_source": draft.reference_price_source,
                            "stamp_duty": str(draft.stamp_duty),
                            "transfer_fee": str(draft.transfer_fee),
                            "other_fee": str(draft.other_fee),
                        },
                        created_at=requested_at,
                    )
                    await uow.fills.append(fill)
                    fills.append(fill)
                    self._failure_injector("after_fill")
                    accounting_results.append(
                        await self._accounting.apply_in_uow(uow=uow, fill_id=fill.id)
                    )
                    self._failure_injector("after_fill_accounting")
                total_fills = [*existing_fills, *fills]
                await self._advance_fill_state(
                    uow=uow,
                    order=order,
                    command=command,
                    fills=total_fills,
                    occurred_at=requested_at,
                    correlation_id=request.correlation_id,
                )
                self._failure_injector("after_fill_state")
                await self._append_account_snapshot(
                    uow=uow,
                    account_id=account.id,
                    correlation_id=request.correlation_id,
                    occurred_at=requested_at,
                )
                self._failure_injector("after_account_snapshot")
                reconciliation = await self._reconciliation.run_in_uow(
                    uow=uow,
                    account_id=account.id,
                    correlation_id=request.correlation_id,
                    occurred_at=requested_at,
                )
                if reconciliation.run.status is not ReconciliationStatus.MATCHED:
                    raise ApplicationError(
                        "SIMULATED_EXECUTION_RECONCILIATION_FAILED",
                        "post-fill reconciliation did not match",
                    )

            command_consumed_now = command.status is CommandStatus.PENDING
            if command_consumed_now:
                command = replace(
                    command,
                    status=CommandStatus.CONSUMED,
                    consumed_at=requested_at,
                    consumed_by=LOCAL_CONSUMER,
                    updated_at=requested_at,
                )
                await uow.order_commands.update(command)
                await append_event_and_audit(
                    uow,
                    event_type="ORDER_COMMAND_CONSUMED_LOCALLY",
                    entity_type="ORDER_COMMAND",
                    entity_id=command.command_id,
                    correlation_id=request.correlation_id,
                    payload={
                        "order_id": str(order.id),
                        "consumed_by": LOCAL_CONSUMER,
                    },
                    source="ALPHADESK_B01",
                    actor_type=OrderActorType.BROKER,
                    occurred_at=requested_at,
                )
            self._failure_injector("after_command_consumed")
            outbox_suppressed_now = outbox.status is OutboxStatus.PENDING
            if outbox_suppressed_now:
                outbox = replace(
                    outbox,
                    status=OutboxStatus.SUPPRESSED,
                    suppressed_at=requested_at,
                    suppression_reason=LOCAL_SUPPRESSION_REASON,
                    updated_at=requested_at,
                )
                await uow.outbox.update(outbox)
                await append_event_and_audit(
                    uow,
                    event_type="ORDER_OUTBOX_SUPPRESSED",
                    entity_type="OUTBOX_MESSAGE",
                    entity_id=outbox.id,
                    correlation_id=request.correlation_id,
                    payload={
                        "order_id": str(order.id),
                        "suppression_reason": LOCAL_SUPPRESSION_REASON,
                    },
                    source="ALPHADESK_B01",
                    actor_type=OrderActorType.BROKER,
                    occurred_at=requested_at,
                )
            self._failure_injector("after_outbox_suppressed")
            self._failure_injector("before_commit")
            await uow.commit()
            return SimulatedExecutionResult(
                attempt=attempt,
                order=order,
                fills=tuple(fills),
                accounting_results=tuple(accounting_results),
                reconciliation=reconciliation,
                integrity_issues=(),
            )

    @staticmethod
    def _validate_consumption(
        command: OrderCommand, outbox: OutboxMessage, status: OrderStatus
    ) -> None:
        if status is OrderStatus.QUEUED:
            if command.status is not CommandStatus.PENDING:
                raise ApplicationError(
                    "BROKER_COMMAND_ALREADY_CONSUMED", "submit command is not pending"
                )
            if not (
                outbox.status is OutboxStatus.PENDING
                or (
                    outbox.status is OutboxStatus.SUPPRESSED
                    and outbox.suppression_reason == BACKTEST_SUPPRESSION_REASON
                )
            ):
                raise ApplicationError(
                    "BROKER_OUTBOX_NOT_PENDING", "submit outbox is not locally executable"
                )
            return
        if command.status is not CommandStatus.CONSUMED or command.consumed_by != LOCAL_CONSUMER:
            raise ApplicationError(
                "BROKER_COMMAND_ALREADY_CONSUMED", "command was consumed by another mode"
            )
        if outbox.status is not OutboxStatus.SUPPRESSED or outbox.suppression_reason not in (
            LOCAL_SUPPRESSION_REASON,
            BACKTEST_SUPPRESSION_REASON,
        ):
            raise ApplicationError(
                "BROKER_OUTBOX_NOT_SUPPRESSED", "local submit outbox is not suppressed"
            )

    @staticmethod
    def _broker_request(
        *,
        order: Order,
        command: OrderCommand,
        symbol: str,
        exchange: str,
        quantity: Decimal,
        correlation_id: UUID,
    ) -> BrokerOrderRequest:
        return BrokerOrderRequest(
            command_id=command.command_id,
            order_id=order.id,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            symbol=symbol,
            exchange=exchange,
            side=order.side,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            quantity=quantity,
            limit_price=order.limit_price,
            submitted_at=order.confirmed_at or order.created_at,
            expires_at=order.expires_at,
            correlation_id=correlation_id,
        )

    async def _idempotent_result(
        self,
        *,
        uow: UnitOfWork,
        request: SimulatedExecutionRequest,
        order: Order,
        command: OrderCommand,
        symbol: str,
        exchange: str,
        existing: BrokerExecutionAttempt,
    ) -> SimulatedExecutionResult:
        if existing.order_id != order.id or existing.command_id != command.command_id:
            raise ApplicationError(
                "BROKER_EXECUTION_IDEMPOTENCY_CONFLICT",
                "idempotency key belongs to another execution",
            )
        replay_request = self._broker_request(
            order=order,
            command=command,
            symbol=symbol,
            exchange=exchange,
            quantity=existing.attempted_quantity,
            correlation_id=request.correlation_id,
        )
        fingerprint = _application_fingerprint(
            adapter=self._adapter,
            request=replay_request,
            market=request.execution_market_snapshot,
        )
        if fingerprint != existing.request_fingerprint:
            raise ApplicationError(
                "BROKER_EXECUTION_IDEMPOTENCY_CONFLICT",
                "idempotency key has different execution input",
            )
        fills = await uow.fills.list_by_execution_attempt(existing.id)
        accounting = tuple(
            [await self._accounting.apply_in_uow(uow=uow, fill_id=fill.id) for fill in fills]
        )
        reconciliation = (
            await uow.account_reconciliations.latest(order.account_id) if fills else None
        )
        return SimulatedExecutionResult(
            attempt=existing,
            order=order,
            fills=tuple(fills),
            accounting_results=accounting,
            reconciliation=(
                None if reconciliation is None else AccountReconciliationResult(run=reconciliation)
            ),
            integrity_issues=(),
            idempotent=True,
        )

    async def _advance_pre_fill_state(
        self,
        *,
        uow: UnitOfWork,
        order: Order,
        attempt: BrokerExecutionAttempt,
        command: OrderCommand,
        occurred_at: datetime,
    ) -> None:
        status = attempt.result_status
        if status is BrokerExecutionStatus.EXPIRED:
            if order.status is OrderStatus.QUEUED:
                await self._transition(
                    uow, order, OrderStatus.EXPIRED, command, attempt.correlation_id, occurred_at
                )
            return
        if order.status is OrderStatus.QUEUED:
            await self._transition(
                uow, order, OrderStatus.DISPATCHED, command, attempt.correlation_id, occurred_at
            )
            if (
                status is BrokerExecutionStatus.REJECTED
                and attempt.rejection_code in EXECUTOR_REJECTION_CODES
            ):
                await self._transition(
                    uow,
                    order,
                    OrderStatus.EXECUTOR_REJECTED,
                    command,
                    attempt.correlation_id,
                    occurred_at,
                )
                return
            await self._transition(
                uow,
                order,
                OrderStatus.EXECUTOR_ACCEPTED,
                command,
                attempt.correlation_id,
                occurred_at,
            )
            await self._transition(
                uow,
                order,
                OrderStatus.BROKER_SUBMITTED,
                command,
                attempt.correlation_id,
                occurred_at,
            )
            if status is BrokerExecutionStatus.REJECTED:
                await self._transition(
                    uow, order, OrderStatus.FAILED, command, attempt.correlation_id, occurred_at
                )
                return
            await self._transition(
                uow,
                order,
                OrderStatus.BROKER_ACCEPTED,
                command,
                attempt.correlation_id,
                occurred_at,
            )
            return
        if status is BrokerExecutionStatus.REJECTED:
            await self._transition(
                uow, order, OrderStatus.FAILED, command, attempt.correlation_id, occurred_at
            )

    async def _advance_fill_state(
        self,
        *,
        uow: UnitOfWork,
        order: Order,
        command: OrderCommand,
        fills: list[Fill],
        occurred_at: datetime,
        correlation_id: UUID,
    ) -> None:
        filled_quantity = sum((fill.quantity for fill in fills), ZERO)
        weighted = sum((fill.quantity * fill.price for fill in fills), ZERO)
        order.filled_quantity = filled_quantity
        order.average_fill_price = weighted / filled_quantity
        order.updated_at = occurred_at
        target = (
            OrderStatus.FILLED
            if filled_quantity == order.requested_quantity
            else OrderStatus.PARTIALLY_FILLED
        )
        if order.status is target:
            await uow.orders.update_projection(order)
            return
        await self._transition(uow, order, target, command, correlation_id, occurred_at)

    @staticmethod
    async def _transition(
        uow: UnitOfWork,
        order: Order,
        target: OrderStatus,
        command: OrderCommand,
        correlation_id: UUID,
        occurred_at: datetime,
    ) -> None:
        previous = order.status
        try:
            OrderStateMachine.require_transition(previous, target)
        except InvalidOrderTransition as exc:
            raise ApplicationError("BROKER_ORDER_TRANSITION_INVALID", str(exc)) from exc
        order.status = target
        order.row_version += 1
        order.updated_at = occurred_at
        if target is OrderStatus.EXPIRED:
            order.expired_at = occurred_at
        if target in OrderStateMachine.terminal_states:
            order.completed_at = occurred_at
        await uow.orders.update_projection(order)
        await uow.order_state_transitions.append(
            OrderStateTransition(
                order_id=order.id,
                from_status=previous,
                to_status=target,
                actor_type=(
                    OrderActorType.BROKER
                    if target
                    in {
                        OrderStatus.BROKER_SUBMITTED,
                        OrderStatus.BROKER_ACCEPTED,
                        OrderStatus.PARTIALLY_FILLED,
                        OrderStatus.FILLED,
                        OrderStatus.FAILED,
                    }
                    else OrderActorType.EXECUTOR
                ),
                reason_code=f"SIMULATED_{target.value}",
                order_version=order.row_version,
                command_id=command.command_id,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                metadata={"execution_mode": "SIMULATED"},
            )
        )
        await append_event_and_audit(
            uow,
            event_type=f"ORDER_{target.value}",
            entity_type="ORDER",
            entity_id=order.id,
            correlation_id=correlation_id,
            payload={
                "from_status": previous.value,
                "to_status": target.value,
                "row_version": order.row_version,
                "execution_mode": "SIMULATED",
            },
            source="ALPHADESK_B01",
            actor_type=OrderActorType.BROKER,
            occurred_at=occurred_at,
        )

    @staticmethod
    async def _append_account_snapshot(
        *,
        uow: UnitOfWork,
        account_id: UUID,
        correlation_id: UUID,
        occurred_at: datetime,
    ) -> None:
        balances = await uow.cash_balances.list_for_account(account_id)
        positions = await uow.positions.list_for_account(account_id)
        cash_total = sum((item.total_cash for item in balances), ZERO)
        cash_available = sum((item.available_cash for item in balances), ZERO)
        cash_frozen = sum((item.frozen_cash for item in balances), ZERO)
        open_positions = [item for item in positions if item.total_quantity > ZERO]
        await uow.account_snapshots.append(
            AccountSnapshot(
                account_id=account_id,
                as_of=occurred_at,
                cash_total=cash_total,
                cash_available=cash_available,
                cash_frozen=cash_frozen,
                positions_cost_basis=sum((item.cost_basis for item in positions), ZERO),
                positions_market_value=None,
                total_equity=None,
                realized_pnl=sum((item.realized_pnl for item in positions), ZERO),
                unrealized_pnl=None,
                valuation_status=AccountValuationStatus.UNAVAILABLE,
                priced_position_count=0,
                unpriced_position_count=len(open_positions),
                correlation_id=correlation_id,
                metadata={"scope": "B01-B", "valuation": "not_requested"},
                created_at=occurred_at,
            )
        )


class SimulatedExecutionIntegrityService:
    """Report persisted execution inconsistencies without modifying facts."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def verify_order(self, order_id: UUID) -> list[SimulatedExecutionIntegrityIssue]:
        async with self._uow_factory() as uow:
            order = await uow.orders.get_by_id(order_id)
            if order is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
            attempts = await uow.broker_execution_attempts.list_by_order(order_id)
            fills = await uow.fills.list_by_order(order_id)
            issues: list[SimulatedExecutionIntegrityIssue] = []
            if [item.attempt_number for item in attempts] != list(range(1, len(attempts) + 1)):
                issues.append(
                    SimulatedExecutionIntegrityIssue(
                        order_id=order.id,
                        code="EXECUTION_ATTEMPT_SEQUENCE_GAP",
                        message="execution attempt numbers are not continuous",
                    )
                )
            b01_fills = [fill for fill in fills if fill.execution_attempt_id is not None]
            if [fill.sequence_number for fill in b01_fills] != list(range(1, len(b01_fills) + 1)):
                issues.append(
                    SimulatedExecutionIntegrityIssue(
                        order_id=order.id,
                        code="FILL_SEQUENCE_GAP",
                        message="Fill sequence numbers are not continuous",
                    )
                )
            attempts_by_id = {attempt.id: attempt for attempt in attempts}
            for fill in b01_fills:
                assert fill.execution_attempt_id is not None
                attempt = attempts_by_id.get(fill.execution_attempt_id)
                if (
                    attempt is None
                    or attempt.order_id != fill.order_id
                    or attempt.account_id != fill.account_id
                    or attempt.instrument_id != fill.instrument_id
                    or attempt.command_id != fill.command_id
                ):
                    issues.append(
                        SimulatedExecutionIntegrityIssue(
                            order_id=order.id,
                            code="FILL_ATTEMPT_MISMATCH",
                            message="Fill is not linked to the matching execution attempt",
                            fill_id=fill.id,
                        )
                    )
                if await uow.ledger_transactions.get_by_fill_id(fill.id) is None:
                    issues.append(
                        SimulatedExecutionIntegrityIssue(
                            order_id=order.id,
                            code="FILL_NOT_ACCOUNTED",
                            message="Fill has no M04 ledger transaction",
                            fill_id=fill.id,
                        )
                    )
                expected_net = fill.gross_amount + fill.commission + fill.tax + fill.other_fee
                if order.side is OrderSide.SELL:
                    expected_net = fill.gross_amount - fill.commission - fill.tax - fill.other_fee
                if fill.net_amount != expected_net:
                    issues.append(
                        SimulatedExecutionIntegrityIssue(
                            order_id=order.id,
                            code="FILL_AMOUNT_MISMATCH",
                            message="Fill amount and fee fields do not balance",
                            fill_id=fill.id,
                        )
                    )
            for attempt in attempts:
                attempt_fills = [
                    fill for fill in b01_fills if fill.execution_attempt_id == attempt.id
                ]
                attempt_fill_quantity = sum((fill.quantity for fill in attempt_fills), ZERO)
                if attempt_fill_quantity != attempt.filled_quantity:
                    issues.append(
                        SimulatedExecutionIntegrityIssue(
                            order_id=order.id,
                            code="ATTEMPT_FILL_QUANTITY_MISMATCH",
                            message="execution attempt quantity differs from linked Fills",
                            execution_attempt_id=attempt.id,
                        )
                    )
                if (
                    attempt.result_status
                    in {
                        BrokerExecutionStatus.REJECTED,
                        BrokerExecutionStatus.EXPIRED,
                        BrokerExecutionStatus.NO_FILL,
                    }
                    and attempt_fills
                ):
                    issues.append(
                        SimulatedExecutionIntegrityIssue(
                            order_id=order.id,
                            code="EMPTY_ATTEMPT_HAS_FILL",
                            message="non-fill execution result has a Fill",
                            execution_attempt_id=attempt.id,
                        )
                    )
            total_filled = sum((fill.quantity for fill in b01_fills), ZERO)
            if total_filled > order.requested_quantity:
                issues.append(
                    SimulatedExecutionIntegrityIssue(
                        order_id=order.id,
                        code="ORDER_OVERFILLED",
                        message="cumulative Fill quantity exceeds requested quantity",
                    )
                )
            if order.status is OrderStatus.FILLED and total_filled != order.requested_quantity:
                issues.append(
                    SimulatedExecutionIntegrityIssue(
                        order_id=order.id,
                        code="FILLED_ORDER_QUANTITY_MISMATCH",
                        message="FILLED order does not have the requested Fill quantity",
                    )
                )
            if order.status is OrderStatus.PARTIALLY_FILLED and not (
                ZERO < total_filled < order.requested_quantity
            ):
                issues.append(
                    SimulatedExecutionIntegrityIssue(
                        order_id=order.id,
                        code="PARTIAL_ORDER_QUANTITY_MISMATCH",
                        message="PARTIALLY_FILLED order has an invalid Fill quantity",
                    )
                )
            command = await uow.order_commands.get_submit_command_by_order(order.id)
            outbox = await uow.outbox.list_by_aggregate("ORDER", order.id)
            if (
                command is not None
                and command.status is CommandStatus.CONSUMED
                and (
                    not outbox or any(item.status is not OutboxStatus.SUPPRESSED for item in outbox)
                )
            ):
                issues.append(
                    SimulatedExecutionIntegrityIssue(
                        order_id=order.id,
                        code="CONSUMED_COMMAND_OUTBOX_PUBLISHABLE",
                        message="locally consumed command has a publishable outbox",
                    )
                )
            if b01_fills:
                reconciliation = await uow.account_reconciliations.latest(order.account_id)
                if (
                    reconciliation is None
                    or reconciliation.status is not ReconciliationStatus.MATCHED
                ):
                    issues.append(
                        SimulatedExecutionIntegrityIssue(
                            order_id=order.id,
                            code="ACCOUNT_RECONCILIATION_NOT_MATCHED",
                            message="latest post-fill reconciliation is not MATCHED",
                        )
                    )
            return issues


class SimulatedExecutionQueryService:
    """Read-only execution and Fill projections used by B01-C transports."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory
        self._integrity = SimulatedExecutionIntegrityService(uow_factory)

    async def by_order(self, order_id: UUID) -> dict[str, object]:
        async with self._uow_factory() as uow:
            order = await uow.orders.get_by_id(order_id)
            if order is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
            attempts = await uow.broker_execution_attempts.list_by_order(order_id)
            fills = await uow.fills.list_by_order(order_id)
        filled = sum((fill.quantity for fill in fills), ZERO)
        fees = sum((fill.commission + fill.tax + fill.other_fee for fill in fills), ZERO)
        issues = await self._integrity.verify_order(order_id)
        return {
            "order_id": order.id,
            "attempts": attempts,
            "fills": fills,
            "filled_quantity": filled,
            "remaining_quantity": order.requested_quantity - filled,
            "total_fee": fees,
            "latest_result_status": attempts[-1].result_status if attempts else None,
            "integrity_issues": issues,
        }

    async def by_execution_attempt(self, attempt_id: UUID) -> dict[str, object]:
        async with self._uow_factory() as uow:
            attempt = await uow.broker_execution_attempts.get_by_id(attempt_id)
            if attempt is None:
                raise ApplicationError(
                    "BROKER_EXECUTION_ATTEMPT_NOT_FOUND", "execution attempt was not found"
                )
            fills = await uow.fills.list_by_execution_attempt(attempt_id)
        return {"attempt": attempt, "fills": fills}

    async def list_attempts(
        self, order_id: UUID, *, page: int = 1, page_size: int = 20
    ) -> dict[str, object]:
        async with self._uow_factory() as uow:
            order = await uow.orders.get_by_id(order_id)
            if order is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
            attempts = await uow.broker_execution_attempts.list_by_order(order_id)
        start = (page - 1) * page_size
        return {
            "items": attempts[start : start + page_size],
            "page": page,
            "page_size": page_size,
            "total": len(attempts),
        }

    async def list_fills(
        self,
        *,
        account_id: UUID | None = None,
        instrument_id: UUID | None = None,
        order_id: UUID | None = None,
        side: str | None = None,
        executed_from: datetime | None = None,
        executed_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, object]:
        if side is not None and side not in {item.value for item in OrderSide}:
            raise ApplicationError("BROKER_EXECUTION_INVALID_REQUEST", "side is invalid")
        if executed_from is not None:
            executed_from = as_utc(executed_from, "executed_from")
        if executed_to is not None:
            executed_to = as_utc(executed_to, "executed_to")
        if executed_from is not None and executed_to is not None and executed_from > executed_to:
            raise ApplicationError(
                "BROKER_EXECUTION_INVALID_REQUEST", "executed_from must not exceed executed_to"
            )
        async with self._uow_factory() as uow:
            fills, total = await uow.fills.list(
                offset=(page - 1) * page_size,
                limit=page_size,
                account_id=account_id,
                instrument_id=instrument_id,
                order_id=order_id,
                side=side,
                executed_from=executed_from,
                executed_to=executed_to,
            )
            items = [await self._fill_view(uow, fill) for fill in fills]
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    async def fill_detail(self, fill_id: UUID) -> dict[str, object]:
        async with self._uow_factory() as uow:
            fill = await uow.fills.get_by_id(fill_id)
            if fill is None:
                raise ApplicationError("FILL_NOT_FOUND", "Fill was not found")
            return await self._fill_view(uow, fill)

    async def execution_detail(self, attempt_id: UUID) -> dict[str, object]:
        async with self._uow_factory() as uow:
            attempt = await uow.broker_execution_attempts.get_by_id(attempt_id)
            if attempt is None:
                raise ApplicationError(
                    "BROKER_EXECUTION_ATTEMPT_NOT_FOUND", "execution attempt was not found"
                )
            order = await uow.orders.get_by_id(attempt.order_id)
            if order is None:
                raise ApplicationError("ORDER_NOT_FOUND", "order was not found")
            fills = await uow.fills.list_by_execution_attempt(attempt_id)
            fill_views = [await self._fill_view(uow, fill) for fill in fills]
            transitions = await uow.order_state_transitions.list_by_order(order.id)
        issues = await self._integrity.verify_order(order.id)
        total_fee = sum((fill.commission + fill.tax + fill.other_fee for fill in fills), ZERO)
        return {
            "attempt": attempt,
            "order_status": order.status,
            "order_transitions": transitions,
            "fills": fill_views,
            "total_fee": total_fee,
            "integrity_issues": issues,
        }

    @staticmethod
    async def _fill_view(uow: UnitOfWork, fill: Fill) -> dict[str, object]:
        order = await uow.orders.get_by_id(fill.order_id)
        account = await uow.accounts.get_by_id(fill.account_id)
        instrument = await uow.instruments.get_by_id(fill.instrument_id)
        if order is None or account is None or instrument is None:
            raise ApplicationError("FILL_INTEGRITY_ERROR", "Fill references are incomplete")
        transfer_fee = Decimal(str(fill.metadata.get("transfer_fee", "0")))
        explicit_other_fee = fill.metadata.get("other_fee")
        other_fee = (
            Decimal(str(explicit_other_fee))
            if explicit_other_fee is not None
            else fill.other_fee - transfer_fee
        )
        total_fee = fill.commission + fill.tax + transfer_fee + other_fee
        return {
            "fill_id": fill.id,
            "execution_attempt_id": fill.execution_attempt_id,
            "order_id": fill.order_id,
            "account": {"id": account.id, "code": account.account_code, "name": account.name},
            "instrument": {
                "id": instrument.id,
                "symbol": instrument.symbol,
                "exchange": instrument.exchange,
                "name": instrument.name,
            },
            "side": order.side,
            "quantity": fill.quantity,
            "price": fill.price,
            "gross_amount": fill.gross_amount,
            "commission": fill.commission,
            "stamp_duty": fill.tax,
            "transfer_fee": transfer_fee,
            "other_fee": other_fee,
            "total_fee": total_fee,
            "net_cash_effect": -fill.net_amount if order.side is OrderSide.BUY else fill.net_amount,
            "executed_at": fill.executed_at,
            "execution_reference": fill.execution_reference,
            "correlation_id": fill.correlation_id,
        }
