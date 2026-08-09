"""BT02-A no-look-ahead intraday evaluation for daily strategy rules.

Daily bars remain the source of completed-session history.  A current-session
bar is built only from minute bars whose interval has closed.  This prevents a
daily strategy from seeing the day's final high, low, close or volume early.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import pairwise
from uuid import UUID

from alphadesk_domain.backtest import ASHARE_TIMEZONE
from alphadesk_domain.enums import MarketTimeframe, OrderSide, SignalType
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.strategy import SignalDraft, StrategyBar, StrategyParameterValue
from alphadesk_domain.strategy_spec import (
    Comparison,
    ComparisonOperator,
    CompiledStrategy,
    ConditionGroup,
    IndicatorKind,
    LogicalOperator,
    MarketField,
    Operand,
    OperandKind,
    StrategySpec,
    _evaluate,
)

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PriceVolumeSmaRule:
    breakout_window: int
    volume_window: int
    volume_multiplier: Decimal
    exit_sma_window: int
    quantity: Decimal
    breakout_inclusive: bool = False
    volume_inclusive: bool = False
    exit_inclusive: bool = False


@dataclass(frozen=True, slots=True)
class IntradayPrefilterPlan:
    candidate_entry_dates: frozenset[date]
    candidate_exit_dates: frozenset[date]
    replay_dates: frozenset[date]
    safe: bool
    reason: str


@dataclass(frozen=True, slots=True)
class MinuteSessionQuality:
    usable: bool
    issues: tuple[str, ...]
    warnings: tuple[str, ...]
    minute_count: int


@dataclass(slots=True)
class _InstrumentState:
    is_long: bool = False
    trading_date: date | None = None
    entry_was_true: bool = False
    exit_was_true: bool = False


def _parameter_int(parameters: Mapping[str, StrategyParameterValue], key: str) -> int:
    value = parameters[key]
    if type(value) is not int:
        raise ValueError(f"{key} must be an integer")
    return value


def _parameter_decimal(parameters: Mapping[str, StrategyParameterValue], key: str) -> Decimal:
    value = parameters[key]
    if not isinstance(value, Decimal):
        raise ValueError(f"{key} must be a Decimal")
    return value


def reference_rule_from_parameters(
    parameters: Mapping[str, StrategyParameterValue],
) -> PriceVolumeSmaRule:
    return PriceVolumeSmaRule(
        breakout_window=_parameter_int(parameters, "breakout_window"),
        volume_window=_parameter_int(parameters, "volume_window"),
        volume_multiplier=_parameter_decimal(parameters, "volume_multiplier"),
        exit_sma_window=_parameter_int(parameters, "exit_sma_window"),
        quantity=_parameter_decimal(parameters, "quantity"),
    )


def _comparison_pair(group: ConditionGroup) -> tuple[Comparison, ...]:
    if group.operator is not LogicalOperator.AND:
        return ()
    return tuple(item for item in group.conditions if isinstance(item, Comparison))


def _field_operand(value: Operand, field_name: MarketField) -> bool:
    return value.kind is OperandKind.FIELD and value.field is field_name


def _indicator_operand(
    value: Operand,
    indicator: IndicatorKind,
    field_name: MarketField,
    *,
    exclude_current: bool,
) -> bool:
    return (
        value.kind is OperandKind.INDICATOR
        and value.indicator is indicator
        and value.field is field_name
        and value.window is not None
        and value.exclude_current is exclude_current
    )


def price_volume_sma_rule_from_spec(spec: StrategySpec) -> PriceVolumeSmaRule | None:
    """Recognise the reference rule even when it came from the safe AST compiler."""

    breakout: Comparison | None = None
    volume: Comparison | None = None
    for condition in _comparison_pair(spec.entry):
        if condition.operator not in (ComparisonOperator.GT, ComparisonOperator.GTE):
            continue
        if _field_operand(condition.left, MarketField.CLOSE) and _indicator_operand(
            condition.right,
            IndicatorKind.ROLLING_HIGHEST,
            MarketField.HIGH,
            exclude_current=True,
        ):
            breakout = condition
        if _field_operand(condition.left, MarketField.VOLUME) and _indicator_operand(
            condition.right,
            IndicatorKind.AVERAGE_VOLUME,
            MarketField.VOLUME,
            exclude_current=True,
        ):
            volume = condition
    exit_comparison: Comparison | None = None
    for condition in _comparison_pair(spec.exit):
        if (
            condition.operator in (ComparisonOperator.LT, ComparisonOperator.LTE)
            and _field_operand(condition.left, MarketField.CLOSE)
            and _indicator_operand(
                condition.right,
                IndicatorKind.SMA,
                MarketField.CLOSE,
                exclude_current=False,
            )
        ):
            exit_comparison = condition
    if breakout is None or volume is None or exit_comparison is None:
        return None
    assert breakout.right.window is not None and volume.right.window is not None
    assert exit_comparison.right.window is not None
    return PriceVolumeSmaRule(
        breakout_window=breakout.right.window,
        volume_window=volume.right.window,
        volume_multiplier=volume.right.multiplier,
        exit_sma_window=exit_comparison.right.window,
        quantity=spec.quantity,
        breakout_inclusive=breakout.operator is ComparisonOperator.GTE,
        volume_inclusive=volume.operator is ComparisonOperator.GTE,
        exit_inclusive=exit_comparison.operator is ComparisonOperator.LTE,
    )


def rule_for_strategy(
    strategy: object,
    strategy_key: str,
    parameters: Mapping[str, StrategyParameterValue],
) -> PriceVolumeSmaRule | None:
    if strategy_key == "price_volume_breakout_sma_exit":
        return reference_rule_from_parameters(parameters)
    if isinstance(strategy, CompiledStrategy):
        return price_volume_sma_rule_from_spec(strategy.spec)
    return None


def build_partial_daily_bar(
    daily_identity: StrategyBar,
    minute_bars: Sequence[StrategyBar],
) -> StrategyBar:
    """Aggregate only the supplied, already-closed minute bars."""

    if not minute_bars:
        raise ValueError("minute_bars must not be empty")
    ordered = sorted(minute_bars, key=lambda item: item.timestamp)
    if any(item.instrument_id != daily_identity.instrument_id for item in ordered):
        raise ValueError("minute bars belong to another instrument")
    amounts = [item.amount for item in ordered]
    return StrategyBar(
        instrument_id=daily_identity.instrument_id,
        symbol=daily_identity.symbol,
        exchange=daily_identity.exchange,
        timeframe=MarketTimeframe.DAY_1,
        timestamp=ordered[-1].timestamp,
        open=ordered[0].open,
        high=max(item.high for item in ordered),
        low=min(item.low for item in ordered),
        close=ordered[-1].close,
        volume=sum((item.volume for item in ordered), ZERO),
        amount=(
            sum((item for item in amounts if item is not None), ZERO)
            if all(item is not None for item in amounts)
            else None
        ),
        adjustment_mode=PriceAdjustmentMode.RAW,
        raw_reference_price=ordered[-1].close,
    )


def inspect_minute_session(
    daily_bar: StrategyBar,
    minute_bars: Sequence[StrategyBar],
) -> MinuteSessionQuality:
    """Check whether local minute data can safely replay one A-share session.

    A gap inside a session is reported but is not automatically fatal because it
    can represent a genuine temporary suspension.  MiniQMT's 09:30-14:59 minute
    series does not include the opening call auction while its authoritative RAW
    daily bar does.  Consequently the daily open/extremes/volume may contain an
    auction contribution that cannot be reconstructed from the 240 continuous-
    auction minutes.  Such one-sided differences are safe and are warnings;
    minute prices outside the daily envelope, a different close, excess minute
    volume, missing session edges, or duplicate/off-session timestamps remain
    fatal quality problems.
    """

    if not minute_bars:
        return MinuteSessionQuality(False, ("NO_MINUTE_BARS",), (), 0)
    ordered = sorted(minute_bars, key=lambda item: item.timestamp)
    issues: list[str] = []
    warnings: list[str] = []
    if any(item.instrument_id != daily_bar.instrument_id for item in ordered):
        issues.append("INSTRUMENT_MISMATCH")
    local_times = [
        item.timestamp.astimezone(ASHARE_TIMEZONE).replace(tzinfo=None) for item in ordered
    ]
    if len(set(local_times)) != len(local_times):
        issues.append("DUPLICATE_MINUTE")
    session_date = daily_bar.timestamp.astimezone(ASHARE_TIMEZONE).date()
    if any(item.date() != session_date for item in local_times):
        issues.append("TRADING_DATE_MISMATCH")

    def _inside_session(value: datetime) -> bool:
        current = value.time()
        return time(9, 30) <= current < time(11, 30) or time(13, 0) <= current < time(15, 0)

    if any(not _inside_session(item) for item in local_times):
        issues.append("OUTSIDE_ASHARE_SESSION")
    if local_times[0].time() != time(9, 30):
        issues.append("SESSION_OPEN_MISSING")
    if local_times[-1].time() != time(14, 59):
        issues.append("SESSION_CLOSE_MISSING")
    for previous, current in pairwise(local_times):
        gap = current - previous
        expected_lunch = previous.time() == time(11, 29) and current.time() == time(13, 0)
        if gap > timedelta(minutes=1) and not expected_lunch:
            warnings.append("INTRADAY_GAP")
            break

    # Do not attempt an aggregate once the session contains another instrument:
    # build_partial_daily_bar deliberately raises for that programming error, while
    # this boundary validator must return an actionable refresh diagnosis instead.
    if "INSTRUMENT_MISMATCH" in issues:
        return MinuteSessionQuality(
            usable=False,
            issues=tuple(dict.fromkeys(issues)),
            warnings=tuple(dict.fromkeys(warnings)),
            minute_count=len(ordered),
        )

    aggregate = build_partial_daily_bar(daily_bar, ordered)
    if aggregate.open != daily_bar.open:
        warnings.append("OPEN_AUCTION_NOT_IN_MINUTE_BARS")
    if aggregate.high > daily_bar.high:
        issues.append("DAILY_HIGH_MISMATCH")
    elif aggregate.high < daily_bar.high:
        warnings.append("AUCTION_HIGH_NOT_IN_MINUTE_BARS")
    if aggregate.low < daily_bar.low:
        issues.append("DAILY_LOW_MISMATCH")
    elif aggregate.low > daily_bar.low:
        warnings.append("AUCTION_LOW_NOT_IN_MINUTE_BARS")
    if aggregate.close != daily_bar.close:
        issues.append("DAILY_CLOSE_MISMATCH")
    volume_tolerance = max(Decimal("1"), abs(daily_bar.volume) * Decimal("0.005"))
    if aggregate.volume > daily_bar.volume + volume_tolerance:
        issues.append("DAILY_VOLUME_MISMATCH")
    elif aggregate.volume < daily_bar.volume - volume_tolerance:
        warnings.append("AUCTION_VOLUME_NOT_IN_MINUTE_BARS")
    return MinuteSessionQuality(
        usable=not issues,
        issues=tuple(dict.fromkeys(issues)),
        warnings=tuple(dict.fromkeys(warnings)),
        minute_count=len(ordered),
    )


def signal_confirmation_points(
    minute_bars: Sequence[StrategyBar], timeframe: MarketTimeframe
) -> tuple[int, ...]:
    """Return raw one-minute indexes at which a 1/5/15-minute bar has closed."""

    width = {
        MarketTimeframe.MINUTE_1: 1,
        MarketTimeframe.MINUTE_5: 5,
        MarketTimeframe.MINUTE_15: 15,
    }.get(timeframe)
    if width is None:
        raise ValueError("unsupported intraday signal timeframe")
    if not minute_bars:
        return ()
    ordered = sorted(minute_bars, key=lambda item: item.timestamp)
    output: list[int] = []
    bucket_count = 0
    previous = None
    for index, bar in enumerate(ordered):
        local = bar.timestamp.astimezone(ASHARE_TIMEZONE).replace(tzinfo=None)
        if previous is not None:
            gap = local - previous
            if gap > timedelta(minutes=1):
                bucket_count = 0
        bucket_count += 1
        if bucket_count == width:
            output.append(index)
            bucket_count = 0
        previous = local
    return tuple(output)


class IntradayDailyStrategyEvaluator:
    """Evaluate daily rules against completed days plus one partial current day."""

    def __init__(
        self,
        *,
        strategy_key: str,
        strategy_version: str,
        rule: PriceVolumeSmaRule | None,
        spec: StrategySpec | None,
    ) -> None:
        if rule is None and spec is None:
            raise ValueError("intraday evaluator requires a supported rule or StrategySpec")
        self._strategy_key = strategy_key
        self._strategy_version = strategy_version
        self._rule = rule
        self._spec = spec
        self._states: dict[UUID, _InstrumentState] = {}

    def evaluate(
        self,
        *,
        completed_daily_bars: Sequence[StrategyBar],
        partial_daily_bar: StrategyBar,
        generated_at: datetime,
    ) -> list[SignalDraft]:
        state = self._states.setdefault(partial_daily_bar.instrument_id, _InstrumentState())
        current_date = partial_daily_bar.timestamp.astimezone(ASHARE_TIMEZONE).date()
        if state.trading_date != current_date:
            state.trading_date = current_date
            state.entry_was_true = False
            state.exit_was_true = False
        bars = [*completed_daily_bars, partial_daily_bar]
        if self._spec is not None:
            entry_true = _evaluate(self._spec.entry, bars)
            exit_true = _evaluate(self._spec.exit, bars)
            quantity = self._spec.quantity
        else:
            assert self._rule is not None
            rule = self._rule
            prior_highs = [item.high for item in completed_daily_bars[-rule.breakout_window :]]
            prior_volumes = [item.volume for item in completed_daily_bars[-rule.volume_window :]]
            entry_true = (
                len(prior_highs) == rule.breakout_window
                and len(prior_volumes) == rule.volume_window
                and partial_daily_bar.close > max(prior_highs)
                and partial_daily_bar.volume
                > sum(prior_volumes, ZERO) / Decimal(rule.volume_window) * rule.volume_multiplier
            )
            closes = [
                item.close for item in completed_daily_bars[-(rule.exit_sma_window - 1) :]
            ] + [partial_daily_bar.close]
            exit_true = len(closes) == rule.exit_sma_window and partial_daily_bar.close < sum(
                closes, ZERO
            ) / Decimal(len(closes))
            quantity = rule.quantity
        side: OrderSide | None = None
        signal_type: SignalType | None = None
        if not state.is_long and entry_true and not state.entry_was_true:
            side = OrderSide.BUY
            signal_type = SignalType.ENTRY
        elif state.is_long and exit_true and not state.exit_was_true:
            side = OrderSide.SELL
            signal_type = SignalType.EXIT
        state.entry_was_true = entry_true
        state.exit_was_true = exit_true
        if side is None or signal_type is None:
            return []
        return [
            SignalDraft(
                strategy_key=self._strategy_key,
                strategy_version=self._strategy_version,
                instrument_id=partial_daily_bar.instrument_id,
                signal_type=signal_type,
                side=side,
                generated_at=generated_at,
                bar_timestamp=partial_daily_bar.timestamp,
                quantity=quantity,
                reference_price=partial_daily_bar.close,
                reason=("分钟级确认: 仅使用此前已完成日线与当前分钟累计形成的临时日线"),
                metadata={
                    "intraday_daily_trigger": True,
                    "no_future_data": True,
                    "signal_price": format(partial_daily_bar.close, "f"),
                },
            )
        ]

    def record_fill(self, instrument_id: UUID, side: OrderSide) -> None:
        """Advance position state only from an actual simulated fill.

        A signal, accepted order, or execution attempt is not a position fact.
        Keeping this transition behind a fill callback prevents rejected or
        unfilled limit-locked orders from creating phantom exits later.
        """

        state = self._states.setdefault(instrument_id, _InstrumentState())
        state.is_long = side is OrderSide.BUY


def safe_prefilter_plan(
    daily_bars: Sequence[StrategyBar], rule: PriceVolumeSmaRule | None
) -> IntradayPrefilterPlan:
    ordered = sorted(daily_bars, key=lambda item: item.timestamp)
    all_dates = frozenset(item.timestamp.astimezone(ASHARE_TIMEZONE).date() for item in ordered)
    if rule is None:
        return IntradayPrefilterPlan(
            candidate_entry_dates=all_dates,
            candidate_exit_dates=all_dates,
            replay_dates=all_dates,
            safe=False,
            reason="策略无法证明某些交易日不可能触发, 已回放全部交易日",
        )
    entry_candidates: set[date] = set()
    exit_candidates: set[date] = set()
    warmup = max(rule.breakout_window, rule.volume_window)
    for index, bar in enumerate(ordered):
        if index < warmup:
            continue
        previous = ordered[:index]
        prior_high = max(item.high for item in previous[-rule.breakout_window :])
        prior_average_volume = sum(
            (item.volume for item in previous[-rule.volume_window :]), ZERO
        ) / Decimal(rule.volume_window)
        # Full-day high and volume are an optimistic envelope.  If either cannot
        # satisfy the rule, no intraday partial bar can satisfy it either.
        price_can_trigger = (
            bar.high >= prior_high if rule.breakout_inclusive else bar.high > prior_high
        )
        volume_threshold = prior_average_volume * rule.volume_multiplier
        volume_can_trigger = (
            bar.volume >= volume_threshold
            if rule.volume_inclusive
            else bar.volume > volume_threshold
        )
        if price_can_trigger and volume_can_trigger:
            entry_candidates.add(bar.timestamp.astimezone(ASHARE_TIMEZONE).date())

    # For a current-inclusive N-day SMA, the intraday exit expression
    #
    #   x < (previous_close_sum + x) / N
    #
    # is exactly equivalent to x being below the average of the preceding
    # N-1 closes.  The authoritative daily low is therefore a safe optimistic
    # envelope: when it cannot cross that fixed threshold, no minute close can.
    exit_window = rule.exit_sma_window
    if exit_window == 1:
        if rule.exit_inclusive:
            exit_candidates.update(all_dates)
    else:
        prior_count = exit_window - 1
        for index, bar in enumerate(ordered):
            if index < prior_count:
                continue
            threshold = sum(
                (item.close for item in ordered[index - prior_count : index]), ZERO
            ) / Decimal(prior_count)
            can_trigger = (
                bar.low <= threshold if rule.exit_inclusive else bar.low < threshold
            )
            if can_trigger:
                exit_candidates.add(bar.timestamp.astimezone(ASHARE_TIMEZONE).date())

    if not entry_candidates:
        return IntradayPrefilterPlan(
            candidate_entry_dates=frozenset(),
            candidate_exit_dates=frozenset(exit_candidates),
            replay_dates=frozenset(),
            safe=True,
            reason="完整日线高点或成交量证明所有交易日均不可能触发买入",
        )
    first = min(entry_candidates)
    replay = frozenset(
        entry_candidates | {item for item in exit_candidates if item >= first}
    )
    return IntradayPrefilterPlan(
        candidate_entry_dates=frozenset(entry_candidates),
        candidate_exit_dates=frozenset(exit_candidates),
        replay_dates=replay,
        safe=True,
        reason="买入候选日使用日线高点与成交量包络; 卖出候选日使用日线低点与固定前序均线阈值",
    )
