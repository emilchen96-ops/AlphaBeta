"""Pure contracts for SC02-D screening data planning and readiness."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.screening import ValidatedScreeningSpec
from alphadesk_domain.strategy import StrategyBar
from alphadesk_domain.values import as_utc, utc_now

SHANGHAI = ZoneInfo("Asia/Shanghai")


class ScreeningPreparationStage(StrEnum):
    PLANNING = "PLANNING"
    CHECKING_COVERAGE = "CHECKING_COVERAGE"
    BACKFILLING_MARKET_DATA = "BACKFILLING_MARKET_DATA"
    BACKFILLING_REFERENCE_DATA = "BACKFILLING_REFERENCE_DATA"
    VERIFYING_DATA = "VERIFYING_DATA"
    PREPARING_FEATURES = "PREPARING_FEATURES"
    SCREENING = "SCREENING"
    COMPLETED = "COMPLETED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"


class ScreeningInstrumentReadiness(StrEnum):
    READY = "READY"
    CURRENTLY_SUSPENDED = "CURRENTLY_SUSPENDED"
    STALE_DATA = "STALE_DATA"
    DATA_GAP = "DATA_GAP"
    CALENDAR_MISMATCH = "CALENDAR_MISMATCH"
    DELISTED = "DELISTED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    REFERENCE_DATA_MISSING = "REFERENCE_DATA_MISSING"
    QUALITY_FAILED = "QUALITY_FAILED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True, kw_only=True)
class DataRequirementPlan:
    universe_count: int
    earliest_required_date: date
    earliest_fetch_date: date
    latest_required_date: date
    required_open_sessions: int
    minimum_rule_sessions: int
    required_timeframe: MarketTimeframe
    price_adjustment_mode: PriceAdjustmentMode
    required_fields: tuple[str, ...]
    required_reference_data: tuple[str, ...]
    required_features: tuple[str, ...]
    provider_plan: tuple[str, ...]
    estimated_missing_instruments: int
    warmup_buffer: int
    maximum_extension_sessions: int
    market_sessions: tuple[date, ...]

    def response_dict(self) -> dict[str, object]:
        return {
            "universe_count": self.universe_count,
            "earliest_required_date": self.earliest_required_date.isoformat(),
            "earliest_fetch_date": self.earliest_fetch_date.isoformat(),
            "latest_required_date": self.latest_required_date.isoformat(),
            "required_open_sessions": self.required_open_sessions,
            "minimum_rule_sessions": self.minimum_rule_sessions,
            "required_timeframe": self.required_timeframe.value,
            "price_adjustment_mode": self.price_adjustment_mode.value,
            "required_fields": list(self.required_fields),
            "required_reference_data": list(self.required_reference_data),
            "required_features": list(self.required_features),
            "provider_plan": list(self.provider_plan),
            "estimated_missing_instruments": self.estimated_missing_instruments,
            "warmup_buffer": self.warmup_buffer,
            "maximum_extension_sessions": self.maximum_extension_sessions,
            "market_sessions": [item.isoformat() for item in self.market_sessions],
        }


class ScreeningDataRequirementPlanner:
    """Derive the minimum point-in-time data contract from a validated spec."""

    _FEATURES: Mapping[str, tuple[str, ...]] = {
        "LIMIT_UP_PULLBACK": (
            "涨停事件",
            "涨停日期",
            "涨停前收盘价",
            "涨停日成交量",
            "距离锚点",
            "成交量比例",
        ),
        "BOTTOM_VOLUME_EXPANSION": (
            "滚动最高价",
            "滚动最低价",
            "区间位置",
            "平均成交量",
            "成交量倍数",
            "阳线状态",
        ),
    }

    def __init__(
        self,
        *,
        warmup_buffer: int = 10,
        maximum_extension_sessions: int = 60,
        provider_code: str = "MINIQMT",
    ) -> None:
        if warmup_buffer < 0:
            raise ValueError("warmup_buffer must be non-negative")
        if maximum_extension_sessions < 0:
            raise ValueError("maximum_extension_sessions must be non-negative")
        self._warmup_buffer = warmup_buffer
        self._maximum_extension_sessions = maximum_extension_sessions
        self._provider_code = provider_code.strip().upper()

    def plan(
        self,
        validated: ValidatedScreeningSpec,
        *,
        universe_count: int,
        open_sessions: Sequence[date],
        estimated_missing_instruments: int = 0,
    ) -> DataRequirementPlan:
        required_sessions = validated.required_history_bars + self._warmup_buffer
        ordered = tuple(sorted(set(open_sessions)))
        eligible = tuple(item for item in ordered if item <= validated.spec.as_of_date)
        if len(eligible) < required_sessions:
            raise ValueError("交易日历不足以覆盖规则窗口和预热缓冲")
        market_sessions = eligible[-required_sessions:]
        fetch_sessions = min(
            len(eligible),
            required_sessions + self._maximum_extension_sessions,
        )
        condition_keys = tuple(item.definition.condition_key for item in validated.conditions)
        fields = sorted(
            {
                field_name
                for condition in validated.conditions
                for field_name in condition.definition.required_fields
            }
            | {"previous_close"}
        )
        references = {"交易日历", "上市退市生命周期", "停复牌状态"}
        if {"LIMIT_UP_PULLBACK", "RECENT_LIMIT_UP_EVENT"} & set(condition_keys):
            references.add("涨跌停价格语义")
        if validated.spec.price_adjustment_mode is PriceAdjustmentMode.QFQ:
            references.add("复权因子")
        features = tuple(
            dict.fromkeys(
                feature
                for key in condition_keys
                for feature in self._FEATURES.get(key, (f"{key}条件特征",))
            )
        )
        provider_plan = (
            f"{self._provider_code}只读历史日线",
            "AlphaDesk本地交易日历与生命周期",
            "缺口按股票和连续交易日区间增量请求",
        )
        return DataRequirementPlan(
            universe_count=universe_count,
            earliest_required_date=market_sessions[0],
            earliest_fetch_date=eligible[-fetch_sessions],
            latest_required_date=validated.spec.as_of_date,
            required_open_sessions=required_sessions,
            minimum_rule_sessions=validated.required_history_bars,
            required_timeframe=validated.spec.timeframe,
            price_adjustment_mode=validated.spec.price_adjustment_mode,
            required_fields=tuple(fields),
            required_reference_data=tuple(sorted(references)),
            required_features=features,
            provider_plan=provider_plan,
            estimated_missing_instruments=max(0, estimated_missing_instruments),
            warmup_buffer=self._warmup_buffer,
            maximum_extension_sessions=self._maximum_extension_sessions,
            market_sessions=market_sessions,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class InstrumentDataGap:
    instrument_id: UUID
    readiness: ScreeningInstrumentReadiness
    available_bars: int
    required_bars: int
    missing_sessions: tuple[date, ...] = ()
    reason_code: str | None = None
    reason: str | None = None

    @property
    def needs_backfill(self) -> bool:
        return bool(self.missing_sessions) and self.readiness in {
            ScreeningInstrumentReadiness.DATA_GAP,
        }

    @property
    def calculation_ready(self) -> bool:
        return self.readiness in {
            ScreeningInstrumentReadiness.READY,
            ScreeningInstrumentReadiness.CURRENTLY_SUSPENDED,
        }


class ScreeningDataGapService:
    """Assess exact open-session gaps and deterministic OHLC quality."""

    def assess(
        self,
        *,
        instruments: Sequence[Instrument],
        bars_by_instrument: Mapping[UUID, Sequence[StrategyBar]],
        required_sessions: Sequence[date],
        minimum_rule_sessions: int,
        available_sessions: Sequence[date] | None = None,
        suspended_sessions: set[tuple[UUID, date]] | None = None,
        currently_suspended_ids: set[UUID] | None = None,
        as_of_date: date | None = None,
        max_stale_sessions: int = 20,
    ) -> tuple[InstrumentDataGap, ...]:
        suspended = suspended_sessions or set()
        ordered_sessions = tuple(sorted(set(required_sessions)))
        extended_sessions = tuple(
            sorted(set(available_sessions if available_sessions is not None else required_sessions))
        )
        current_suspended = currently_suspended_ids or set()
        cutoff = as_of_date or ordered_sessions[-1]
        values: list[InstrumentDataGap] = []
        for instrument in instruments:
            if instrument.delisted_at is not None and instrument.delisted_at <= cutoff:
                values.append(
                    InstrumentDataGap(
                        instrument_id=instrument.id,
                        readiness=ScreeningInstrumentReadiness.DELISTED,
                        available_bars=len(bars_by_instrument.get(instrument.id, ())),
                        required_bars=len(ordered_sessions),
                        reason_code="DELISTED",
                        reason="股票在筛选截止日前已经退市",
                    )
                )
                continue
            lifecycle_sessions = tuple(
                item
                for item in extended_sessions
                if (instrument.listed_at is None or item >= instrument.listed_at)
                and (instrument.delisted_at is None or item < instrument.delisted_at)
            )
            bars = tuple(
                sorted(
                    bars_by_instrument.get(instrument.id, ()),
                    key=lambda item: item.timestamp,
                )
            )
            if not bars and (
                instrument.listed_at is None or instrument.listed_at <= date(1971, 1, 1)
            ):
                values.append(
                    InstrumentDataGap(
                        instrument_id=instrument.id,
                        readiness=ScreeningInstrumentReadiness.REFERENCE_DATA_MISSING,
                        available_bars=0,
                        required_bars=len(ordered_sessions),
                        reason_code="LISTING_DATE_NOT_AVAILABLE",
                        reason="MiniQMT尚无首根日线。上市日期资料也不可用",
                    )
                )
                continue
            if len(lifecycle_sessions) < minimum_rule_sessions:
                values.append(
                    InstrumentDataGap(
                        instrument_id=instrument.id,
                        readiness=ScreeningInstrumentReadiness.NOT_APPLICABLE,
                        available_bars=len(bars),
                        required_bars=len(ordered_sessions),
                        reason_code="LISTING_HISTORY_TOO_SHORT",
                        reason="上市历史不足。暂不适用当前规则",
                    )
                )
                continue
            dates = [item.timestamp.astimezone(SHANGHAI).date() for item in bars]
            if len(dates) != len(set(dates)):
                values.append(
                    InstrumentDataGap(
                        instrument_id=instrument.id,
                        readiness=ScreeningInstrumentReadiness.QUALITY_FAILED,
                        available_bars=len(bars),
                        required_bars=len(lifecycle_sessions),
                        reason_code="DUPLICATE_DAILY_BAR",
                        reason="同一交易日存在重复日线",
                    )
                )
                continue
            if any(not self._valid_bar(item) for item in bars):
                values.append(
                    InstrumentDataGap(
                        instrument_id=instrument.id,
                        readiness=ScreeningInstrumentReadiness.QUALITY_FAILED,
                        available_bars=len(bars),
                        required_bars=len(lifecycle_sessions),
                        reason_code="INVALID_OHLC",
                        reason="日线开高低收或成交量不合法",
                    )
                )
                continue
            available = set(dates)
            # Individual technical indicators consume real bars. Suspended
            # sessions are skipped and the target is extended backwards, while
            # `ordered_sessions` remains the shared market-event window.
            effective_target: list[date] = []
            for session in reversed(lifecycle_sessions):
                if (instrument.id, session) in suspended:
                    continue
                effective_target.append(session)
                if len(effective_target) >= len(ordered_sessions):
                    break
            effective_target.reverse()
            missing = tuple(item for item in effective_target if item not in available)
            latest_bar_date = max(dates, default=None)
            stale_distance = len(
                [
                    item
                    for item in ordered_sessions
                    if latest_bar_date is None or item > latest_bar_date
                ]
            )
            if missing:
                readiness = ScreeningInstrumentReadiness.DATA_GAP
                reason_code = "OPEN_SESSION_DATA_GAP"
                reason = "正常交易日确实缺少历史日线"
            elif stale_distance > max_stale_sessions:
                readiness = ScreeningInstrumentReadiness.STALE_DATA
                reason_code = "STALE_DATA"
                reason = "最近有效行情距离筛选日过远"
            elif instrument.id in current_suspended:
                readiness = ScreeningInstrumentReadiness.CURRENTLY_SUSPENDED
                reason_code = "CURRENTLY_SUSPENDED"
                reason = "筛选截止日当前停牌。仅完成研究计算。不作为可执行结果"
            else:
                readiness = ScreeningInstrumentReadiness.READY
                reason_code = reason = None
            values.append(
                InstrumentDataGap(
                    instrument_id=instrument.id,
                    readiness=readiness,
                    available_bars=len(bars),
                    required_bars=min(len(lifecycle_sessions), len(ordered_sessions)),
                    missing_sessions=missing,
                    reason_code=reason_code,
                    reason=reason,
                )
            )
        return tuple(values)

    @staticmethod
    def contiguous_ranges(
        missing_sessions: Sequence[date], ordered_sessions: Sequence[date]
    ) -> tuple[tuple[date, date], ...]:
        missing = set(missing_sessions)
        ranges: list[tuple[date, date]] = []
        start: date | None = None
        end: date | None = None
        for session in sorted(set(ordered_sessions)):
            if session in missing:
                start = session if start is None else start
                end = session
            elif start is not None and end is not None:
                ranges.append((start, end))
                start = end = None
        if start is not None and end is not None:
            ranges.append((start, end))
        return tuple(ranges)

    @staticmethod
    def _valid_bar(bar: StrategyBar) -> bool:
        return (
            bar.open > 0
            and bar.high > 0
            and bar.low > 0
            and bar.close > 0
            and bar.volume >= 0
            and bar.low <= min(bar.open, bar.close)
            and bar.high >= max(bar.open, bar.close)
            and bar.low <= bar.high
        )


@dataclass(slots=True, kw_only=True)
class ScreeningPreparationRun:
    scan_run_id: UUID
    stage: ScreeningPreparationStage = ScreeningPreparationStage.PLANNING
    current_action: str = "正在分析数据需求"
    original_ready_count: int = 0
    ready_count: int = 0
    downloading_count: int = 0
    insufficient_count: int = 0
    indeterminate_count: int = 0
    provider_failed_count: int = 0
    quality_failed_count: int = 0
    not_applicable_count: int = 0
    listing_history_short_count: int = 0
    currently_suspended_count: int = 0
    stale_data_count: int = 0
    data_gap_count: int = 0
    calendar_mismatch_count: int = 0
    delisted_count: int = 0
    backfilled_instrument_count: int = 0
    backfilled_bar_count: int = 0
    reference_backfilled_count: int = 0
    feature_prepared_count: int = 0
    attempt: int = 1
    started_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def response_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "current_action": self.current_action,
            "original_ready_count": self.original_ready_count,
            "ready_count": self.ready_count,
            "downloading_count": self.downloading_count,
            "insufficient_count": self.insufficient_count,
            "indeterminate_count": self.indeterminate_count,
            "provider_failed_count": self.provider_failed_count,
            "quality_failed_count": self.quality_failed_count,
            "not_applicable_count": self.not_applicable_count,
            "listing_history_short_count": self.listing_history_short_count,
            "currently_suspended_count": self.currently_suspended_count,
            "stale_data_count": self.stale_data_count,
            "data_gap_count": self.data_gap_count,
            "calendar_mismatch_count": self.calendar_mismatch_count,
            "delisted_count": self.delisted_count,
            "backfilled_instrument_count": self.backfilled_instrument_count,
            "backfilled_bar_count": self.backfilled_bar_count,
            "reference_backfilled_count": self.reference_backfilled_count,
            "feature_prepared_count": self.feature_prepared_count,
            "attempt": self.attempt,
            "started_at": as_utc(self.started_at, "started_at").isoformat(),
            "updated_at": as_utc(self.updated_at, "updated_at").isoformat(),
        }
