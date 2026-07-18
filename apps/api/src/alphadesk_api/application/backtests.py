"""BT01 synchronous daily backtest orchestration and read models."""

from __future__ import annotations

import builtins
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import ROUND_FLOOR, Decimal
from itertools import pairwise
from typing import TypedDict
from uuid import UUID, uuid4

from alphadesk_api.application.accounting import (
    KnownPriceAccountValuationService,
    SimulatedAccountService,
)
from alphadesk_api.application.common import (
    ApplicationError,
    UnitOfWorkFactory,
    append_event_and_audit,
)
from alphadesk_api.application.orders import ConfirmOrderRequest, OrderConfirmationService
from alphadesk_api.application.orders import CreateOrderRequest as CreateM05OrderRequest
from alphadesk_api.application.risk import (
    ConfiguredRiskLimitsProvider,
    RiskGatedOrderService,
    SignalRiskAssessmentService,
)
from alphadesk_api.application.simulated_execution import (
    BACKTEST_SUPPRESSION_REASON,
    SimulatedBrokerExecutionService,
    SimulatedExecutionMarketInput,
)
from alphadesk_api.application.strategy_runner import (
    persisted_signal_from_draft,
    validate_signal_draft,
)
from alphadesk_api.core.config import Settings
from alphadesk_domain.backtest import (
    ASHARE_TIMEZONE,
    BacktestClock,
    BacktestConfiguration,
    BacktestEquityPoint,
    BacktestError,
    BacktestEvent,
    BacktestEventType,
    BacktestFillMetricInput,
    BacktestMetricSet,
    BacktestPerformanceService,
    BacktestPhase,
    BacktestRun,
    BacktestRunStatus,
    BacktestSession,
    BacktestTradeSummary,
    backtest_configuration_to_dict,
    backtest_request_fingerprint,
    build_equity_points,
)
from alphadesk_domain.broker import (
    AshareSimpleFeeModel,
    FixedBasisPointsSlippageModel,
    SimulatedBrokerAdapter,
    TradingStatus,
)
from alphadesk_domain.entities import Fill, Order, OrderStateTransition, RiskDecision, Signal
from alphadesk_domain.enums import (
    MarketTimeframe,
    OrderActorType,
    OrderIntentSource,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskDecisionType,
    SettlementPolicy,
    TimeInForce,
)
from alphadesk_domain.order_workflow import OrderStateMachine
from alphadesk_domain.strategy import (
    StrategyBar,
    StrategyContext,
    StrategyEnvironment,
    StrategyParameterValue,
    StrategyRegistry,
)
from alphadesk_domain.strategy_runs import StrategyRun, StrategyRunStatus, stored_parameters

ZERO = Decimal("0")
EIGHT_PLACES = Decimal("0.00000001")
TWELVE_PLACES = Decimal("0.000000000001")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateBacktestRequest:
    strategy_key: str
    parameters: Mapping[str, StrategyParameterValue]
    instrument_ids: tuple[UUID, ...]
    timeframe: MarketTimeframe
    start_at: datetime
    end_at: datetime
    initial_cash: Decimal
    order_type: OrderType
    time_in_force: TimeInForce
    fee_configuration: AshareSimpleFeeModel
    slippage_configuration: FixedBasisPointsSlippageModel
    maximum_volume_participation: Decimal | None
    benchmark_symbol: str | None
    idempotency_key: str
    risk_configuration_reference: str = "r01-default-v1"
    correlation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class BacktestRunResult:
    run: BacktestRun
    metrics: BacktestMetricSet | None
    replayed: bool = False


@dataclass(slots=True)
class _OpenLot:
    opened_at: datetime
    quantity: Decimal
    price: Decimal
    remaining_entry_fees: Decimal


class BacktestPageResult(TypedDict):
    items: builtins.list[dict[str, object]]
    page: int
    page_size: int
    total: int


def _safe_failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, BacktestError | ApplicationError):
        return exc.code, str(exc)[:512]
    return "BACKTEST_EXECUTION_FAILED", "backtest execution failed"


def _bar_date(bar: StrategyBar) -> date:
    return bar.timestamp.astimezone(ASHARE_TIMEZONE).date()


def _next_dates(bars: list[StrategyBar]) -> dict[tuple[UUID, date], date]:
    dates: dict[UUID, list[date]] = defaultdict(list)
    for bar in bars:
        trading_date = _bar_date(bar)
        if not dates[bar.instrument_id] or dates[bar.instrument_id][-1] != trading_date:
            dates[bar.instrument_id].append(trading_date)
    result: dict[tuple[UUID, date], date] = {}
    for instrument_id, values in dates.items():
        for current, following in pairwise(values):
            result[(instrument_id, current)] = following
    return result


def _available_volume(bar: StrategyBar, participation: Decimal | None, lot: Decimal) -> Decimal:
    permitted = bar.volume if participation is None else bar.volume * participation
    lots = (permitted / lot).to_integral_value(rounding=ROUND_FLOOR)
    return lots * lot


def _fill_fees(fill: Fill) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    transfer = Decimal(str(fill.metadata.get("transfer_fee", "0")))
    other = max(fill.other_fee - transfer, ZERO)
    return fill.commission, fill.tax, transfer, other


def _metric_signature(metric: BacktestMetricSet) -> dict[str, object]:
    values = asdict(metric)
    values.pop("id")
    values.pop("created_at")
    twelve_scale = {"sharpe_ratio", "profit_factor"}
    for name, value in tuple(values.items()):
        if isinstance(value, Decimal):
            values[name] = value.quantize(TWELVE_PLACES if name in twelve_scale else EIGHT_PLACES)
    return values


class BacktestService:
    """Run one deterministic backtest without network, Redis or a real broker."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: StrategyRegistry,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._settings = settings
        self._limits = ConfiguredRiskLimitsProvider(settings)

    async def run(self, request: CreateBacktestRequest) -> BacktestRunResult:
        metadata = self._registry.get(request.strategy_key)
        parameters = self._registry.validate_parameters(request.strategy_key, request.parameters)
        configuration = BacktestConfiguration(
            strategy_key=request.strategy_key,
            strategy_version=metadata.version,
            parameters=parameters,
            instrument_ids=request.instrument_ids,
            timeframe=request.timeframe,
            start_at=request.start_at,
            end_at=request.end_at,
            initial_cash=request.initial_cash,
            order_type=request.order_type,
            time_in_force=request.time_in_force,
            fee_configuration=request.fee_configuration,
            slippage_configuration=request.slippage_configuration,
            risk_configuration_reference=request.risk_configuration_reference,
            maximum_volume_participation=request.maximum_volume_participation,
            benchmark_symbol=request.benchmark_symbol,
        )
        if len(configuration.instrument_ids) > self._settings.backtest_max_instruments:
            raise ApplicationError(
                "BACKTEST_TOO_MANY_INSTRUMENTS", "instrument count exceeds the configured limit"
            )
        fingerprint = backtest_request_fingerprint(configuration)
        correlation_id = request.correlation_id or uuid4()
        async with self._uow_factory() as uow:
            existing = await uow.backtest_runs.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ApplicationError(
                        "BACKTEST_IDEMPOTENCY_CONFLICT",
                        "idempotency key was used with another configuration",
                    )
                return BacktestRunResult(
                    existing,
                    await uow.backtest_metrics.get_by_run(existing.id),
                    replayed=True,
                )
            run = BacktestRun(
                idempotency_key=request.idempotency_key,
                request_fingerprint=fingerprint,
                configuration=configuration,
                correlation_id=correlation_id,
            )
            await uow.backtest_runs.add(run)
            await uow.backtest_events.append(
                BacktestEvent(
                    run_id=run.id,
                    event_type=BacktestEventType.RUN_CREATED,
                    occurred_at=configuration.start_at,
                    sequence_number=1,
                    summary="Backtest run created",
                )
            )
            await uow.commit()

        try:
            return await self._execute(run, parameters)
        except Exception as exc:
            code, message = _safe_failure(exc)
            run.mark_failed(configuration.end_at, code, message)
            async with self._uow_factory() as uow:
                persisted = await uow.backtest_runs.get_for_update(run.id)
                if persisted is not None and persisted.status is not BacktestRunStatus.COMPLETED:
                    persisted.mark_failed(configuration.end_at, code, message)
                    await uow.backtest_runs.update_status(persisted)
                    if persisted.strategy_run_id is not None:
                        failed_strategy_run = await uow.strategy_runs.get_by_id(
                            persisted.strategy_run_id
                        )
                        if (
                            failed_strategy_run is not None
                            and failed_strategy_run.status is not StrategyRunStatus.COMPLETED
                        ):
                            failed_strategy_run.mark_failed(configuration.end_at, code, message)
                            await uow.strategy_runs.update(failed_strategy_run)
                    count = len(await uow.backtest_events.list_by_run(run.id))
                    await uow.backtest_events.append(
                        BacktestEvent(
                            run_id=run.id,
                            event_type=BacktestEventType.RUN_FAILED,
                            occurred_at=configuration.end_at,
                            sequence_number=count + 1,
                            summary=message,
                            details={"error_code": code},
                        )
                    )
                    await uow.commit()
                    run = persisted
            return BacktestRunResult(run, None)

    async def _execute(
        self,
        run: BacktestRun,
        parameters: Mapping[str, StrategyParameterValue],
    ) -> BacktestRunResult:
        config = run.configuration
        async with self._uow_factory() as uow:
            bars = await uow.historical_bars.list_bars(
                instrument_ids=config.instrument_ids,
                timeframe=config.timeframe,
                start_at=config.start_at,
                end_at=config.end_at,
            )
        if not bars:
            raise ApplicationError("BACKTEST_NO_MARKET_DATA", "no local daily bars were found")
        if len(bars) > self._settings.backtest_max_bars:
            raise ApplicationError("BACKTEST_TOO_MANY_BARS", "bar count exceeds configured limit")

        bars_by_date: dict[date, dict[UUID, StrategyBar]] = defaultdict(dict)
        for bar in bars:
            trading_date = _bar_date(bar)
            if bar.instrument_id in bars_by_date[trading_date]:
                raise ApplicationError(
                    "BACKTEST_INVALID_CONFIGURATION", "duplicate instrument daily bar"
                )
            bars_by_date[trading_date][bar.instrument_id] = bar
        sessions = [
            BacktestSession(
                trading_date=trading_date,
                instrument_ids=tuple(day_bars),
            )
            for trading_date, day_bars in bars_by_date.items()
        ]
        if len(sessions) > self._settings.backtest_max_sessions:
            raise ApplicationError(
                "BACKTEST_TOO_MANY_SESSIONS", "session count exceeds configured limit"
            )
        clock = BacktestClock(sessions)

        account = await SimulatedAccountService(self._uow_factory).create(
            account_code=f"BT-{str(run.id)[:12].upper()}",
            name=f"Backtest {str(run.id)[:8]}",
            base_currency="CNY",
            initial_cash=config.initial_cash,
            settlement_policy=SettlementPolicy.IMMEDIATE,
            idempotency_key=f"bt:{run.id}:account",
            correlation_id=run.correlation_id,
            occurred_at=config.start_at,
            scope="BT01",
            owner_id=run.id,
        )
        strategy_run = StrategyRun(
            idempotency_key=f"bt:{run.id}:strategy",
            request_fingerprint=run.request_fingerprint,
            strategy_key=config.strategy_key,
            strategy_version=config.strategy_version,
            environment=StrategyEnvironment.BACKTEST,
            timeframe=config.timeframe,
            start_at=config.start_at,
            end_at=config.end_at,
            parameters=stored_parameters(parameters),
            instrument_ids=config.instrument_ids,
            status=StrategyRunStatus.CREATED,
            correlation_id=run.correlation_id,
        )
        strategy_run.mark_running(clock.current_time)
        run.account_id = account.id
        run.strategy_run_id = strategy_run.id
        run.mark_running(clock.current_time)
        async with self._uow_factory() as uow:
            record = await uow.strategies.get_by_business_key(config.strategy_key)
            strategy_run.strategy_id = None if record is None else record.id
            await uow.strategy_runs.add(strategy_run)
            await uow.backtest_runs.update_status(run)
            await uow.backtest_events.append(
                BacktestEvent(
                    run_id=run.id,
                    event_type=BacktestEventType.RUN_STARTED,
                    occurred_at=clock.current_time,
                    sequence_number=2,
                    summary="Backtest event loop started",
                    details={"account_id": str(account.id)},
                )
            )
            await uow.commit()

        strategy = self._registry.create_instance(config.strategy_key, parameters)
        context = StrategyContext(
            strategy_key=config.strategy_key,
            strategy_version=config.strategy_version,
            run_id=strategy_run.id,
            current_time=clock.current_time,
            parameters=parameters,
            environment=StrategyEnvironment.BACKTEST,
        )
        strategy.initialize(context)
        execution = SimulatedBrokerExecutionService(
            self._uow_factory,
            adapter=SimulatedBrokerAdapter(
                fee_model=config.fee_configuration,
                slippage_model=config.slippage_configuration,
            ),
        )
        risk_orders = RiskGatedOrderService(self._uow_factory, self._limits)
        signal_risk = SignalRiskAssessmentService(self._uow_factory, self._limits)
        confirmation = OrderConfirmationService(self._uow_factory)
        pending: dict[UUID, list[Order]] = defaultdict(list)
        sequence = 0
        event_sequence = 2
        next_date = _next_dates(bars)
        latest_close: dict[UUID, Decimal] = {}
        equity_snapshots: list[
            tuple[datetime, Decimal, Decimal, Decimal, Decimal, int, tuple[str, ...]]
        ] = []
        metric_fills: list[BacktestFillMetricInput] = []
        trades: list[BacktestTradeSummary] = []
        lots: dict[UUID, deque[_OpenLot]] = defaultdict(deque)

        while not clock.is_complete:
            session = clock.current_session
            phase = clock.current_phase
            current_time = clock.current_time
            day_bars = bars_by_date[session.trading_date]
            context.advance_time(current_time)
            if phase is BacktestPhase.SESSION_OPEN:
                event_sequence += 1
                await self._event(
                    run.id,
                    event_sequence,
                    BacktestEventType.SESSION_OPEN,
                    current_time,
                    f"Session {session.trading_date} open",
                )
                for instrument_id in sorted(day_bars, key=str):
                    bar = day_bars[instrument_id]
                    executable = list(pending[instrument_id])
                    pending[instrument_id].clear()
                    async with self._uow_factory() as uow:
                        instrument = await uow.instruments.get_by_id(instrument_id)
                    if instrument is None:
                        raise ApplicationError("INSTRUMENT_NOT_FOUND", "instrument was not found")
                    for order in executable:
                        result = await execution.execute_market_input(
                            SimulatedExecutionMarketInput(
                                order_id=order.id,
                                idempotency_key=f"bt:{run.id}:execute:{order.id}:{session.trading_date}",
                                correlation_id=run.correlation_id,
                                timestamp=current_time,
                                trading_status=TradingStatus.TRADING,
                                source="BACKTEST_DAILY_BAR",
                                is_stale=False,
                                open=bar.open,
                                last_price=bar.open,
                                bid_price=bar.open,
                                ask_price=bar.open,
                                available_volume=_available_volume(
                                    bar,
                                    config.maximum_volume_participation,
                                    instrument.lot_size,
                                ),
                            )
                        )
                        run.fills_generated += len(result.fills)
                        for fill in result.fills:
                            fees = _fill_fees(fill)
                            metric_fills.append(
                                BacktestFillMetricInput(
                                    side=result.order.side,
                                    quantity=fill.quantity,
                                    price=fill.price,
                                    commission=fees[0],
                                    stamp_duty=fees[1],
                                    transfer_fee=fees[2],
                                    other_fee=fees[3],
                                )
                            )
                            self._record_trade(
                                run.id, result.order, fill, sum(fees, ZERO), lots, trades
                            )
                        if config.time_in_force is TimeInForce.DAY:
                            await self._expire_day_order(result.order.id, current_time, run)
                        elif result.order.status is not OrderStatus.FILLED:
                            pending[instrument_id].append(result.order)

            elif phase is BacktestPhase.SESSION_CLOSE:
                event_sequence += 1
                await self._event(
                    run.id,
                    event_sequence,
                    BacktestEventType.SESSION_CLOSE,
                    current_time,
                    f"Session {session.trading_date} close",
                )
                for instrument_id in sorted(day_bars, key=str):
                    bar = day_bars[instrument_id]
                    run.bars_processed += 1
                    for draft in strategy.on_bar(context, bar):
                        validate_signal_draft(
                            draft,
                            run=strategy_run,
                            current_bar_instrument_id=bar.instrument_id,
                            current_bar_timestamp=bar.timestamp,
                            expected_generated_at=current_time,
                        )
                        sequence += 1
                        signal = persisted_signal_from_draft(
                            strategy_run, draft, sequence, account_id=account.id
                        )
                        signal.valid_until = config.end_at
                        async with self._uow_factory() as uow:
                            await uow.signals.add(signal)
                            await uow.commit()
                        run.signals_generated += 1
                        outcome, returned_order = await self._signal_to_order(
                            run,
                            signal,
                            bar,
                            current_time,
                            next_date.get((instrument_id, session.trading_date)),
                            risk_orders,
                            signal_risk,
                            confirmation,
                        )
                        if outcome is RiskDecisionType.ALLOW:
                            run.risk_passed += 1
                        elif outcome is RiskDecisionType.REJECT:
                            run.risk_rejected += 1
                        else:
                            run.risk_reviewed += 1
                        if returned_order is not None:
                            run.orders_created += 1
                            pending[instrument_id].append(returned_order)

            else:
                for instrument_id, bar in day_bars.items():
                    latest_close[instrument_id] = bar.close
                equity_snapshots.append(
                    await self._valuation_snapshot(
                        account.id,
                        current_time,
                        latest_close,
                        day_bars,
                        run.correlation_id,
                    )
                )
                run.sessions_processed += 1
                event_sequence += 1
                await self._event(
                    run.id,
                    event_sequence,
                    BacktestEventType.SESSION_END,
                    current_time,
                    f"Session {session.trading_date} valued",
                )
            clock.advance()

        strategy.finalize(context)
        for orders in pending.values():
            for order in orders:
                await self._expire_day_order(order.id, config.end_at, run)
        points = build_equity_points(
            run_id=run.id, initial_equity=config.initial_cash, snapshots=equity_snapshots
        )
        metrics = BacktestPerformanceService().calculate(
            run_id=run.id, equity_points=points, fills=metric_fills, trades=trades
        )
        strategy_run.mark_completed(config.end_at, run.bars_processed, run.signals_generated)
        run.mark_completed(config.end_at)
        async with self._uow_factory() as uow:
            for point in points:
                await uow.backtest_equity_points.append(point)
            await uow.backtest_trades.append_many(trades)
            await uow.backtest_metrics.save(metrics)
            await uow.strategy_runs.update(strategy_run)
            await uow.backtest_runs.update_status(run)
            await uow.backtest_events.append(
                BacktestEvent(
                    run_id=run.id,
                    event_type=BacktestEventType.RUN_COMPLETED,
                    occurred_at=config.end_at,
                    sequence_number=event_sequence + 1,
                    summary="Backtest completed",
                    details={"final_equity": str(metrics.final_equity)},
                )
            )
            await uow.commit()
        return BacktestRunResult(run, metrics)

    async def _signal_to_order(
        self,
        run: BacktestRun,
        signal: Signal,
        bar: StrategyBar,
        occurred_at: datetime,
        next_trading_date: date | None,
        risk_orders: RiskGatedOrderService,
        signal_risk: SignalRiskAssessmentService,
        confirmation: OrderConfirmationService,
    ) -> tuple[RiskDecisionType, Order | None]:
        if run.account_id is None:
            raise ApplicationError("BACKTEST_ACCOUNT_CREATION_FAILED", "run has no account")
        key = f"bt:{run.id}:signal:{signal.id}"
        if signal.target_quantity is None:
            outcome = await signal_risk.assess(
                signal.id,
                run.account_id,
                f"{key}:risk",
                run.correlation_id,
                reference_price=signal.reference_price,
            )
            return outcome.decision.overall_decision, None
        expires_at = run.configuration.end_at
        if next_trading_date is not None:
            expires_at = BacktestSession(
                trading_date=next_trading_date,
                instrument_ids=(signal.instrument_id,),
            ).time_for(BacktestPhase.SESSION_END)
        limit_price = (
            signal.reference_price if run.configuration.order_type is OrderType.LIMIT else None
        )
        outcome = await risk_orders.create(
            CreateM05OrderRequest(
                account_id=run.account_id,
                instrument_id=signal.instrument_id,
                side=signal.side.value,
                order_type=run.configuration.order_type.value,
                time_in_force=run.configuration.time_in_force.value,
                quantity=signal.target_quantity,
                limit_price=limit_price,
                expires_at=expires_at,
                idempotency_key=f"{key}:risk-order",
                correlation_id=run.correlation_id,
                actor_id="BACKTEST_ENGINE",
                actor_type=OrderActorType.SYSTEM,
                occurred_at=occurred_at,
                intent_source=OrderIntentSource.STRATEGY,
                source_id=signal.id,
                strategy_key=run.configuration.strategy_key,
                reference_price=signal.reference_price or bar.close,
            )
        )
        order = outcome.order
        if order is None:
            return outcome.decision.overall_decision, None
        confirmed = await confirmation.confirm(
            ConfirmOrderRequest(
                order_id=order.id,
                idempotency_key=f"{key}:confirm",
                expected_order_version=order.row_version,
                correlation_id=run.correlation_id,
                note="BT01 internal auto-confirmation",
                actor_type=OrderActorType.SYSTEM,
                actor_id="BACKTEST_ENGINE",
                occurred_at=occurred_at,
                suppress_outbox_reason=BACKTEST_SUPPRESSION_REASON,
            )
        )
        return outcome.decision.overall_decision, confirmed

    async def _valuation_snapshot(
        self,
        account_id: UUID,
        occurred_at: datetime,
        latest_close: Mapping[UUID, Decimal],
        day_bars: Mapping[UUID, StrategyBar],
        correlation_id: UUID,
    ) -> tuple[datetime, Decimal, Decimal, Decimal, Decimal, int, tuple[str, ...]]:
        async with self._uow_factory() as uow:
            positions = await uow.positions.list_for_account(account_id)
        held = {item.instrument_id for item in positions if item.total_quantity > ZERO}
        stale = held - set(day_bars)
        valuation = await KnownPriceAccountValuationService(self._uow_factory).value(
            account_id=account_id,
            prices=dict(latest_close),
            stale_instrument_ids=stale,
            as_of=occurred_at,
            correlation_id=correlation_id,
        )
        snapshot = valuation.snapshot
        assert snapshot.positions_market_value is not None and snapshot.total_equity is not None
        warnings = tuple(f"STALE_VALUATION:{item}" for item in sorted(stale, key=str))
        return (
            occurred_at,
            snapshot.cash_total,
            snapshot.positions_market_value,
            snapshot.positions_market_value,
            snapshot.positions_market_value,
            len(held),
            warnings,
        )

    async def _expire_day_order(
        self, order_id: UUID, occurred_at: datetime, run: BacktestRun
    ) -> None:
        async with self._uow_factory() as uow:
            order = await uow.orders.get_for_update(order_id)
            if order is None or order.status in OrderStateMachine.terminal_states:
                return
            if order.status is OrderStatus.QUEUED:
                path: tuple[OrderStatus, ...] = (OrderStatus.EXPIRED,)
            elif order.status in (OrderStatus.BROKER_ACCEPTED, OrderStatus.PARTIALLY_FILLED):
                path = (OrderStatus.CANCEL_PENDING, OrderStatus.CANCELLED)
            else:
                return
            for target in path:
                previous = order.status
                OrderStateMachine.require_transition(previous, target)
                order.status = target
                order.row_version += 1
                order.updated_at = occurred_at
                if target is OrderStatus.EXPIRED:
                    order.expired_at = occurred_at
                if target is OrderStatus.CANCELLED:
                    order.cancelled_at = occurred_at
                await uow.orders.update_projection(order)
                await uow.order_state_transitions.append(
                    OrderStateTransition(
                        order_id=order.id,
                        from_status=previous,
                        to_status=target,
                        actor_type=OrderActorType.SYSTEM,
                        actor_id="BACKTEST_ENGINE",
                        reason_code="BACKTEST_DAY_ORDER_ENDED",
                        correlation_id=run.correlation_id,
                        occurred_at=occurred_at,
                        order_version=order.row_version,
                    )
                )
            await append_event_and_audit(
                uow,
                event_type="BACKTEST_DAY_ORDER_ENDED",
                entity_type="ORDER",
                entity_id=order.id,
                correlation_id=run.correlation_id,
                payload={"status": order.status.value},
                source="ALPHADESK_BT01",
                actor_type=OrderActorType.SYSTEM,
                occurred_at=occurred_at,
            )
            await uow.commit()

    @staticmethod
    def _record_trade(
        run_id: UUID,
        order: Order,
        fill: Fill,
        fees: Decimal,
        lots: dict[UUID, deque[_OpenLot]],
        trades: list[BacktestTradeSummary],
    ) -> None:
        queue = lots[order.instrument_id]
        if order.side is OrderSide.BUY:
            queue.append(_OpenLot(fill.executed_at, fill.quantity, fill.price, fees))
            return
        remaining = fill.quantity
        sell_fee_remaining = fees
        while remaining > ZERO and queue:
            lot = queue[0]
            matched = min(remaining, lot.quantity)
            entry_fee = lot.remaining_entry_fees * matched / lot.quantity
            exit_fee = sell_fee_remaining * matched / remaining
            gross = (fill.price - lot.price) * matched
            trades.append(
                BacktestTradeSummary(
                    run_id=run_id,
                    instrument_id=order.instrument_id,
                    opened_at=lot.opened_at,
                    closed_at=fill.executed_at,
                    quantity=matched,
                    entry_price=lot.price,
                    exit_price=fill.price,
                    gross_pnl=gross,
                    fees=entry_fee + exit_fee,
                    net_pnl=gross - entry_fee - exit_fee,
                )
            )
            lot.quantity -= matched
            lot.remaining_entry_fees -= entry_fee
            remaining -= matched
            sell_fee_remaining -= exit_fee
            if lot.quantity == ZERO:
                queue.popleft()

    async def _event(
        self,
        run_id: UUID,
        sequence: int,
        event_type: BacktestEventType,
        occurred_at: datetime,
        summary: str,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.backtest_events.append(
                BacktestEvent(
                    run_id=run_id,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    sequence_number=sequence,
                    summary=summary,
                )
            )
            await uow.commit()


class BacktestQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list(self, *, page: int, page_size: int, status: str | None) -> BacktestPageResult:
        async with self._uow_factory() as uow:
            runs, total = await uow.backtest_runs.list(
                status=status, offset=(page - 1) * page_size, limit=page_size
            )
        return {
            "items": [self._run_view(run) for run in runs],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    async def detail(self, run_id: UUID) -> dict[str, object]:
        run = await self._require(run_id)
        async with self._uow_factory() as uow:
            metrics = await uow.backtest_metrics.get_by_run(run_id)
        result = self._run_view(run)
        result["configuration"] = backtest_configuration_to_dict(run.configuration)
        result["metrics"] = None if metrics is None else asdict(metrics)
        return result

    async def metrics(self, run_id: UUID) -> BacktestMetricSet:
        await self._require(run_id)
        async with self._uow_factory() as uow:
            result = await uow.backtest_metrics.get_by_run(run_id)
        if result is None:
            raise ApplicationError("BACKTEST_METRICS_FAILED", "metrics are not available")
        return result

    async def equity_curve(self, run_id: UUID) -> builtins.list[BacktestEquityPoint]:
        await self._require(run_id)
        async with self._uow_factory() as uow:
            return await uow.backtest_equity_points.list_by_run(run_id)

    async def trades(self, run_id: UUID) -> builtins.list[BacktestTradeSummary]:
        await self._require(run_id)
        async with self._uow_factory() as uow:
            return await uow.backtest_trades.list_by_run(run_id)

    async def signals(self, run_id: UUID) -> builtins.list[Signal]:
        run = await self._require(run_id)
        if run.strategy_run_id is None:
            return []
        async with self._uow_factory() as uow:
            signals, _ = await uow.signals.list_by_run(run.strategy_run_id, 0, 100_000)
        return signals

    async def orders(self, run_id: UUID) -> builtins.list[Order]:
        run = await self._require(run_id)
        if run.account_id is None:
            return []
        async with self._uow_factory() as uow:
            orders, _ = await uow.orders.list(offset=0, limit=100_000, account_id=run.account_id)
        return orders

    async def fills(self, run_id: UUID) -> builtins.list[Fill]:
        run = await self._require(run_id)
        if run.account_id is None:
            return []
        async with self._uow_factory() as uow:
            fills, _ = await uow.fills.list(offset=0, limit=100_000, account_id=run.account_id)
        return fills

    async def risk_decisions(self, run_id: UUID) -> builtins.list[RiskDecision]:
        run = await self._require(run_id)
        if run.account_id is None:
            return []
        async with self._uow_factory() as uow:
            decisions, _ = await uow.risk_decisions.list(
                offset=0, limit=100_000, account_id=run.account_id
            )
        return decisions

    async def timeline(self, run_id: UUID) -> builtins.list[BacktestEvent]:
        await self._require(run_id)
        async with self._uow_factory() as uow:
            return await uow.backtest_events.list_by_run(run_id)

    async def _require(self, run_id: UUID) -> BacktestRun:
        async with self._uow_factory() as uow:
            run = await uow.backtest_runs.get_by_id(run_id)
        if run is None:
            raise ApplicationError("BACKTEST_NOT_FOUND", "backtest was not found")
        return run

    @staticmethod
    def _run_view(run: BacktestRun) -> dict[str, object]:
        return {
            "id": run.id,
            "idempotency_key": run.idempotency_key,
            "strategy_key": run.configuration.strategy_key,
            "strategy_version": run.configuration.strategy_version,
            "status": run.status.value,
            "strategy_run_id": run.strategy_run_id,
            "account_id": run.account_id,
            "bars_processed": run.bars_processed,
            "sessions_processed": run.sessions_processed,
            "signals_generated": run.signals_generated,
            "risk_passed": run.risk_passed,
            "risk_rejected": run.risk_rejected,
            "risk_reviewed": run.risk_reviewed,
            "orders_created": run.orders_created,
            "fills_generated": run.fills_generated,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "failed_at": run.failed_at,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "created_at": run.created_at,
        }


@dataclass(frozen=True, slots=True)
class BacktestIntegrityIssue:
    code: str
    message: str
    entity_type: str
    entity_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class BacktestIntegrityReport:
    run_id: UUID
    passed: bool
    checked_at: datetime
    issues: tuple[BacktestIntegrityIssue, ...]


class BacktestIntegrityService:
    """Read-only cross-check of BT01 provenance and persisted facts."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def verify(self, run_id: UUID) -> BacktestIntegrityReport:
        query = BacktestQueryService(self._uow_factory)
        run = await query._require(run_id)
        issues: list[BacktestIntegrityIssue] = []
        async with self._uow_factory() as uow:
            account = (
                None if run.account_id is None else await uow.accounts.get_by_id(run.account_id)
            )
            strategy_run = (
                None
                if run.strategy_run_id is None
                else await uow.strategy_runs.get_by_id(run.strategy_run_id)
            )
            signals = (
                []
                if run.strategy_run_id is None
                else (await uow.signals.list_by_run(run.strategy_run_id, 0, 100_000))[0]
            )
            orders = (
                []
                if run.account_id is None
                else (await uow.orders.list(offset=0, limit=100_000, account_id=run.account_id))[0]
            )
            fills = (
                []
                if run.account_id is None
                else (await uow.fills.list(offset=0, limit=100_000, account_id=run.account_id))[0]
            )
            points = await uow.backtest_equity_points.list_by_run(run.id)
            metrics = await uow.backtest_metrics.get_by_run(run.id)
            trades = await uow.backtest_trades.list_by_run(run.id)
            risk_decisions = (
                []
                if run.account_id is None
                else (
                    await uow.risk_decisions.list(
                        offset=0, limit=100_000, account_id=run.account_id
                    )
                )[0]
            )
            latest_reconciliation = (
                None
                if run.account_id is None
                else await uow.account_reconciliations.latest(run.account_id)
            )
            attempts_by_order = {
                order.id: await uow.broker_execution_attempts.list_by_order(order.id)
                for order in orders
            }
            outbox_by_order = {
                order.id: await uow.outbox.list_by_aggregate("ORDER", order.id) for order in orders
            }

        if account is None or account.metadata.get("owner_id") != str(run.id):
            issues.append(
                BacktestIntegrityIssue(
                    "BACKTEST_ACCOUNT_OWNERSHIP_MISMATCH",
                    "run does not own exactly one BT01 account",
                    "TRADING_ACCOUNT",
                    run.account_id,
                )
            )
        if (
            strategy_run is None
            or strategy_run.environment is not StrategyEnvironment.BACKTEST
            or strategy_run.strategy_version != run.configuration.strategy_version
        ):
            issues.append(
                BacktestIntegrityIssue(
                    "BACKTEST_STRATEGY_VERSION_MISMATCH",
                    "strategy run provenance is missing or inconsistent",
                    "STRATEGY_RUN",
                    run.strategy_run_id,
                )
            )
        signal_by_id = {signal.id: signal for signal in signals}
        for signal in signals:
            if signal.bar_timestamp is None or signal.generated_at < signal.bar_timestamp:
                issues.append(
                    BacktestIntegrityIssue(
                        "BACKTEST_SIGNAL_TIME_INVALID",
                        "signal predates its source bar",
                        "SIGNAL",
                        signal.id,
                    )
                )
        allow_by_order = {
            item.order_id: item
            for item in risk_decisions
            if item.overall_decision is RiskDecisionType.ALLOW and item.order_id is not None
        }
        fill_quantity: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
        for fill in fills:
            fill_quantity[fill.order_id] += fill.quantity
        for order in orders:
            linked_signal = None if order.signal_id is None else signal_by_id.get(order.signal_id)
            if order.intent_source != OrderIntentSource.STRATEGY or linked_signal is None:
                issues.append(
                    BacktestIntegrityIssue(
                        "BACKTEST_ORDER_PROVENANCE_INVALID",
                        "backtest order does not reference a persisted strategy signal",
                        "ORDER",
                        order.id,
                    )
                )
            if order.id not in allow_by_order:
                issues.append(
                    BacktestIntegrityIssue(
                        "BACKTEST_ORDER_RISK_MISSING",
                        "order has no ALLOW risk decision",
                        "ORDER",
                        order.id,
                    )
                )
            if fill_quantity[order.id] > order.requested_quantity:
                issues.append(
                    BacktestIntegrityIssue(
                        "BACKTEST_FILL_QUANTITY_EXCEEDED",
                        "fill quantity exceeds requested quantity",
                        "ORDER",
                        order.id,
                    )
                )
            if linked_signal is not None:
                for attempt in attempts_by_order[order.id]:
                    if attempt.started_at <= linked_signal.generated_at:
                        issues.append(
                            BacktestIntegrityIssue(
                                "BACKTEST_FUTURE_EXECUTION_RULE_BROKEN",
                                "execution attempt is not later than the signal",
                                "BROKER_EXECUTION_ATTEMPT",
                                attempt.id,
                            )
                        )
            outboxes = outbox_by_order[order.id]
            if len(outboxes) != 1 or any(
                item.status.value != "SUPPRESSED"
                or item.suppression_reason != BACKTEST_SUPPRESSION_REASON
                for item in outboxes
            ):
                issues.append(
                    BacktestIntegrityIssue(
                        "BACKTEST_OUTBOX_NOT_SUPPRESSED",
                        "backtest order outbox is not BACKTEST_ENGINE suppressed",
                        "ORDER",
                        order.id,
                    )
                )
        timestamps = [point.timestamp for point in points]
        if timestamps != sorted(set(timestamps)):
            issues.append(
                BacktestIntegrityIssue(
                    "BACKTEST_EQUITY_SEQUENCE_INVALID",
                    "equity timestamps are not unique and ordered",
                    "BACKTEST_RUN",
                    run.id,
                )
            )
        if metrics is not None and (not points or metrics.final_equity != points[-1].total_equity):
            issues.append(
                BacktestIntegrityIssue(
                    "BACKTEST_METRICS_EQUITY_MISMATCH",
                    "metrics final equity differs from the final equity point",
                    "BACKTEST_METRICS",
                    metrics.id,
                )
            )
        if metrics is not None and points:
            fill_inputs = []
            for fill in fills:
                commission, stamp_duty, transfer_fee, other_fee = _fill_fees(fill)
                fill_order = next((item for item in orders if item.id == fill.order_id), None)
                if fill_order is not None:
                    fill_inputs.append(
                        BacktestFillMetricInput(
                            side=fill_order.side,
                            quantity=fill.quantity,
                            price=fill.price,
                            commission=commission,
                            stamp_duty=stamp_duty,
                            transfer_fee=transfer_fee,
                            other_fee=other_fee,
                        )
                    )
            recomputed = BacktestPerformanceService().calculate(
                run_id=run.id,
                equity_points=points,
                fills=fill_inputs,
                trades=trades,
            )
            if _metric_signature(metrics) != _metric_signature(recomputed):
                issues.append(
                    BacktestIntegrityIssue(
                        "BACKTEST_METRICS_RECOMPUTE_MISMATCH",
                        "persisted metrics differ from equity, fill and trade facts",
                        "BACKTEST_METRICS",
                        metrics.id,
                    )
                )
        if fills and (
            latest_reconciliation is None or latest_reconciliation.status.value != "MATCHED"
        ):
            issues.append(
                BacktestIntegrityIssue(
                    "BACKTEST_RECONCILIATION_MISMATCH",
                    "latest M04 reconciliation is not MATCHED",
                    "TRADING_ACCOUNT",
                    run.account_id,
                )
            )
        return BacktestIntegrityReport(
            run_id=run.id,
            passed=not issues,
            checked_at=run.completed_at or run.failed_at or run.updated_at,
            issues=tuple(issues),
        )
