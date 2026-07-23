"""RT01 historical daily replay orchestration, queries and integrity checks."""

from __future__ import annotations

import builtins
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from enum import Enum
from itertools import pairwise
from typing import Any, TypedDict, cast
from uuid import UUID, uuid4

from alphadesk_api.application.accounting import (
    KnownPriceAccountValuationService,
    SimulatedAccountService,
)
from alphadesk_api.application.backtests import _CapturedRiskLimitsProvider, _fill_fees
from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.orders import ConfirmOrderRequest, OrderConfirmationService
from alphadesk_api.application.orders import CreateOrderRequest as CreateM05OrderRequest
from alphadesk_api.application.risk import (
    ConfiguredRiskLimitsProvider,
    RiskGatedOrderService,
    SignalRiskAssessmentService,
)
from alphadesk_api.application.simulated_execution import (
    REPLAY_SUPPRESSION_REASON,
    SimulatedBrokerExecutionService,
    SimulatedExecutionMarketInput,
)
from alphadesk_api.application.strategies import StrategyResearchService
from alphadesk_api.application.strategy_runner import (
    persisted_signal_from_draft,
    validate_signal_draft,
)
from alphadesk_api.core.config import Settings
from alphadesk_domain.backtest import (
    ASHARE_TIMEZONE,
    BacktestConfiguration,
    BacktestEquityPoint,
    BacktestFillMetricInput,
    BacktestPerformanceService,
    BacktestPhase,
    BacktestRiskConfigurationSnapshot,
    BacktestSession,
    BacktestTradeSummary,
    HistoricalSessionProcessor,
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
    AdjustmentType,
    MarketDataQualityStatus,
    MarketDataReadinessStatus,
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
from alphadesk_domain.market_reference import InstrumentTradingState, PriceAdjustmentMode
from alphadesk_domain.order_workflow import OrderStateMachine
from alphadesk_domain.replay import (
    TERMINAL_REPLAY_STATUSES,
    ReplayActorType,
    ReplayConfiguration,
    ReplayControlAction,
    ReplayControlActionType,
    ReplayEvent,
    ReplayEventType,
    ReplayIntegrityReport,
    ReplayRun,
    ReplayRunStatus,
    ReplaySessionResult,
    ReplaySpeedMode,
    replay_action_fingerprint,
    replay_configuration_to_dict,
    replay_request_fingerprint,
)
from alphadesk_domain.strategy import (
    StrategyBar,
    StrategyContext,
    StrategyEnvironment,
    StrategyParameterValue,
    StrategyRegistry,
)
from alphadesk_domain.strategy_runs import StrategyRun, StrategyRunStatus, stored_parameters
from alphadesk_domain.values import utc_now

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateReplayRequest:
    strategy_key: str
    parameters: Mapping[str, StrategyParameterValue]
    instrument_ids: tuple[UUID, ...]
    start_at: datetime
    end_at: datetime
    initial_cash: Decimal
    order_type: OrderType
    time_in_force: TimeInForce
    fee_configuration: AshareSimpleFeeModel
    slippage_configuration: FixedBasisPointsSlippageModel
    maximum_volume_participation: Decimal | None
    speed_mode: ReplaySpeedMode
    idempotency_key: str
    risk_configuration_reference: str = "r01-default-v1"
    data_source_code: str | None = None
    correlation_id: UUID | None = None
    strategy_price_adjustment_mode: PriceAdjustmentMode = PriceAdjustmentMode.RAW


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplayControlRequest:
    replay_run_id: UUID
    action_type: ReplayControlActionType
    idempotency_key: str
    expected_run_version: int
    requested_speed: ReplaySpeedMode | None = None
    actor_type: ReplayActorType = ReplayActorType.LOCAL_USER
    actor_id: str | None = None
    correlation_id: UUID | None = None
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReplayCreateResult:
    run: ReplayRun
    replayed: bool = False


class ReplayPageResult(TypedDict):
    items: builtins.list[dict[str, object]]
    page: int
    page_size: int
    total: int


def _bar_date(bar: StrategyBar) -> date:
    return bar.timestamp.astimezone(ASHARE_TIMEZONE).date()


def _available_volume(bar: StrategyBar, participation: Decimal | None, lot: Decimal) -> Decimal:
    permitted = bar.volume if participation is None else bar.volume * participation
    return (permitted / lot).to_integral_value(rounding=ROUND_FLOOR) * lot


def _next_dates(bars: list[StrategyBar]) -> dict[tuple[UUID, date], date]:
    dates: dict[UUID, list[date]] = defaultdict(list)
    for bar in bars:
        current = _bar_date(bar)
        if not dates[bar.instrument_id] or dates[bar.instrument_id][-1] != current:
            dates[bar.instrument_id].append(current)
    return {
        (instrument_id, current): following
        for instrument_id, values in dates.items()
        for current, following in pairwise(values)
    }


def _json(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json(item) for item in value]
    return value


class ReplayEventPublisher:
    """Best-effort post-commit notifier; PostgreSQL remains authoritative."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    async def publish(self, event: ReplayEvent) -> None:
        if self._redis is None:
            return
        try:
            import json

            await self._redis.publish(
                f"alphadesk:replays:v1:{event.replay_run_id}",
                json.dumps(event.envelope(), ensure_ascii=True),
            )
        except Exception:
            # Delivery is recoverable from GET /events?after_sequence=N.
            return


class ReplayService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: StrategyRegistry,
        settings: Settings,
        publisher: ReplayEventPublisher | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._settings = settings
        self._limits = ConfiguredRiskLimitsProvider(settings)
        self._publisher = publisher or ReplayEventPublisher()

    async def create(self, request: CreateReplayRequest) -> ReplayCreateResult:
        metadata = self._registry.get(request.strategy_key)
        parameters = self._registry.validate_parameters(request.strategy_key, request.parameters)
        limits = self._limits.get_limits(UUID(int=0))
        risk_snapshot = BacktestRiskConfigurationSnapshot(
            reference=request.risk_configuration_reference,
            limits_version_marker=self._limits.version_marker,
            max_order_notional=limits.max_order_notional,
            max_instrument_weight=limits.max_instrument_weight,
            max_total_exposure=limits.max_total_exposure,
            max_orders_per_window=limits.max_orders_per_window,
            order_frequency_window_seconds=limits.order_frequency_window_seconds,
            allow_market_orders=limits.allow_market_orders,
            require_reference_price_for_market_order=limits.require_reference_price_for_market_order,
            kill_switch_enabled=limits.kill_switch_enabled,
        )
        requested_source = (
            request.data_source_code.strip().upper()
            if request.data_source_code is not None
            else None
        )
        if (
            self._settings.environment != "test"
            and requested_source is not None
            and requested_source != self._settings.authoritative_market_source
        ):
            raise ApplicationError(
                "REPLAY_MARKET_SOURCE_NOT_ALLOWED",
                "正式环境仅允许使用 MiniQMT 行情",
            )
        selected_source = (
            self._settings.authoritative_market_source
            if self._settings.environment != "test"
            else requested_source or self._settings.historical_market_provider
        )
        execution = BacktestConfiguration(
            strategy_key=request.strategy_key,
            strategy_version=metadata.version,
            parameters=parameters,
            instrument_ids=request.instrument_ids,
            timeframe=MarketTimeframe.DAY_1,
            start_at=request.start_at,
            end_at=request.end_at,
            initial_cash=request.initial_cash,
            order_type=request.order_type,
            time_in_force=request.time_in_force,
            fee_configuration=request.fee_configuration,
            slippage_configuration=request.slippage_configuration,
            maximum_volume_participation=request.maximum_volume_participation,
            risk_configuration_reference=request.risk_configuration_reference,
            risk_configuration_snapshot=risk_snapshot,
            data_source_code=selected_source,
            strategy_price_adjustment_mode=request.strategy_price_adjustment_mode,
        )
        configuration = ReplayConfiguration(execution=execution, speed_mode=request.speed_mode)
        if len(execution.instrument_ids) > self._settings.replay_max_instruments:
            raise ApplicationError(
                "REPLAY_INVALID_CONFIGURATION", "instrument count exceeds replay limit"
            )
        raw_bars, strategy_bars, sessions = await self._load_bars_and_sessions(execution)
        del raw_bars, strategy_bars
        if len(sessions) > self._settings.replay_max_sessions:
            raise ApplicationError(
                "REPLAY_INVALID_CONFIGURATION", "session count exceeds replay limit"
            )
        fingerprint = replay_request_fingerprint(configuration)
        correlation_id = request.correlation_id or uuid4()
        async with self._uow_factory() as uow:
            await uow.replay_runs.lock_idempotency_key(request.idempotency_key)
            existing = await uow.replay_runs.get_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ApplicationError(
                        "REPLAY_IDEMPOTENCY_CONFLICT",
                        "idempotency key was used with another configuration",
                    )
                return ReplayCreateResult(existing, replayed=True)
            run = ReplayRun(
                idempotency_key=request.idempotency_key,
                request_fingerprint=fingerprint,
                configuration=configuration,
                correlation_id=correlation_id,
                total_sessions=len(sessions),
                speed_mode=request.speed_mode,
            )
            await uow.replay_runs.add(run)
            event = await self._append_event_in_uow(
                uow,
                run,
                ReplayEventType.RUN_CREATED,
                execution.start_at,
                "Historical replay created",
                {"total_sessions": len(sessions)},
            )
            await uow.commit()
        await self._publisher.publish(event)

        account = await SimulatedAccountService(self._uow_factory).create(
            account_code=f"RP-{str(run.id)[:12].upper()}",
            name=f"Replay {str(run.id)[:8]}",
            base_currency="CNY",
            initial_cash=execution.initial_cash,
            settlement_policy=SettlementPolicy.IMMEDIATE,
            idempotency_key=f"replay:{run.id}:account",
            correlation_id=correlation_id,
            occurred_at=execution.start_at,
            scope="RT01",
            owner_id=run.id,
        )
        strategy_run = StrategyRun(
            idempotency_key=f"replay:{run.id}:strategy",
            request_fingerprint=run.request_fingerprint,
            strategy_key=execution.strategy_key,
            strategy_version=execution.strategy_version,
            environment=StrategyEnvironment.REPLAY,
            timeframe=execution.timeframe,
            start_at=execution.start_at,
            end_at=execution.end_at,
            parameters=stored_parameters(parameters),
            instrument_ids=execution.instrument_ids,
            status=StrategyRunStatus.CREATED,
            correlation_id=correlation_id,
        )
        async with self._uow_factory() as uow:
            persisted = await uow.replay_runs.get_for_update(run.id)
            if persisted is None:
                raise ApplicationError("REPLAY_NOT_FOUND", "replay was not found")
            record = await uow.strategies.get_by_business_key(execution.strategy_key)
            strategy_run.strategy_id = None if record is None else record.id
            await uow.strategy_runs.add(strategy_run)
            persisted.account_id = account.id
            persisted.strategy_run_id = strategy_run.id
            persisted.transition(ReplayRunStatus.READY, execution.start_at)
            await uow.replay_runs.update(persisted)
            ready_event = await self._append_event_in_uow(
                uow,
                persisted,
                ReplayEventType.RUN_READY,
                execution.start_at,
                "Historical replay is ready",
                {"account_id": str(account.id), "strategy_run_id": str(strategy_run.id)},
            )
            await uow.commit()
        await self._publisher.publish(ready_event)
        return ReplayCreateResult(persisted)

    async def control(self, request: ReplayControlRequest) -> ReplayRun:
        now = request.occurred_at or utc_now()
        fingerprint = replay_action_fingerprint(
            request.replay_run_id,
            request.action_type,
            request.expected_run_version,
            request.requested_speed,
        )
        event: ReplayEvent | None = None
        async with self._uow_factory() as uow:
            run = await uow.replay_runs.get_for_update(request.replay_run_id)
            if run is None:
                raise ApplicationError("REPLAY_NOT_FOUND", "replay was not found")
            existing = await uow.replay_control_actions.get_by_idempotency_key(
                run.id, request.idempotency_key
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise ApplicationError(
                        "REPLAY_IDEMPOTENCY_CONFLICT",
                        "control idempotency key was used with another request",
                    )
                return run
            if run.row_version != request.expected_run_version:
                raise ApplicationError("REPLAY_VERSION_CONFLICT", "replay version is stale")
            if run.status in TERMINAL_REPLAY_STATUSES:
                raise ApplicationError("REPLAY_TERMINAL_STATE", "replay is in a terminal state")
            event_type: ReplayEventType | None = None
            summary = ""
            if request.action_type is ReplayControlActionType.START:
                if run.status is not ReplayRunStatus.READY:
                    raise ApplicationError(
                        "REPLAY_INVALID_TRANSITION", "only READY replay can start"
                    )
                run.transition(ReplayRunStatus.RUNNING, now)
                event_type, summary = ReplayEventType.RUN_STARTED, "Replay started"
                await self._mark_strategy_running(uow, run, now)
            elif request.action_type is ReplayControlActionType.PAUSE:
                if run.status is not ReplayRunStatus.RUNNING:
                    raise ApplicationError("REPLAY_NOT_RUNNING", "replay is not running")
                run.transition(ReplayRunStatus.PAUSED, now)
                run.lease_owner = None
                run.lease_expires_at = None
                event_type, summary = ReplayEventType.RUN_PAUSED, "Replay paused"
            elif request.action_type is ReplayControlActionType.RESUME:
                if run.status is not ReplayRunStatus.PAUSED:
                    raise ApplicationError("REPLAY_NOT_PAUSED", "replay is not paused")
                run.transition(ReplayRunStatus.RUNNING, now)
                event_type, summary = ReplayEventType.RUN_RESUMED, "Replay resumed"
            elif request.action_type is ReplayControlActionType.SET_SPEED:
                if request.requested_speed is None:
                    raise ApplicationError("REPLAY_INVALID_CONFIGURATION", "speed is required")
                run.speed_mode = request.requested_speed
                run.row_version += 1
                run.updated_at = now
                event_type, summary = ReplayEventType.RUN_SPEED_CHANGED, "Replay speed changed"
            elif request.action_type is ReplayControlActionType.STOP:
                run.transition(ReplayRunStatus.STOPPED, now)
                run.lease_owner = None
                run.lease_expires_at = None
                event_type, summary = ReplayEventType.RUN_STOPPED, "Replay stopped"
            elif request.action_type is ReplayControlActionType.STEP:
                if run.status not in {ReplayRunStatus.READY, ReplayRunStatus.PAUSED}:
                    raise ApplicationError(
                        "REPLAY_INVALID_TRANSITION", "STEP requires READY or PAUSED"
                    )
                if run.status is ReplayRunStatus.READY:
                    run.transition(ReplayRunStatus.RUNNING, now)
                    await self._mark_strategy_running(uow, run, now)
                    run.transition(ReplayRunStatus.PAUSED, now)
                else:
                    run.row_version += 1
                    run.updated_at = now
            action = ReplayControlAction(
                replay_run_id=run.id,
                action_type=request.action_type,
                idempotency_key=request.idempotency_key,
                request_fingerprint=fingerprint,
                expected_run_version=request.expected_run_version,
                applied_run_version=run.row_version,
                requested_speed=request.requested_speed,
                actor_type=request.actor_type,
                actor_id=request.actor_id,
                occurred_at=now,
                correlation_id=request.correlation_id or run.correlation_id,
            )
            await uow.replay_control_actions.append(action)
            await uow.replay_runs.update(run)
            if event_type is not None:
                event = await self._append_event_in_uow(
                    uow,
                    run,
                    event_type,
                    self._business_time(run),
                    summary,
                    {
                        "action_id": str(action.id),
                        "speed_mode": run.speed_mode.value,
                        "run_version": run.row_version,
                    },
                )
            await uow.commit()
        if event is not None:
            await self._publisher.publish(event)
        if request.action_type is ReplayControlActionType.STEP:
            await ReplaySessionProcessor(
                self._uow_factory, self._registry, self._settings, self._publisher
            ).process_next_session(request.replay_run_id, allow_paused=True)
            async with self._uow_factory() as uow:
                refreshed = await uow.replay_runs.get_by_id(request.replay_run_id)
            if refreshed is None:
                raise ApplicationError("REPLAY_NOT_FOUND", "replay was not found")
            return refreshed
        return run

    async def _load_bars_and_sessions(
        self, configuration: BacktestConfiguration
    ) -> tuple[list[StrategyBar], list[StrategyBar], list[BacktestSession]]:
        async with self._uow_factory() as uow:
            readiness = await uow.historical_bars.readiness(
                instrument_ids=configuration.instrument_ids,
                timeframe=configuration.timeframe,
                start_at=configuration.start_at,
                end_at=configuration.end_at,
                source_code=configuration.data_source_code,
                adjustment_type=AdjustmentType.NONE,
                accepted_quality_statuses=(MarketDataQualityStatus.NORMAL,),
                minimum_bars_per_instrument=1,
            )
            if readiness.status not in {
                MarketDataReadinessStatus.READY,
                MarketDataReadinessStatus.PARTIAL,
            }:
                raise ApplicationError(
                    "REPLAY_DATA_NOT_READY", "local historical daily data is not ready"
                )
            bars = await uow.historical_bars.list_authoritative_bars(
                instrument_ids=configuration.instrument_ids,
                timeframe=configuration.timeframe,
                start_at=configuration.start_at,
                end_at=configuration.end_at,
                source_code=configuration.data_source_code,
                adjustment_type=AdjustmentType.NONE,
                accepted_quality_statuses=(MarketDataQualityStatus.NORMAL,),
            )
            strategy_bars = await uow.historical_bars.list_authoritative_bars(
                instrument_ids=configuration.instrument_ids,
                timeframe=configuration.timeframe,
                start_at=configuration.start_at,
                end_at=configuration.end_at,
                source_code=configuration.data_source_code,
                adjustment_type=AdjustmentType.NONE,
                accepted_quality_statuses=(MarketDataQualityStatus.NORMAL,),
                price_adjustment_mode=configuration.strategy_price_adjustment_mode,
            )
            calendar_rows = await uow.trading_calendar.list(
                exchange=None,
                start=configuration.start_at.date(),
                end=configuration.end_at.date(),
                limit=self._settings.replay_max_sessions * 2 + 100,
            )
        if not bars or set(configuration.instrument_ids) - {item.instrument_id for item in bars}:
            raise ApplicationError(
                "REPLAY_DATA_NOT_READY", "one or more instruments have no local daily bars"
            )
        grouped: dict[date, set[UUID]] = defaultdict(set)
        for bar in bars:
            grouped[_bar_date(bar)].add(bar.instrument_id)
        calendar_dates = {item.session_date for item in calendar_rows if item.is_open}
        session_dates = sorted(grouped)
        if calendar_dates:
            session_dates = [item for item in session_dates if item in calendar_dates]
        sessions = [
            BacktestSession(trading_date=trading_date, instrument_ids=tuple(instruments))
            for trading_date in session_dates
            for instruments in (grouped[trading_date],)
        ]
        HistoricalSessionProcessor(sessions)
        return bars, strategy_bars, sessions

    @staticmethod
    async def _mark_strategy_running(uow: Any, run: ReplayRun, occurred_at: datetime) -> None:
        if run.strategy_run_id is None:
            return
        strategy_run = await uow.strategy_runs.get_by_id(run.strategy_run_id)
        if strategy_run is not None and strategy_run.status is StrategyRunStatus.CREATED:
            strategy_run.mark_running(occurred_at)
            await uow.strategy_runs.update(strategy_run)

    @staticmethod
    def _business_time(run: ReplayRun) -> datetime:
        if run.current_session_date is None:
            return run.configuration.execution.start_at
        return BacktestSession(
            trading_date=run.current_session_date,
            instrument_ids=run.configuration.execution.instrument_ids,
        ).time_for(BacktestPhase.SESSION_END)

    @staticmethod
    async def _append_event_in_uow(
        uow: Any,
        run: ReplayRun,
        event_type: ReplayEventType,
        business_time: datetime,
        summary: str,
        payload: Mapping[str, Any],
        *,
        instrument_id: UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: UUID | None = None,
    ) -> ReplayEvent:
        event = ReplayEvent(
            replay_run_id=run.id,
            sequence_number=await uow.replay_events.next_sequence(run.id),
            event_type=event_type,
            business_time=business_time,
            occurred_at=utc_now(),
            summary=summary,
            payload=dict(payload),
            instrument_id=instrument_id,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            correlation_id=run.correlation_id,
        )
        await uow.replay_events.append(event)
        return event


class ReplaySessionProcessor:
    """Advance one complete OPEN/CLOSE/END session using existing trading services."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        registry: StrategyRegistry,
        settings: Settings,
        publisher: ReplayEventPublisher | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry
        self._settings = settings
        self._publisher = publisher or ReplayEventPublisher()

    async def process_next_session(
        self, replay_run_id: UUID, *, allow_paused: bool = False
    ) -> ReplaySessionResult:
        async with self._uow_factory() as uow:
            run = await uow.replay_runs.get_for_update(replay_run_id)
            if run is None:
                raise ApplicationError("REPLAY_NOT_FOUND", "replay was not found")
            allowed = {ReplayRunStatus.RUNNING}
            if allow_paused:
                allowed |= {ReplayRunStatus.READY, ReplayRunStatus.PAUSED}
            if run.status not in allowed:
                raise ApplicationError("REPLAY_NOT_RUNNING", "replay cannot advance now")
            if run.current_session_index >= run.total_sessions:
                raise ApplicationError("REPLAY_INVALID_TRANSITION", "replay is complete")
            cursor = run.current_session_index
        config = run.configuration.execution
        parameters = StrategyResearchService(self._uow_factory, self._registry).parameters(
            config.strategy_key,
            cast(dict[str, str | int | bool], dict(config.parameters)),
        )
        bars, strategy_bars, sessions = await ReplayService(
            self._uow_factory, self._registry, self._settings
        )._load_bars_and_sessions(config)
        cursor_result = HistoricalSessionProcessor(sessions, cursor).process_next_session()
        session = cursor_result.session
        bars_by_date: dict[date, dict[UUID, StrategyBar]] = defaultdict(dict)
        for bar in bars:
            bars_by_date[_bar_date(bar)][bar.instrument_id] = bar
        day_bars = bars_by_date[session.trading_date]
        strategy_bars_by_date: dict[date, dict[UUID, StrategyBar]] = defaultdict(dict)
        for bar in strategy_bars:
            strategy_bars_by_date[_bar_date(bar)][bar.instrument_id] = bar
        strategy_day_bars = strategy_bars_by_date[session.trading_date]
        open_time = session.time_for(BacktestPhase.SESSION_OPEN)
        close_time = session.time_for(BacktestPhase.SESSION_CLOSE)
        end_time = session.time_for(BacktestPhase.SESSION_END)
        events: list[ReplayEvent] = []
        events.append(
            await self._event(
                run,
                ReplayEventType.SESSION_STARTED,
                open_time,
                f"Session {session.trading_date} started",
                {"session_index": cursor},
            )
        )

        execution = SimulatedBrokerExecutionService(
            self._uow_factory,
            adapter=SimulatedBrokerAdapter(
                fee_model=config.fee_configuration,
                slippage_model=config.slippage_configuration,
            ),
        )
        fills_count = 0
        async with self._uow_factory() as uow:
            orders = (
                []
                if run.account_id is None
                else await uow.orders.list_all_by_account(run.account_id)
            )
        executable_statuses = {
            OrderStatus.QUEUED,
            OrderStatus.BROKER_ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
        }
        for instrument_id in sorted(day_bars, key=str):
            bar = day_bars[instrument_id]
            async with self._uow_factory() as uow:
                instrument = await uow.instruments.get_by_id(instrument_id)
                statuses = await uow.instrument_trading_statuses.list(
                    instrument_ids=[instrument_id],
                    start=session.trading_date,
                    end=session.trading_date,
                    limit=10,
                )
            if instrument is None:
                raise ApplicationError("INSTRUMENT_NOT_FOUND", "instrument was not found")
            candidates = [
                order
                for order in orders
                if order.instrument_id == instrument_id
                and order.status in executable_statuses
                and order.created_at < open_time
            ]
            if any(item.status is InstrumentTradingState.SUSPENDED for item in statuses):
                events.append(
                    await self._event(
                        run,
                        ReplayEventType.WARNING,
                        open_time,
                        f"Instrument {instrument_id} suspended; execution deferred",
                        {"instrument_id": str(instrument_id)},
                        instrument_id=instrument_id,
                    )
                )
                continue
            for order in sorted(candidates, key=lambda item: (item.created_at, str(item.id))):
                result = await execution.execute_market_input(
                    SimulatedExecutionMarketInput(
                        order_id=order.id,
                        idempotency_key=(
                            f"replay:{run.id}:execute:{order.id}:{session.trading_date}"
                        ),
                        correlation_id=run.correlation_id,
                        timestamp=open_time,
                        trading_status=TradingStatus.TRADING,
                        source="REPLAY_DAILY_BAR",
                        is_stale=False,
                        open=bar.open,
                        high=bar.open,
                        low=bar.open,
                        close=bar.open,
                        last_price=bar.open,
                        bid_price=bar.open,
                        ask_price=bar.open,
                        available_volume=_available_volume(
                            bar, config.maximum_volume_participation, instrument.lot_size
                        ),
                    )
                )
                fills_count += len(result.fills)
                events.append(
                    await self._event(
                        run,
                        ReplayEventType.EXECUTION_COMPLETED,
                        open_time,
                        f"Order {order.id} execution completed",
                        {
                            "order_id": str(order.id),
                            "attempt_id": str(result.attempt.id),
                            "fill_count": len(result.fills),
                        },
                        related_entity_type="ORDER",
                        related_entity_id=order.id,
                    )
                )
                for fill in result.fills:
                    events.append(
                        await self._event(
                            run,
                            ReplayEventType.FILL_CREATED,
                            open_time,
                            f"Fill {fill.id} created",
                            {
                                "fill_id": str(fill.id),
                                "order_id": str(order.id),
                                "quantity": str(fill.quantity),
                                "price": str(fill.price),
                            },
                            instrument_id=instrument_id,
                            related_entity_type="FILL",
                            related_entity_id=fill.id,
                        )
                    )
                if config.time_in_force is TimeInForce.DAY and result.order.status not in (
                    OrderStateMachine.terminal_states
                ):
                    await self._end_day_order(result.order.id, end_time, run)
        events.append(
            await self._event(
                run,
                ReplayEventType.OPEN_PHASE_COMPLETED,
                open_time,
                "Open phase completed",
                {"fills_generated": fills_count},
            )
        )

        latest_close = {
            item.instrument_id: item.close
            for item in bars
            if _bar_date(item) <= session.trading_date
        }
        if run.account_id is None or run.strategy_run_id is None:
            raise ApplicationError("REPLAY_SESSION_FAILED", "replay account is missing")
        await self._valuation(
            run.account_id, close_time, latest_close, day_bars, run.correlation_id
        )
        signals_count = 0
        orders_count = 0
        strategy = self._registry.create_instance(config.strategy_key, parameters)
        context = StrategyContext(
            strategy_key=config.strategy_key,
            strategy_version=config.strategy_version,
            run_id=run.strategy_run_id,
            current_time=config.start_at,
            parameters=parameters,
            environment=StrategyEnvironment.REPLAY,
        )
        strategy.initialize(context)
        ordered_bars = sorted(
            strategy_bars, key=lambda item: (_bar_date(item), str(item.instrument_id))
        )
        prior_bars = [item for item in ordered_bars if _bar_date(item) < session.trading_date]
        for prior in prior_bars:
            prior_time = BacktestSession(
                trading_date=_bar_date(prior), instrument_ids=(prior.instrument_id,)
            ).time_for(BacktestPhase.SESSION_CLOSE)
            context.advance_time(prior_time)
            tuple(strategy.on_bar(context, prior))
        context.advance_time(close_time)
        async with self._uow_factory() as uow:
            existing_signals = await uow.signals.list_all_by_run(run.strategy_run_id)
        sequence = len(existing_signals)
        next_dates = _next_dates(bars)
        captured = config.risk_configuration_snapshot
        if captured is None:
            raise ApplicationError("REPLAY_INVALID_CONFIGURATION", "risk snapshot is missing")
        limits = _CapturedRiskLimitsProvider(captured)
        risk_orders = RiskGatedOrderService(self._uow_factory, limits)
        signal_risk = SignalRiskAssessmentService(self._uow_factory, limits)
        confirmation = OrderConfirmationService(self._uow_factory)
        for instrument_id in sorted(day_bars, key=str):
            bar = day_bars[instrument_id]
            strategy_bar = strategy_day_bars[instrument_id]
            for draft in strategy.on_bar(context, strategy_bar):
                validate_signal_draft(
                    draft,
                    run=StrategyRun(
                        id=run.strategy_run_id,
                        idempotency_key=f"replay:{run.id}:strategy",
                        request_fingerprint=run.request_fingerprint,
                        strategy_key=config.strategy_key,
                        strategy_version=config.strategy_version,
                        environment=StrategyEnvironment.REPLAY,
                        timeframe=config.timeframe,
                        start_at=config.start_at,
                        end_at=config.end_at,
                        parameters=stored_parameters(parameters),
                        instrument_ids=config.instrument_ids,
                        status=StrategyRunStatus.RUNNING,
                        correlation_id=run.correlation_id,
                    ),
                    current_bar_instrument_id=strategy_bar.instrument_id,
                    current_bar_timestamp=strategy_bar.timestamp,
                    expected_generated_at=close_time,
                )
                sequence += 1
                async with self._uow_factory() as uow:
                    persisted_run = await uow.strategy_runs.get_by_id(run.strategy_run_id)
                if persisted_run is None:
                    raise ApplicationError("REPLAY_SESSION_FAILED", "strategy run is missing")
                signal = persisted_signal_from_draft(
                    persisted_run, draft, sequence, account_id=run.account_id
                )
                signal.valid_until = config.end_at
                async with self._uow_factory() as uow:
                    await uow.signals.add(signal)
                    await uow.commit()
                signals_count += 1
                events.append(
                    await self._event(
                        run,
                        ReplayEventType.SIGNAL_GENERATED,
                        close_time,
                        f"Signal {signal.id} generated",
                        {"signal_id": str(signal.id), "side": signal.side.value},
                        instrument_id=instrument_id,
                        related_entity_type="SIGNAL",
                        related_entity_id=signal.id,
                    )
                )
                outcome, created_order, decision_id = await self._signal_to_order(
                    run,
                    signal,
                    bar,
                    close_time,
                    next_dates.get((instrument_id, session.trading_date)),
                    risk_orders,
                    signal_risk,
                    confirmation,
                )
                events.append(
                    await self._event(
                        run,
                        ReplayEventType.RISK_EVALUATED,
                        close_time,
                        f"Risk decision {outcome.value}",
                        {
                            "signal_id": str(signal.id),
                            "risk_decision_id": str(decision_id),
                            "decision": outcome.value,
                        },
                        instrument_id=instrument_id,
                        related_entity_type="RISK_DECISION",
                        related_entity_id=decision_id,
                    )
                )
                if created_order is not None:
                    orders_count += 1
                    events.append(
                        await self._event(
                            run,
                            ReplayEventType.ORDER_CREATED,
                            close_time,
                            f"Order {created_order.id} created",
                            {
                                "order_id": str(created_order.id),
                                "signal_id": str(signal.id),
                            },
                            instrument_id=instrument_id,
                            related_entity_type="ORDER",
                            related_entity_id=created_order.id,
                        )
                    )
                    events.append(
                        await self._event(
                            run,
                            ReplayEventType.ORDER_CONFIRMED,
                            close_time,
                            f"Order {created_order.id} internally confirmed",
                            {
                                "order_id": str(created_order.id),
                                "actor_id": "REPLAY_ENGINE",
                            },
                            instrument_id=instrument_id,
                            related_entity_type="ORDER",
                            related_entity_id=created_order.id,
                        )
                    )
                    if config.time_in_force is TimeInForce.DAY and (
                        next_dates.get((instrument_id, session.trading_date)) is None
                    ):
                        await self._end_day_order(created_order.id, end_time, run)

        strategy.finalize(context)
        snapshot = await self._valuation(
            run.account_id, end_time, latest_close, day_bars, run.correlation_id
        )
        async with self._uow_factory() as uow:
            previous = await uow.replay_equity_points.list_by_run(run.id)
            points = build_equity_points(
                run_id=run.id,
                initial_equity=config.initial_cash,
                snapshots=[
                    (
                        item.timestamp,
                        item.cash,
                        item.market_value,
                        item.gross_exposure,
                        item.net_exposure,
                        item.positions_count,
                        item.warnings,
                    )
                    for item in previous
                ]
                + [snapshot],
            )
            point = points[-1]
            await uow.replay_equity_points.append(point)
            locked = await uow.replay_runs.get_for_update(run.id)
            if locked is None or locked.current_session_index != cursor:
                raise ApplicationError("REPLAY_VERSION_CONFLICT", "replay cursor changed")
            locked.current_session_date = session.trading_date
            locked.current_session_index = cursor_result.next_session_index
            locked.bars_processed += len(day_bars)
            locked.signals_generated += signals_count
            locked.orders_created += orders_count
            locked.fills_generated += fills_count
            locked.row_version += 1
            locked.updated_at = utc_now()
            completed = cursor_result.completed
            if completed:
                completion_wall_time = utc_now()
                if locked.status in {ReplayRunStatus.READY, ReplayRunStatus.PAUSED}:
                    locked.transition(ReplayRunStatus.RUNNING, completion_wall_time)
                locked.transition(ReplayRunStatus.COMPLETED, completion_wall_time)
                locked.lease_owner = None
                locked.lease_expires_at = None
            await uow.replay_runs.update(locked)
            await uow.commit()
        events.append(
            await self._event(
                locked,
                ReplayEventType.EQUITY_UPDATED,
                end_time,
                "Replay equity updated",
                {
                    "cash": str(point.cash),
                    "market_value": str(point.market_value),
                    "total_equity": str(point.total_equity),
                    "drawdown": str(point.drawdown),
                },
            )
        )
        events.append(
            await self._event(
                locked,
                ReplayEventType.SESSION_COMPLETED,
                end_time,
                f"Session {session.trading_date} completed",
                {"session_index": cursor, "next_session_index": cursor_result.next_session_index},
            )
        )
        if cursor_result.completed:
            await self._finalize(locked, end_time)
            events.append(
                await self._event(
                    locked,
                    ReplayEventType.RUN_COMPLETED,
                    end_time,
                    "Historical replay completed",
                    {"final_equity": str(point.total_equity)},
                )
            )
        for event in events:
            await self._publisher.publish(event)
        return ReplaySessionResult(
            replay_run_id=run.id,
            session_index=cursor,
            session_date=session.trading_date,
            bars_processed=len(day_bars),
            signals_generated=signals_count,
            orders_created=orders_count,
            fills_generated=fills_count,
            total_equity=str(point.total_equity),
            completed=cursor_result.completed,
        )

    async def _signal_to_order(
        self,
        run: ReplayRun,
        signal: Signal,
        bar: StrategyBar,
        occurred_at: datetime,
        next_trading_date: date | None,
        risk_orders: RiskGatedOrderService,
        signal_risk: SignalRiskAssessmentService,
        confirmation: OrderConfirmationService,
    ) -> tuple[RiskDecisionType, Order | None, UUID]:
        assert run.account_id is not None
        config = run.configuration.execution
        key = f"replay:{run.id}:signal:{signal.id}"
        if signal.target_quantity is None:
            outcome = await signal_risk.assess(
                signal.id,
                run.account_id,
                f"{key}:risk",
                run.correlation_id,
                reference_price=signal.reference_price,
            )
            return outcome.decision.overall_decision, None, outcome.decision.id
        expiry_date = next_trading_date or _bar_date(bar)
        expires_at = BacktestSession(
            trading_date=expiry_date, instrument_ids=(signal.instrument_id,)
        ).time_for(BacktestPhase.SESSION_END)
        if config.time_in_force is not TimeInForce.DAY:
            expires_at = config.end_at
        outcome = await risk_orders.create(
            CreateM05OrderRequest(
                account_id=run.account_id,
                instrument_id=signal.instrument_id,
                side=signal.side.value,
                order_type=config.order_type.value,
                time_in_force=config.time_in_force.value,
                quantity=signal.target_quantity,
                limit_price=(
                    (bar.raw_reference_price or bar.close)
                    if config.order_type is OrderType.LIMIT
                    else None
                ),
                expires_at=expires_at,
                idempotency_key=f"{key}:risk-order",
                correlation_id=run.correlation_id,
                actor_id="REPLAY_ENGINE",
                actor_type=OrderActorType.SYSTEM,
                occurred_at=occurred_at,
                intent_source=OrderIntentSource.STRATEGY,
                source_id=signal.id,
                strategy_key=config.strategy_key,
                reference_price=bar.raw_reference_price or bar.close,
            )
        )
        order = outcome.order
        if order is None:
            return outcome.decision.overall_decision, None, outcome.decision.id
        confirmed = await confirmation.confirm(
            ConfirmOrderRequest(
                order_id=order.id,
                idempotency_key=f"{key}:confirm",
                expected_order_version=order.row_version,
                correlation_id=run.correlation_id,
                note="RT01 internal auto-confirmation",
                actor_type=OrderActorType.SYSTEM,
                actor_id="REPLAY_ENGINE",
                occurred_at=occurred_at,
                suppress_outbox_reason=REPLAY_SUPPRESSION_REASON,
            )
        )
        return outcome.decision.overall_decision, confirmed, outcome.decision.id

    async def _valuation(
        self,
        account_id: UUID,
        occurred_at: datetime,
        prices: Mapping[UUID, Decimal],
        day_bars: Mapping[UUID, StrategyBar],
        correlation_id: UUID,
    ) -> tuple[datetime, Decimal, Decimal, Decimal, Decimal, int, tuple[str, ...]]:
        async with self._uow_factory() as uow:
            positions = await uow.positions.list_for_account(account_id)
        held = {item.instrument_id for item in positions if item.total_quantity > ZERO}
        stale = held - set(day_bars)
        result = await KnownPriceAccountValuationService(self._uow_factory).value(
            account_id=account_id,
            prices=dict(prices),
            stale_instrument_ids=stale,
            as_of=occurred_at,
            correlation_id=correlation_id,
        )
        snapshot = result.snapshot
        if snapshot.positions_market_value is None or snapshot.total_equity is None:
            raise ApplicationError("REPLAY_SESSION_FAILED", "account valuation is unavailable")
        return (
            occurred_at,
            snapshot.cash_total,
            snapshot.positions_market_value,
            snapshot.positions_market_value,
            snapshot.positions_market_value,
            len(held),
            tuple(f"STALE_VALUATION:{item}" for item in sorted(stale, key=str)),
        )

    async def _end_day_order(self, order_id: UUID, occurred_at: datetime, run: ReplayRun) -> None:
        async with self._uow_factory() as uow:
            order = await uow.orders.get_for_update(order_id)
            if order is None or order.status in OrderStateMachine.terminal_states:
                return
            path = (
                (OrderStatus.EXPIRED,)
                if order.status is OrderStatus.QUEUED
                else (OrderStatus.CANCEL_PENDING, OrderStatus.CANCELLED)
            )
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
                        actor_id="REPLAY_ENGINE",
                        reason_code="REPLAY_DAY_ORDER_ENDED",
                        correlation_id=run.correlation_id,
                        occurred_at=occurred_at,
                        order_version=order.row_version,
                    )
                )
            await uow.commit()

    async def _event(
        self,
        run: ReplayRun,
        event_type: ReplayEventType,
        business_time: datetime,
        summary: str,
        payload: Mapping[str, Any],
        *,
        instrument_id: UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: UUID | None = None,
    ) -> ReplayEvent:
        async with self._uow_factory() as uow:
            event = await ReplayService._append_event_in_uow(
                uow,
                run,
                event_type,
                business_time,
                summary,
                payload,
                instrument_id=instrument_id,
                related_entity_type=related_entity_type,
                related_entity_id=related_entity_id,
            )
            await uow.commit()
        return event

    async def _finalize(self, run: ReplayRun, occurred_at: datetime) -> None:
        query = ReplayQueryService(self._uow_factory)
        points = await query.equity(run.id)
        fills = await query.fills(run.id)
        orders = await query.orders(run.id)
        orders_by_id = {item.id: item for item in orders}
        fill_inputs: builtins.list[BacktestFillMetricInput] = []
        trades: builtins.list[BacktestTradeSummary] = []
        quantities: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
        cost_basis: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
        opened_at: dict[UUID, datetime] = {}
        for item in sorted(fills, key=lambda fill: (fill.executed_at, str(fill.id))):
            fees = _fill_fees(item)
            order = orders_by_id[item.order_id]
            side = order.side
            total_fee = sum(fees, ZERO)
            fill_inputs.append(
                BacktestFillMetricInput(
                    side=side,
                    quantity=item.quantity,
                    price=item.price,
                    commission=fees[0],
                    stamp_duty=fees[1],
                    transfer_fee=fees[2],
                    other_fee=fees[3],
                )
            )
            instrument_id = order.instrument_id
            if side is OrderSide.BUY:
                if quantities[instrument_id] == ZERO:
                    opened_at[instrument_id] = item.executed_at
                quantities[instrument_id] += item.quantity
                cost_basis[instrument_id] += item.gross_amount + total_fee
                continue
            average_cost = cost_basis[instrument_id] / quantities[instrument_id]
            removed_cost = average_cost * item.quantity
            net_proceeds = item.gross_amount - total_fee
            realized = net_proceeds - removed_cost
            trades.append(
                BacktestTradeSummary(
                    run_id=run.id,
                    instrument_id=instrument_id,
                    opened_at=opened_at[instrument_id],
                    closed_at=item.executed_at,
                    quantity=item.quantity,
                    entry_price=average_cost,
                    exit_price=item.price,
                    gross_pnl=realized + total_fee,
                    fees=total_fee,
                    net_pnl=realized,
                )
            )
            quantities[instrument_id] -= item.quantity
            cost_basis[instrument_id] -= removed_cost
            if quantities[instrument_id] == ZERO:
                cost_basis[instrument_id] = ZERO
                opened_at.pop(instrument_id, None)
        metrics = BacktestPerformanceService().calculate(
            run_id=run.id, equity_points=points, fills=fill_inputs, trades=trades
        )
        serialized_metrics = _json(asdict(metrics))
        if not isinstance(serialized_metrics, dict):
            raise ApplicationError("REPLAY_SESSION_FAILED", "metrics serialization failed")
        summary = serialized_metrics
        integrity = await ReplayIntegrityService(self._uow_factory).verify(run.id)
        async with self._uow_factory() as uow:
            locked = await uow.replay_runs.get_for_update(run.id)
            if locked is None:
                raise ApplicationError("REPLAY_NOT_FOUND", "replay was not found")
            locked.final_summary = summary
            locked.integrity_summary = {
                "ok": integrity.ok,
                "checked_at": integrity.checked_at.isoformat(),
                "issues": list(integrity.issues),
            }
            await uow.replay_runs.update(locked)
            if locked.strategy_run_id is not None:
                strategy_run = await uow.strategy_runs.get_by_id(locked.strategy_run_id)
                if strategy_run is not None and strategy_run.status is StrategyRunStatus.RUNNING:
                    strategy_run.mark_completed(
                        occurred_at, locked.bars_processed, locked.signals_generated
                    )
                    await uow.strategy_runs.update(strategy_run)
            await uow.commit()


class ReplayQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def list(self, *, page: int, page_size: int, status: str | None) -> ReplayPageResult:
        async with self._uow_factory() as uow:
            runs, total = await uow.replay_runs.list(
                status=status, offset=(page - 1) * page_size, limit=page_size
            )
        return {
            "items": [self.run_view(item) for item in runs],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    async def detail(self, replay_run_id: UUID) -> dict[str, object]:
        run = await self.require(replay_run_id)
        result = self.run_view(run)
        result["configuration"] = replay_configuration_to_dict(run.configuration)
        result["final_summary"] = dict(run.final_summary)
        result["integrity_summary"] = dict(run.integrity_summary)
        return result

    async def state(self, replay_run_id: UUID) -> dict[str, object]:
        run = await self.require(replay_run_id)
        current_bars: builtins.list[StrategyBar] = []
        async with self._uow_factory() as uow:
            cash = (
                None
                if run.account_id is None
                else await uow.cash_balances.get(run.account_id, "CNY")
            )
            positions = (
                []
                if run.account_id is None
                else await uow.positions.list_for_account(run.account_id)
            )
            equity_points = await uow.replay_equity_points.list_by_run(run.id)
            latest_equity = equity_points[-1] if equity_points else None
            if run.current_session_date is not None:
                config = run.configuration.execution
                all_bars = await uow.historical_bars.list_authoritative_bars(
                    instrument_ids=config.instrument_ids,
                    timeframe=config.timeframe,
                    start_at=config.start_at,
                    end_at=config.end_at,
                    source_code=config.data_source_code,
                    adjustment_type=AdjustmentType.NONE,
                    accepted_quality_statuses=(MarketDataQualityStatus.NORMAL,),
                )
                current_bars = [
                    item for item in all_bars if _bar_date(item) == run.current_session_date
                ]
        ordered_current_bars = sorted(current_bars, key=lambda item: str(item.instrument_id))
        return {
            **self.run_view(run),
            "cash": None if cash is None else _json(asdict(cash)),
            "positions": [_json(asdict(item)) for item in positions],
            "latest_equity": (None if latest_equity is None else _json(asdict(latest_equity))),
            "current_bar": (
                None if not ordered_current_bars else _json(asdict(ordered_current_bars[0]))
            ),
            "current_bars": [_json(asdict(item)) for item in ordered_current_bars],
        }

    async def events(
        self,
        replay_run_id: UUID,
        *,
        after_sequence: int,
        event_type: str | None,
        instrument_id: UUID | None,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        await self.require(replay_run_id)
        async with self._uow_factory() as uow:
            items, total = await uow.replay_events.list_by_run(
                replay_run_id,
                after_sequence=after_sequence,
                event_type=event_type,
                instrument_id=instrument_id,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        return {
            "items": [_json(asdict(item)) for item in items],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    async def equity(self, replay_run_id: UUID) -> builtins.list[BacktestEquityPoint]:
        await self.require(replay_run_id)
        async with self._uow_factory() as uow:
            return await uow.replay_equity_points.list_by_run(replay_run_id)

    async def signals(self, replay_run_id: UUID) -> builtins.list[Signal]:
        run = await self.require(replay_run_id)
        if run.strategy_run_id is None:
            return []
        async with self._uow_factory() as uow:
            return await uow.signals.list_all_by_run(run.strategy_run_id)

    async def risk_decisions(self, replay_run_id: UUID) -> builtins.list[RiskDecision]:
        run = await self.require(replay_run_id)
        if run.account_id is None:
            return []
        async with self._uow_factory() as uow:
            decisions, _ = await uow.risk_decisions.list(
                offset=0, limit=100_000, account_id=run.account_id
            )
        return decisions

    async def orders(self, replay_run_id: UUID) -> builtins.list[Order]:
        run = await self.require(replay_run_id)
        if run.account_id is None:
            return []
        async with self._uow_factory() as uow:
            orders, _ = await uow.orders.list(offset=0, limit=100_000, account_id=run.account_id)
        return orders

    async def fills(self, replay_run_id: UUID) -> builtins.list[Fill]:
        run = await self.require(replay_run_id)
        if run.account_id is None:
            return []
        async with self._uow_factory() as uow:
            fills, _ = await uow.fills.list(offset=0, limit=100_000, account_id=run.account_id)
        return fills

    async def require(self, replay_run_id: UUID) -> ReplayRun:
        async with self._uow_factory() as uow:
            run = await uow.replay_runs.get_by_id(replay_run_id)
        if run is None:
            raise ApplicationError("REPLAY_NOT_FOUND", "replay was not found")
        return run

    @staticmethod
    def run_view(run: ReplayRun) -> dict[str, object]:
        return {
            "id": run.id,
            "idempotency_key": run.idempotency_key,
            "status": run.status.value,
            "row_version": run.row_version,
            "strategy_key": run.configuration.execution.strategy_key,
            "strategy_version": run.configuration.execution.strategy_version,
            "account_id": run.account_id,
            "strategy_run_id": run.strategy_run_id,
            "current_session_date": run.current_session_date,
            "current_session_index": run.current_session_index,
            "total_sessions": run.total_sessions,
            "speed_mode": run.speed_mode.value,
            "bars_processed": run.bars_processed,
            "signals_generated": run.signals_generated,
            "orders_created": run.orders_created,
            "fills_generated": run.fills_generated,
            "started_at": run.started_at,
            "paused_at": run.paused_at,
            "completed_at": run.completed_at,
            "stopped_at": run.stopped_at,
            "failed_at": run.failed_at,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "last_heartbeat_at": run.last_heartbeat_at,
            "worker_online": (
                run.last_heartbeat_at is not None
                and utc_now() - run.last_heartbeat_at < timedelta(seconds=30)
            ),
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }


class ReplayIntegrityService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def verify(self, replay_run_id: UUID) -> ReplayIntegrityReport:
        query = ReplayQueryService(self._uow_factory)
        run = await query.require(replay_run_id)
        signals = await query.signals(replay_run_id)
        orders = await query.orders(replay_run_id)
        fills = await query.fills(replay_run_id)
        points = await query.equity(replay_run_id)
        async with self._uow_factory() as uow:
            events, _ = await uow.replay_events.list_by_run(replay_run_id, limit=1_000_000)
            account = (
                None if run.account_id is None else await uow.accounts.get_by_id(run.account_id)
            )
        issues: list[str] = []
        if [item.sequence_number for item in events] != list(range(1, len(events) + 1)):
            issues.append("REPLAY_EVENT_SEQUENCE_GAP")
        if run.current_session_index != len(points):
            issues.append("REPLAY_SESSION_EQUITY_COUNT_MISMATCH")
        if run.signals_generated != len(signals):
            issues.append("REPLAY_SIGNAL_COUNT_MISMATCH")
        if run.orders_created != len(orders):
            issues.append("REPLAY_ORDER_COUNT_MISMATCH")
        if run.fills_generated != len(fills):
            issues.append("REPLAY_FILL_COUNT_MISMATCH")
        if account is None or account.metadata.get("scope") != "RT01":
            issues.append("REPLAY_ACCOUNT_SCOPE_MISMATCH")
        return ReplayIntegrityReport(
            replay_run_id=replay_run_id,
            ok=not issues,
            checked_at=utc_now(),
            issues=tuple(issues),
            facts={
                "sessions": run.current_session_index,
                "events": len(events),
                "signals": len(signals),
                "orders": len(orders),
                "fills": len(fills),
            },
        )


def replay_interval_seconds(settings: Settings, speed: ReplaySpeedMode) -> float | None:
    if speed is ReplaySpeedMode.MANUAL:
        return None
    milliseconds = {
        ReplaySpeedMode.X1: settings.replay_interval_x1_ms,
        ReplaySpeedMode.X10: settings.replay_interval_x10_ms,
        ReplaySpeedMode.X100: settings.replay_interval_x100_ms,
    }[speed]
    return milliseconds / 1000
