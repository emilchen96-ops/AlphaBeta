"""R01-B application pipeline: authoritative snapshots, persisted decisions and order gate."""

from __future__ import annotations

import builtins
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.order_contracts import payload_hash
from alphadesk_api.application.orders import CreateOrderRequest, OrderIntentService
from alphadesk_api.core.config import Settings
from alphadesk_domain.entities import AuditLog, DomainEvent, Order, RiskDecision, RiskRuleEvaluation
from alphadesk_domain.enums import OrderSide, OrderType, RiskDecisionType
from alphadesk_domain.risk import (
    RiskAccountSnapshot,
    RiskEvaluationResult,
    RiskInstrumentSnapshot,
    RiskLimits,
    RiskPositionSnapshot,
    RiskRequest,
    RiskRequestSource,
    RiskRuleResult,
    RiskSeverity,
    RuleBasedRiskEvaluator,
)
from alphadesk_domain.unit_of_work import UnitOfWork


def _json(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    return value


class RiskLimitsProvider(Protocol):
    def get_limits(self, account_id: UUID) -> RiskLimits: ...
    @property
    def version_marker(self) -> str: ...


class ConfiguredRiskLimitsProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def version_marker(self) -> str:
        return "r01-config-v1"

    def get_limits(self, account_id: UUID) -> RiskLimits:
        del account_id
        return RiskLimits(
            max_order_notional=self._settings.risk_max_order_notional,
            max_instrument_weight=self._settings.risk_max_instrument_weight,
            max_total_exposure=self._settings.risk_max_total_exposure,
            max_orders_per_window=self._settings.risk_max_orders_per_window,
            order_frequency_window_seconds=self._settings.risk_order_frequency_window_seconds,
            allow_market_orders=self._settings.risk_allow_market_orders,
            require_reference_price_for_market_order=(
                self._settings.risk_require_reference_price_for_market_order
            ),
            kill_switch_enabled=self._settings.risk_kill_switch_enabled,
        )


@dataclass(frozen=True, slots=True)
class RiskSnapshots:
    account: RiskAccountSnapshot | None
    instrument: RiskInstrumentSnapshot
    account_payload: dict[str, object]
    instrument_payload: dict[str, object]
    review_reason: str | None = None


class RiskSnapshotService:
    """Build values exclusively from authoritative PostgreSQL account facts."""

    async def build(
        self, uow: UnitOfWork, request: RiskRequest, limits: RiskLimits
    ) -> RiskSnapshots:
        account = await uow.accounts.get_by_id(request.account_id)
        if account is None:
            raise ApplicationError("RISK_ACCOUNT_NOT_FOUND", "trading account was not found")
        instrument = await uow.instruments.get_by_id(request.instrument_id)
        if instrument is None:
            raise ApplicationError("RISK_INSTRUMENT_NOT_FOUND", "instrument was not found")
        balances = await uow.cash_balances.list_for_account(account.id)
        cash = next((item for item in balances if item.currency == account.base_currency), None)
        positions = await uow.positions.list_for_account(account.id)
        latest = await uow.account_snapshots.latest(account.id)
        account_payload: dict[str, object] = {
            "account_id": str(account.id),
            "account_type": account.account_type.value,
            "account_status": account.status.value,
            "cash_fact_available": cash is not None,
            "valuation_fact_available": latest is not None,
            "position_count": len(positions),
        }
        instrument_snapshot = RiskInstrumentSnapshot(
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            active=instrument.is_active,
            lot_size=instrument.lot_size,
            price_tick=instrument.price_tick,
            reference_price=request.reference_price,
            snapshot_at=request.requested_at,
        )
        instrument_payload = _json(asdict(instrument_snapshot))
        assert isinstance(instrument_payload, dict)
        if cash is None:
            return RiskSnapshots(
                None,
                instrument_snapshot,
                account_payload,
                instrument_payload,
                "RISK_CASH_SNAPSHOT_UNAVAILABLE",
            )
        if positions and (
            latest is None
            or latest.positions_market_value is None
            or latest.total_equity is None
            or any(item.market_value is None for item in positions)
        ):
            account_payload["valuation_status"] = (
                None if latest is None else latest.valuation_status.value
            )
            return RiskSnapshots(
                None,
                instrument_snapshot,
                account_payload,
                instrument_payload,
                "RISK_ACCOUNT_VALUATION_UNAVAILABLE",
            )
        market_value = (
            Decimal("0")
            if not positions
            else (None if latest is None else latest.positions_market_value)
        )
        total_equity = (
            cash.total_cash if not positions else (None if latest is None else latest.total_equity)
        )
        assert market_value is not None and total_equity is not None
        recent = await uow.orders.list_recent_timestamps(
            account.id,
            request.requested_at - timedelta(seconds=limits.order_frequency_window_seconds),
        )
        position_snapshots = tuple(
            RiskPositionSnapshot(
                instrument_id=item.instrument_id,
                quantity=item.total_quantity,
                sellable_quantity=item.available_quantity,
                market_value=item.market_value or Decimal("0"),
                reference_price=item.last_price,
            )
            for item in positions
        )
        risk_account = RiskAccountSnapshot(
            account_id=account.id,
            account_type=account.account_type,
            account_status=account.status,
            cash_available=cash.available_cash,
            cash_total=cash.total_cash,
            market_value=market_value,
            total_equity=total_equity,
            positions=position_snapshots,
            open_order_count=await uow.orders.count_open(account.id),
            recent_order_timestamps=tuple(recent),
            kill_switch_enabled=bool(account.metadata.get("kill_switch_enabled", False)),
            snapshot_at=request.requested_at,
        )
        payload = _json(asdict(risk_account))
        assert isinstance(payload, dict)
        return RiskSnapshots(risk_account, instrument_snapshot, payload, instrument_payload)


def risk_request_fingerprint(request: RiskRequest, limits_marker: str) -> str:
    return payload_hash(
        {
            "schema_version": request.schema_version,
            "source_type": request.source_type.value,
            "source_id": None if request.source_id is None else str(request.source_id),
            "account_id": str(request.account_id),
            "instrument_id": str(request.instrument_id),
            "side": request.side.value,
            "order_type": request.order_type.value,
            "quantity": str(request.quantity),
            "limit_price": None if request.limit_price is None else str(request.limit_price),
            "reference_price": None
            if request.reference_price is None
            else str(request.reference_price),
            "strategy_key": request.strategy_key,
            "limits_marker": limits_marker,
        }
    )


@dataclass(frozen=True, slots=True)
class RiskAssessmentOutcome:
    decision: RiskDecision
    rule_results: tuple[RiskRuleEvaluation, ...]
    order: Order | None = None


class RiskAssessmentService:
    def __init__(
        self,
        limits_provider: RiskLimitsProvider,
        evaluator: RuleBasedRiskEvaluator | None = None,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._limits_provider = limits_provider
        self._evaluator = evaluator or RuleBasedRiskEvaluator()
        self._snapshot_service = RiskSnapshotService()
        self._failure = failure_injector or (lambda _stage: None)

    async def assess_in_transaction(
        self,
        uow: UnitOfWork,
        request: RiskRequest,
        idempotency_key: str,
        *,
        order_id: UUID | None = None,
    ) -> RiskAssessmentOutcome:
        await uow.risk_decisions.lock_idempotency_key(idempotency_key)
        fingerprint = risk_request_fingerprint(request, self._limits_provider.version_marker)
        existing = await uow.risk_decisions.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ApplicationError(
                    "RISK_IDEMPOTENCY_CONFLICT", "idempotency key has different input"
                )
            rules = await uow.risk_rule_evaluations.list_by_decision(existing.id)
            order = (
                None if existing.order_id is None else await uow.orders.get_by_id(existing.order_id)
            )
            return RiskAssessmentOutcome(existing, tuple(rules), order)
        limits = self._limits_provider.get_limits(request.account_id)
        snapshots = await self._snapshot_service.build(uow, request, limits)
        if snapshots.account is None:
            reason = snapshots.review_reason or "RISK_SNAPSHOT_UNAVAILABLE"
            result = RiskEvaluationResult(
                request_id=request.request_id,
                overall_decision=RiskDecisionType.REQUIRE_CONFIRMATION,
                rule_results=(
                    RiskRuleResult(
                        rule_key="authoritative_snapshot",
                        decision=RiskDecisionType.REQUIRE_CONFIRMATION,
                        reason_code=reason,
                        message=(
                            "authoritative PostgreSQL valuation is unavailable; "
                            "manual review is required"
                        ),
                        severity=RiskSeverity.WARNING,
                        evaluated_at=request.requested_at,
                    ),
                ),
                evaluated_at=request.requested_at,
                warnings=(reason,),
            )
        else:
            result = self._evaluator.evaluate(
                request, snapshots.account, snapshots.instrument, limits
            )
        effective_order_id = order_id if result.overall_decision is RiskDecisionType.ALLOW else None
        limits_payload = _json(asdict(limits))
        assert isinstance(limits_payload, dict)
        limits_payload["version_marker"] = self._limits_provider.version_marker
        decision = RiskDecision(
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            request_id=request.request_id,
            source_type=request.source_type.value,
            source_id=request.source_id,
            signal_id=request.signal_id,
            order_id=effective_order_id,
            account_id=request.account_id,
            instrument_id=request.instrument_id,
            overall_decision=result.overall_decision,
            estimated_notional=result.estimated_notional,
            projected_instrument_weight=result.projected_instrument_weight,
            projected_total_exposure=result.projected_total_exposure,
            limits_snapshot=limits_payload,
            account_snapshot=snapshots.account_payload,
            instrument_snapshot=snapshots.instrument_payload,
            warnings=list(result.warnings),
            correlation_id=request.correlation_id,
            evaluated_at=result.evaluated_at,
        )
        await uow.risk_decisions.append(decision)
        self._failure("after_decision")
        facts: list[RiskRuleEvaluation] = []
        for seq, item in enumerate(result.rule_results, 1):
            observed = _json(item.observed_value)
            limit = _json(item.limit_value)
            metadata = _json(dict(item.metadata))
            assert isinstance(observed, (str, int, bool, type(None)))
            assert isinstance(limit, (str, int, bool, type(None)))
            assert isinstance(metadata, dict)
            fact = RiskRuleEvaluation(
                risk_decision_id=decision.id,
                seq=seq,
                rule_key=item.rule_key,
                decision=item.decision,
                reason_code=item.reason_code,
                message=item.message,
                severity=item.severity.value,
                observed_value=observed,
                limit_value=limit,
                metadata=metadata,
                evaluated_at=item.evaluated_at,
            )
            await uow.risk_rule_evaluations.append(fact)
            facts.append(fact)
        self._failure("after_rules")
        await uow.events.append(
            DomainEvent(
                event_id=uuid4(),
                event_type="RISK_DECISION_EVALUATED",
                entity_type="RISK_DECISION",
                entity_id=decision.id,
                source="ALPHADESK_R01",
                event_time=result.evaluated_at,
                received_time=result.evaluated_at,
                correlation_id=request.correlation_id,
                schema_version=1,
                payload={
                    "risk_decision_id": str(decision.id),
                    "decision": decision.overall_decision.value,
                    "rule_count": len(facts),
                    "order_id": None if decision.order_id is None else str(decision.order_id),
                },
            )
        )
        self._failure("after_event")
        await uow.audit_logs.append(
            AuditLog(
                actor_type="SYSTEM",
                action="RISK_DECISION_EVALUATED",
                resource_type="RISK_DECISION",
                resource_id=decision.id,
                outcome=decision.overall_decision.value,
                correlation_id=request.correlation_id,
                occurred_at=result.evaluated_at,
                details={"source_type": decision.source_type, "rule_count": len(facts)},
            )
        )
        self._failure("after_audit")
        return RiskAssessmentOutcome(decision, tuple(facts))


class RiskGatedOrderService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        limits_provider: RiskLimitsProvider,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._failure = failure_injector or (lambda _stage: None)
        self._assessment = RiskAssessmentService(limits_provider, failure_injector=self._failure)
        self._orders = OrderIntentService(uow_factory, self._failure)

    async def create(self, order_request: CreateOrderRequest) -> RiskAssessmentOutcome:
        requested_at = order_request.occurred_at
        if requested_at is None:
            raise ApplicationError("RISK_INVALID_REQUEST", "occurred_at is required")
        request = RiskRequest(
            request_id=uuid4(),
            correlation_id=order_request.correlation_id,
            source_type=RiskRequestSource.MANUAL_ORDER,
            account_id=order_request.account_id,
            instrument_id=order_request.instrument_id,
            side=OrderSide(order_request.side),
            order_type=OrderType(order_request.order_type),
            quantity=order_request.quantity,
            limit_price=order_request.limit_price,
            requested_at=requested_at,
        )
        order_id = uuid4()
        async with self._uow_factory() as uow:
            outcome = await self._assessment.assess_in_transaction(
                uow, request, order_request.idempotency_key, order_id=order_id
            )
            if outcome.decision.overall_decision is RiskDecisionType.ALLOW:
                if outcome.order is not None:
                    return outcome
                order = await self._orders.create_in_transaction(
                    uow, order_request, order_id=order_id
                )
                self._failure("after_order")
                outcome = RiskAssessmentOutcome(outcome.decision, outcome.rule_results, order)
            self._failure("before_commit")
            await uow.commit()
            return outcome


class SignalRiskAssessmentService:
    """Evaluate and persist a Signal only; never creates an Order."""

    def __init__(self, uow_factory: UnitOfWorkFactory, limits_provider: RiskLimitsProvider) -> None:
        self._uow_factory = uow_factory
        self._limits_provider = limits_provider
        self._assessment = RiskAssessmentService(limits_provider)

    async def assess(
        self, signal_id: UUID, idempotency_key: str, correlation_id: UUID
    ) -> RiskAssessmentOutcome:
        async with self._uow_factory() as uow:
            signal = await uow.signals.get_by_id(signal_id)
            if signal is None or signal.account_id is None:
                raise ApplicationError(
                    "RISK_SIGNAL_NOT_ELIGIBLE", "signal or account is unavailable"
                )
            if signal.target_quantity is None:
                await uow.risk_decisions.lock_idempotency_key(idempotency_key)
                fingerprint = payload_hash(
                    {
                        "schema_version": 1,
                        "source_type": "STRATEGY_SIGNAL",
                        "source_id": str(signal.id),
                        "target_weight": (
                            None if signal.target_weight is None else str(signal.target_weight)
                        ),
                        "limits_marker": self._limits_provider.version_marker,
                    }
                )
                existing = await uow.risk_decisions.get_by_idempotency_key(idempotency_key)
                if existing is not None:
                    if existing.request_fingerprint != fingerprint:
                        raise ApplicationError(
                            "RISK_IDEMPOTENCY_CONFLICT", "idempotency key has different input"
                        )
                    rules = await uow.risk_rule_evaluations.list_by_decision(existing.id)
                    return RiskAssessmentOutcome(existing, tuple(rules))
                now = signal.generated_at
                decision = RiskDecision(
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                    request_id=uuid4(),
                    source_type="STRATEGY_SIGNAL",
                    source_id=signal.id,
                    signal_id=signal.id,
                    account_id=signal.account_id,
                    instrument_id=signal.instrument_id,
                    overall_decision=RiskDecisionType.REQUIRE_CONFIRMATION,
                    limits_snapshot={"version_marker": self._limits_provider.version_marker},
                    account_snapshot={"account_id": str(signal.account_id)},
                    instrument_snapshot={"instrument_id": str(signal.instrument_id)},
                    warnings=["RISK_SIGNAL_TARGET_UNSUPPORTED"],
                    correlation_id=correlation_id,
                    evaluated_at=now,
                )
                rule = RiskRuleEvaluation(
                    risk_decision_id=decision.id,
                    seq=1,
                    rule_key="signal_target",
                    decision=RiskDecisionType.REQUIRE_CONFIRMATION,
                    reason_code="RISK_SIGNAL_TARGET_UNSUPPORTED",
                    message="target_weight cannot be converted to quantity without guessing",
                    severity=RiskSeverity.WARNING.value,
                    evaluated_at=now,
                )
                await uow.risk_decisions.append(decision)
                await uow.risk_rule_evaluations.append(rule)
                await uow.events.append(
                    DomainEvent(
                        event_id=uuid4(),
                        event_type="RISK_DECISION_EVALUATED",
                        entity_type="RISK_DECISION",
                        entity_id=decision.id,
                        source="ALPHADESK_R01",
                        event_time=now,
                        received_time=now,
                        correlation_id=correlation_id,
                        schema_version=1,
                        payload={
                            "risk_decision_id": str(decision.id),
                            "decision": decision.overall_decision.value,
                            "rule_count": 1,
                            "order_id": None,
                        },
                    )
                )
                await uow.audit_logs.append(
                    AuditLog(
                        actor_type="SYSTEM",
                        action="RISK_DECISION_EVALUATED",
                        resource_type="RISK_DECISION",
                        resource_id=decision.id,
                        outcome=decision.overall_decision.value,
                        correlation_id=correlation_id,
                        occurred_at=now,
                        details={"source_type": "STRATEGY_SIGNAL", "rule_count": 1},
                    )
                )
                await uow.commit()
                return RiskAssessmentOutcome(decision, (rule,))
            request = RiskRequest(
                request_id=uuid4(),
                correlation_id=correlation_id,
                source_type=RiskRequestSource.STRATEGY_SIGNAL,
                source_id=signal.id,
                signal_id=signal.id,
                account_id=signal.account_id,
                instrument_id=signal.instrument_id,
                side=signal.side,
                order_type=OrderType.MARKET,
                quantity=signal.target_quantity,
                reference_price=signal.reference_price,
                strategy_key=signal.strategy_key,
                requested_at=signal.generated_at,
            )
            outcome = await self._assessment.assess_in_transaction(uow, request, idempotency_key)
            await uow.commit()
            return outcome


class RiskDecisionQueryService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def detail(self, decision_id: UUID) -> dict[str, object]:
        async with self._uow_factory() as uow:
            decision = await uow.risk_decisions.get_by_id(decision_id)
            if decision is None:
                raise ApplicationError("RISK_DECISION_NOT_FOUND", "risk decision was not found")
            rules = await uow.risk_rule_evaluations.list_by_decision(decision.id)
            return self._view(decision, rules)

    async def list(
        self,
        *,
        page: int,
        page_size: int,
        account_id: UUID | None = None,
        instrument_id: UUID | None = None,
        source_type: str | None = None,
        source_id: UUID | None = None,
        decision: str | None = None,
    ) -> dict[str, object]:
        async with self._uow_factory() as uow:
            decisions, total = await uow.risk_decisions.list(
                offset=(page - 1) * page_size,
                limit=page_size,
                account_id=account_id,
                instrument_id=instrument_id,
                source_type=source_type,
                source_id=source_id,
                decision=decision,
            )
            items = []
            for stored_decision in decisions:
                rules = await uow.risk_rule_evaluations.list_by_decision(stored_decision.id)
                items.append(self._view(stored_decision, rules))
            return {"items": items, "page": page, "page_size": page_size, "total": total}

    @staticmethod
    def _view(
        decision: RiskDecision, rules: builtins.list[RiskRuleEvaluation]
    ) -> dict[str, object]:
        value = _json(asdict(decision))
        assert isinstance(value, dict)
        value["overall_decision"] = decision.overall_decision.value
        value["layer"] = decision.layer.value
        rule_values = [_json(asdict(item)) for item in rules]
        assert all(isinstance(item, dict) for item in rule_values)
        value["rule_results"] = rule_values
        return value


@dataclass(frozen=True, slots=True)
class RiskIntegrityIssue:
    risk_decision_id: UUID
    code: str
    message: str


class RiskDecisionIntegrityService:
    """Read-only consistency report; it never repairs or rewrites facts."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def verify(self) -> builtins.list[RiskIntegrityIssue]:
        issues: builtins.list[RiskIntegrityIssue] = []
        async with self._uow_factory() as uow:
            decisions, _ = await uow.risk_decisions.list(offset=0, limit=10000)
            for decision in decisions:
                rules = await uow.risk_rule_evaluations.list_by_decision(decision.id)
                if [item.seq for item in rules] != list(range(1, len(rules) + 1)):
                    issues.append(
                        RiskIntegrityIssue(
                            decision.id, "RISK_RULE_SEQUENCE_GAP", "rule sequence is not continuous"
                        )
                    )
                aggregate = (
                    RiskDecisionType.REJECT
                    if any(item.decision is RiskDecisionType.REJECT for item in rules)
                    else RiskDecisionType.REQUIRE_CONFIRMATION
                    if any(item.decision is RiskDecisionType.REQUIRE_CONFIRMATION for item in rules)
                    else RiskDecisionType.ALLOW
                )
                if rules and aggregate is not decision.overall_decision:
                    issues.append(
                        RiskIntegrityIssue(
                            decision.id,
                            "RISK_AGGREGATE_MISMATCH",
                            "overall decision does not match rule facts",
                        )
                    )
                if decision.overall_decision is RiskDecisionType.ALLOW and (
                    decision.source_type == RiskRequestSource.MANUAL_ORDER.value
                ):
                    order = (
                        None
                        if decision.order_id is None
                        else await uow.orders.get_by_id(decision.order_id)
                    )
                    transitions = (
                        []
                        if order is None
                        else await uow.order_state_transitions.list_by_order(order.id)
                    )
                    if order is None or order.row_version != 2 or len(transitions) != 2:
                        issues.append(
                            RiskIntegrityIssue(
                                decision.id,
                                "RISK_ORDER_FACT_MISMATCH",
                                "PASS manual decision lacks the M05 initial order fact set",
                            )
                        )
                elif decision.order_id is not None:
                    issues.append(
                        RiskIntegrityIssue(
                            decision.id,
                            "RISK_UNEXPECTED_ORDER_LINK",
                            "non-PASS or non-manual decision must not link an order",
                        )
                    )
        return issues
