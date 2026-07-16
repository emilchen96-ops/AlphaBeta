import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from alphadesk_domain.enums import (
    AccountStatus,
    AccountType,
    OrderSide,
    OrderType,
    RiskDecisionType,
)
from alphadesk_domain.risk import (
    CORE_RISK_RULES,
    AccountEligibilityRule,
    AvailableCashRule,
    EstimatedNotionalRule,
    InstrumentEligibilityRule,
    KillSwitchRule,
    MaxInstrumentWeightRule,
    MaxOrderNotionalRule,
    MaxTotalExposureRule,
    OrderFrequencyRule,
    OrderStructureRule,
    PassThroughRiskEvaluator,
    RiskAccountSnapshot,
    RiskError,
    RiskInstrumentSnapshot,
    RiskLimits,
    RiskPositionSnapshot,
    RiskRequest,
    RiskRequestSource,
    RiskRuleResult,
    RiskSeverity,
    RuleBasedRiskEvaluator,
    SellablePositionRule,
)

NOW = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
ACCOUNT_ID = uuid4()
INSTRUMENT_ID = uuid4()


def request(**changes: object) -> RiskRequest:
    values: dict[str, object] = {
        "request_id": uuid4(),
        "correlation_id": uuid4(),
        "source_type": RiskRequestSource.MANUAL_ORDER,
        "account_id": ACCOUNT_ID,
        "instrument_id": INSTRUMENT_ID,
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("100"),
        "limit_price": Decimal("10.00"),
        "requested_at": NOW,
    }
    values.update(changes)
    return RiskRequest(**values)  # type: ignore[arg-type]


def position(**changes: object) -> RiskPositionSnapshot:
    values: dict[str, object] = {
        "instrument_id": INSTRUMENT_ID,
        "quantity": Decimal("1000"),
        "sellable_quantity": Decimal("800"),
        "market_value": Decimal("10000"),
        "reference_price": Decimal("10"),
    }
    values.update(changes)
    return RiskPositionSnapshot(**values)  # type: ignore[arg-type]


def account(**changes: object) -> RiskAccountSnapshot:
    values: dict[str, object] = {
        "account_id": ACCOUNT_ID,
        "account_type": AccountType.SIMULATED,
        "account_status": AccountStatus.ACTIVE,
        "cash_available": Decimal("10000"),
        "cash_total": Decimal("10000"),
        "market_value": Decimal("20000"),
        "total_equity": Decimal("30000"),
        "positions": (position(),),
        "open_order_count": 0,
        "recent_order_timestamps": (),
        "kill_switch_enabled": False,
        "snapshot_at": NOW,
    }
    values.update(changes)
    return RiskAccountSnapshot(**values)  # type: ignore[arg-type]


def instrument(**changes: object) -> RiskInstrumentSnapshot:
    values: dict[str, object] = {
        "instrument_id": INSTRUMENT_ID,
        "symbol": "600000",
        "exchange": "SSE",
        "active": True,
        "lot_size": Decimal("100"),
        "price_tick": Decimal("0.01"),
        "reference_price": Decimal("10"),
        "snapshot_at": NOW,
    }
    values.update(changes)
    return RiskInstrumentSnapshot(**values)  # type: ignore[arg-type]


def limits(**changes: object) -> RiskLimits:
    values: dict[str, object] = {
        "max_order_notional": Decimal("2000"),
        "max_instrument_weight": Decimal("0.40"),
        "max_total_exposure": Decimal("0.75"),
        "max_orders_per_window": 5,
        "order_frequency_window_seconds": 60,
        "allow_market_orders": True,
        "require_reference_price_for_market_order": True,
        "kill_switch_enabled": False,
    }
    values.update(changes)
    return RiskLimits(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value", [1.0, float("nan"), float("inf"), Decimal("NaN"), Decimal("Infinity")]
)
def test_risk_request_rejects_float_and_non_finite_quantity(value: object) -> None:
    with pytest.raises((RiskError, TypeError)) as exc_info:
        request(quantity=value)
    if isinstance(exc_info.value, RiskError):
        assert exc_info.value.code == "RISK_INVALID_REQUEST"


def test_risk_request_order_contract_and_time_normalization() -> None:
    with pytest.raises(RiskError, match="requires limit_price"):
        request(limit_price=None)
    with pytest.raises(RiskError, match="must not carry"):
        request(order_type=OrderType.MARKET, limit_price=Decimal("10"))
    with pytest.raises(RiskError, match="timezone-aware"):
        request(requested_at=datetime(2026, 1, 1))
    eastern = timezone(timedelta(hours=8))
    normalized = request(requested_at=datetime(2026, 7, 16, 16, 0, tzinfo=eastern))
    assert normalized.requested_at == NOW
    assert normalized.requested_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"max_order_notional": Decimal("0")}, "must be positive"),
        ({"max_instrument_weight": Decimal("1.01")}, "between zero and one"),
        ({"max_total_exposure": Decimal("-0.01")}, "between zero and one"),
        ({"max_orders_per_window": 0}, "must be positive"),
        ({"order_frequency_window_seconds": 0}, "must be positive"),
    ],
)
def test_risk_limits_validate_ranges(changes: dict[str, object], message: str) -> None:
    with pytest.raises(RiskError, match=message) as exc_info:
        limits(**changes)
    assert exc_info.value.code == "RISK_INVALID_LIMITS"


def test_snapshots_are_frozen_decimal_only_and_utc() -> None:
    snapshot = account(recent_order_timestamps=(NOW, NOW - timedelta(seconds=1)))
    assert snapshot.recent_order_timestamps == (NOW - timedelta(seconds=1), NOW)
    with pytest.raises(FrozenInstanceError):
        snapshot.cash_available = Decimal("0")  # type: ignore[misc]
    with pytest.raises(RiskError, match="must be Decimal"):
        account(cash_available=1.0)
    with pytest.raises(RiskError, match="timezone-aware"):
        instrument(snapshot_at=datetime(2026, 1, 1))


def test_rule_result_serialization_is_stable_and_metadata_is_immutable() -> None:
    result = RiskRuleResult(
        rule_key="z_rule",
        decision=RiskDecisionType.ALLOW,
        reason_code="RISK_RULE_PASSED",
        message="passed",
        severity=RiskSeverity.INFO,
        observed_value=Decimal("1.2300"),
        metadata={"z": Decimal("2.00"), "a": True},
        evaluated_at=NOW,
    )
    assert list(result.metadata) == ["a", "z"]
    assert result.to_dict()["observed_value"] == "1.2300"
    assert result.to_dict()["metadata"] == {"a": True, "z": "2.00"}
    with pytest.raises(TypeError):
        result.metadata["x"] = 1  # type: ignore[index]


class FixedRule:
    def __init__(self, key: str, priority: int, decision: RiskDecisionType) -> None:
        self.rule_key = key
        self.priority = priority
        self.decision = decision

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        return RiskRuleResult(
            rule_key=self.rule_key,
            decision=self.decision,
            reason_code="TEST",
            message="test result",
            severity=RiskSeverity.INFO,
            evaluated_at=request.requested_at,
        )


class BrokenRule:
    rule_key = "broken"
    priority = 1

    def evaluate(
        self,
        request: RiskRequest,
        account: RiskAccountSnapshot,
        instrument: RiskInstrumentSnapshot,
        limits: RiskLimits,
    ) -> RiskRuleResult:
        raise RuntimeError("secret local stack and database URL")


def test_evaluator_orders_rules_and_rejects_duplicate_keys() -> None:
    evaluator = RuleBasedRiskEvaluator(
        [
            FixedRule("z", 20, RiskDecisionType.ALLOW),
            FixedRule("b", 10, RiskDecisionType.ALLOW),
            FixedRule("a", 10, RiskDecisionType.ALLOW),
        ]
    )
    assert [rule.rule_key for rule in evaluator.rules] == ["a", "b", "z"]
    with pytest.raises(RiskError) as exc_info:
        evaluator.register(FixedRule("a", 30, RiskDecisionType.ALLOW))
    assert exc_info.value.code == "RISK_RULE_ALREADY_REGISTERED"


@pytest.mark.parametrize(
    ("decisions", "expected"),
    [
        ([RiskDecisionType.ALLOW], RiskDecisionType.ALLOW),
        (
            [RiskDecisionType.ALLOW, RiskDecisionType.REQUIRE_CONFIRMATION],
            RiskDecisionType.REQUIRE_CONFIRMATION,
        ),
        ([RiskDecisionType.REQUIRE_CONFIRMATION, RiskDecisionType.REJECT], RiskDecisionType.REJECT),
    ],
)
def test_evaluator_aggregates_decisions(
    decisions: list[RiskDecisionType], expected: RiskDecisionType
) -> None:
    rules = [
        FixedRule(f"rule_{index}", index, decision) for index, decision in enumerate(decisions)
    ]
    result = RuleBasedRiskEvaluator(rules).evaluate(request(), account(), instrument(), limits())
    assert result.overall_decision is expected


def test_rule_exception_fails_closed_without_leaking_details() -> None:
    result = RuleBasedRiskEvaluator([BrokenRule()]).evaluate(
        request(), account(), instrument(), limits()
    )
    rule_result = result.rule_results[0]
    assert result.overall_decision is RiskDecisionType.REQUIRE_CONFIRMATION
    assert rule_result.reason_code == "RISK_RULE_EXECUTION_FAILED"
    assert "database" not in rule_result.message


def test_evaluation_is_deterministic_for_identical_inputs() -> None:
    evaluator = RuleBasedRiskEvaluator()
    first = evaluator.evaluate(request(request_id=uuid4()), account(), instrument(), limits())
    second = evaluator.evaluate(
        RiskRequest(
            request_id=first.request_id,
            correlation_id=uuid4(),
            source_type=RiskRequestSource.MANUAL_ORDER,
            account_id=ACCOUNT_ID,
            instrument_id=INSTRUMENT_ID,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("100"),
            limit_price=Decimal("10.00"),
            requested_at=NOW,
        ),
        account(),
        instrument(),
        limits(),
    )
    assert first == second


def test_pass_through_is_explicit_and_restricted() -> None:
    result = PassThroughRiskEvaluator("development").evaluate(
        request(), account(), instrument(), limits()
    )
    assert result.overall_decision is RiskDecisionType.ALLOW
    assert result.warnings == ("RISK_RULES_BYPASSED",)
    with pytest.raises(RiskError) as exc_info:
        PassThroughRiskEvaluator("production")
    assert exc_info.value.code == "RISK_PASSTHROUGH_NOT_ALLOWED"


@pytest.mark.parametrize(
    ("rule", "account_changes"),
    [
        (AccountEligibilityRule(), {"account_type": AccountType.CASH}),
        (AccountEligibilityRule(), {"account_status": AccountStatus.READ_ONLY}),
    ],
)
def test_account_eligibility_rejects_non_simulated_or_inactive(
    rule: AccountEligibilityRule, account_changes: dict[str, object]
) -> None:
    result = rule.evaluate(request(), account(**account_changes), instrument(), limits())
    assert result.decision is RiskDecisionType.REJECT
    assert result.reason_code == "RISK_ACCOUNT_NOT_ELIGIBLE"


def test_instrument_eligibility_and_kill_switch_rejections() -> None:
    inactive = InstrumentEligibilityRule().evaluate(
        request(), account(), instrument(active=False), limits()
    )
    account_kill = KillSwitchRule().evaluate(
        request(), account(kill_switch_enabled=True), instrument(), limits()
    )
    limits_kill = KillSwitchRule().evaluate(
        request(), account(), instrument(), limits(kill_switch_enabled=True)
    )
    assert inactive.reason_code == "RISK_INSTRUMENT_NOT_ELIGIBLE"
    assert account_kill.metadata["scope"] == "ACCOUNT"
    assert limits_kill.metadata["scope"] == "LIMITS"
    assert {inactive.decision, account_kill.decision, limits_kill.decision} == {
        RiskDecisionType.REJECT
    }


def test_order_structure_checks_lot_tick_and_market_configuration() -> None:
    rule = OrderStructureRule()
    lot = rule.evaluate(request(quantity=Decimal("150")), account(), instrument(), limits())
    tick = rule.evaluate(request(limit_price=Decimal("10.005")), account(), instrument(), limits())
    market_request = request(
        order_type=OrderType.MARKET, limit_price=None, reference_price=Decimal("10")
    )
    market = rule.evaluate(
        market_request, account(), instrument(), limits(allow_market_orders=False)
    )
    assert [item.reason_code for item in (lot, tick, market)] == [
        "RISK_ORDER_STRUCTURE_INVALID"
    ] * 3


def test_estimated_notional_uses_limit_and_market_reference_prices() -> None:
    limit_result = EstimatedNotionalRule().evaluate(request(), account(), instrument(), limits())
    market_request = request(
        order_type=OrderType.MARKET, limit_price=None, reference_price=Decimal("12.34")
    )
    market_result = EstimatedNotionalRule().evaluate(
        market_request, account(), instrument(), limits()
    )
    missing_request = request(order_type=OrderType.MARKET, limit_price=None, reference_price=None)
    missing = EstimatedNotionalRule().evaluate(
        missing_request, account(), instrument(reference_price=None), limits()
    )
    review = EstimatedNotionalRule().evaluate(
        missing_request,
        account(),
        instrument(reference_price=None),
        limits(require_reference_price_for_market_order=False),
    )
    assert limit_result.observed_value == Decimal("1000.00")
    assert market_result.observed_value == Decimal("1234.00")
    assert missing.decision is RiskDecisionType.REJECT
    assert review.decision is RiskDecisionType.REQUIRE_CONFIRMATION
    assert missing.reason_code == "RISK_REFERENCE_PRICE_REQUIRED"


def test_available_cash_buy_and_sell_paths() -> None:
    rule = AvailableCashRule()
    sufficient = rule.evaluate(
        request(), account(cash_available=Decimal("1000")), instrument(), limits()
    )
    insufficient = rule.evaluate(
        request(),
        account(cash_available=Decimal("999"), cash_total=Decimal("999")),
        instrument(),
        limits(),
    )
    sell = rule.evaluate(
        request(side=OrderSide.SELL),
        account(cash_available=Decimal("0"), cash_total=Decimal("0")),
        instrument(),
        limits(),
    )
    assert sufficient.decision is RiskDecisionType.ALLOW
    assert insufficient.reason_code == "RISK_INSUFFICIENT_CASH"
    assert insufficient.decision is RiskDecisionType.REJECT
    assert sell.decision is RiskDecisionType.ALLOW


def test_sellable_position_prevents_naked_short_selling() -> None:
    rule = SellablePositionRule()
    sufficient = rule.evaluate(
        request(side=OrderSide.SELL, quantity=Decimal("800")), account(), instrument(), limits()
    )
    insufficient = rule.evaluate(
        request(side=OrderSide.SELL, quantity=Decimal("900")), account(), instrument(), limits()
    )
    missing = rule.evaluate(
        request(side=OrderSide.SELL), account(positions=()), instrument(), limits()
    )
    assert sufficient.decision is RiskDecisionType.ALLOW
    assert insufficient.reason_code == "RISK_INSUFFICIENT_POSITION"
    assert missing.decision is RiskDecisionType.REJECT


def test_notional_weight_and_total_exposure_limits() -> None:
    max_order = MaxOrderNotionalRule().evaluate(
        request(), account(), instrument(), limits(max_order_notional=Decimal("999"))
    )
    max_weight = MaxInstrumentWeightRule().evaluate(
        request(), account(), instrument(), limits(max_instrument_weight=Decimal("0.35"))
    )
    max_exposure = MaxTotalExposureRule().evaluate(
        request(), account(), instrument(), limits(max_total_exposure=Decimal("0.69"))
    )
    assert max_order.reason_code == "RISK_MAX_ORDER_NOTIONAL_EXCEEDED"
    assert max_weight.reason_code == "RISK_MAX_INSTRUMENT_WEIGHT_EXCEEDED"
    assert max_exposure.reason_code == "RISK_MAX_TOTAL_EXPOSURE_EXCEEDED"
    assert all(
        item.decision is RiskDecisionType.REJECT for item in (max_order, max_weight, max_exposure)
    )


def test_non_positive_equity_fails_controlled_weight_calculations() -> None:
    zero_equity = account(total_equity=Decimal("0"))
    weight = MaxInstrumentWeightRule().evaluate(request(), zero_equity, instrument(), limits())
    exposure = MaxTotalExposureRule().evaluate(request(), zero_equity, instrument(), limits())
    assert weight.reason_code == exposure.reason_code == "RISK_EQUITY_NOT_POSITIVE"
    assert weight.decision is exposure.decision is RiskDecisionType.REJECT


def test_order_frequency_window_is_inclusive_and_ignores_future_or_old_values() -> None:
    timestamps = (
        NOW - timedelta(seconds=61),
        NOW - timedelta(seconds=60),
        NOW - timedelta(seconds=60) + timedelta(microseconds=1),
        NOW,
        NOW + timedelta(microseconds=1),
    )
    result = OrderFrequencyRule().evaluate(
        request(),
        account(recent_order_timestamps=timestamps),
        instrument(),
        limits(max_orders_per_window=2),
    )
    assert result.observed_value == 2
    assert result.decision is RiskDecisionType.REJECT
    assert result.reason_code == "RISK_ORDER_FREQUENCY_EXCEEDED"


def test_unconfigured_optional_limits_pass() -> None:
    unconfigured = RiskLimits(allow_market_orders=True)
    results = [
        MaxOrderNotionalRule().evaluate(request(), account(), instrument(), unconfigured),
        MaxInstrumentWeightRule().evaluate(request(), account(), instrument(), unconfigured),
        MaxTotalExposureRule().evaluate(request(), account(), instrument(), unconfigured),
        OrderFrequencyRule().evaluate(request(), account(), instrument(), unconfigured),
    ]
    assert all(result.decision is RiskDecisionType.ALLOW for result in results)


def test_default_core_rules_allow_safe_request_and_return_derived_values() -> None:
    result = RuleBasedRiskEvaluator(CORE_RISK_RULES).evaluate(
        request(), account(), instrument(), limits()
    )
    assert result.overall_decision is RiskDecisionType.ALLOW
    assert result.estimated_notional == Decimal("1000.00")
    assert result.projected_instrument_weight == Decimal("11000") / Decimal("30000")
    assert result.projected_total_exposure == Decimal("21000") / Decimal("30000")
    assert len(result.rule_results) == 11


def test_risk_core_has_no_framework_persistence_or_execution_dependencies() -> None:
    source_path = Path(__file__).resolve().parents[2] / "src" / "alphadesk_domain" / "risk.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"fastapi", "sqlalchemy", "alembic", "redis", "xtquant", "miniqmt"})
    assert "RiskDecision(" not in source
    assert "Order(" not in source
    assert "Fill(" not in source
    assert ".commit(" not in source
