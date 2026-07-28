from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Self
from uuid import UUID, uuid4

import pytest

from alphadesk_api.application.screenings import (
    ScreeningDataPreparationService,
    ScreeningOrchestrationService,
    ScreeningPreparationOutcome,
    ScreeningRunService,
)
from alphadesk_domain.entities import Instrument
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.market_reference import PriceAdjustmentMode
from alphadesk_domain.scanners import (
    ScanMemberStatus,
    ScanRun,
    ScanRunMember,
    ScanRunStatus,
)
from alphadesk_domain.screening import (
    ConditionOutcome,
    RuleBasedScreeningEngine,
    ScreeningCondition,
    ScreeningFeatureStore,
    ScreeningSpec,
    UniverseSpec,
    builtin_condition_catalog,
)
from alphadesk_domain.screening_data_preparation import (
    InstrumentDataGap,
    ScreeningDataGapService,
    ScreeningDataRequirementPlanner,
    ScreeningInstrumentReadiness,
    ScreeningPreparationRun,
    ScreeningPreparationStage,
)
from alphadesk_domain.strategy import StrategyBar

AS_OF = date(2026, 7, 22)


def sessions(count: int = 120) -> list[date]:
    values: list[date] = []
    current = AS_OF
    while len(values) < count:
        if current.weekday() < 5:
            values.append(current)
        current -= timedelta(days=1)
    return sorted(values)


def instrument(
    *,
    symbol: str = "600001",
    name: str = "测试股票",
    listed_at: date | None = date(2020, 1, 1),
    delisted_at: date | None = None,
    metadata: dict[str, object] | None = None,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        exchange="SSE",
        market="CN_A",
        name=name,
        asset_type="STOCK",
        currency="CNY",
        lot_size=Decimal("100"),
        price_tick=Decimal("0.01"),
        timezone="Asia/Shanghai",
        listed_at=listed_at,
        delisted_at=delisted_at,
        metadata=metadata or {},
    )


def bar(item: Instrument, session: date, *, close: str = "10", volume: str = "100") -> StrategyBar:
    value = Decimal(close)
    return StrategyBar(
        instrument_id=item.id,
        symbol=item.symbol,
        exchange=item.exchange,
        timeframe=MarketTimeframe.DAY_1,
        timestamp=datetime.combine(session, datetime.min.time(), UTC) + timedelta(hours=7),
        open=value,
        high=value + Decimal("1"),
        low=value - Decimal("1"),
        close=value,
        volume=Decimal(volume),
        amount=value * Decimal(volume),
    )


def spec(condition_key: str) -> ScreeningSpec:
    return ScreeningSpec(
        schema_version=1,
        name="自动准备测试",
        origin="API",
        universe_spec=UniverseSpec(),
        as_of_date=AS_OF,
        timeframe=MarketTimeframe.DAY_1,
        conditions=(ScreeningCondition(condition_key=condition_key),),
        price_adjustment_mode=PriceAdjustmentMode.RAW,
    )


def assess(
    item: Instrument,
    values: list[StrategyBar],
    required: list[date],
    *,
    minimum: int = 3,
    suspended: set[tuple[UUID, date]] | None = None,
) -> InstrumentDataGap:
    return ScreeningDataGapService().assess(
        instruments=[item],
        bars_by_instrument={item.id: values},
        required_sessions=required,
        minimum_rule_sessions=minimum,
        suspended_sessions=suspended,
    )[0]


def test_01_limit_up_pullback_plan_contains_required_reference_facts() -> None:
    catalog = builtin_condition_catalog()
    plan = ScreeningDataRequirementPlanner(warmup_buffer=7).plan(
        spec("LIMIT_UP_PULLBACK").validate(catalog),
        universe_count=5_531,
        open_sessions=sessions(),
    )
    assert plan.universe_count == 5_531
    assert plan.warmup_buffer == 7
    assert "previous_close" in plan.required_fields
    assert "volume" in plan.required_fields
    assert "涨跌停价格语义" in plan.required_reference_data
    assert "涨停事件" in plan.required_features


def test_02_bottom_volume_plan_contains_only_needed_features() -> None:
    catalog = builtin_condition_catalog()
    plan = ScreeningDataRequirementPlanner(warmup_buffer=10).plan(
        spec("BOTTOM_VOLUME_EXPANSION").validate(catalog),
        universe_count=5_500,
        open_sessions=sessions(),
    )
    assert {"open", "high", "low", "close", "volume"}.issubset(plan.required_fields)
    assert "滚动最高价" in plan.required_features
    assert "平均成交量" in plan.required_features
    assert "涨停事件" not in plan.required_features


def test_03_plan_uses_open_sessions_plus_configured_warmup() -> None:
    catalog = builtin_condition_catalog()
    validated = spec("BOTTOM_VOLUME_EXPANSION").validate(catalog)
    plan = ScreeningDataRequirementPlanner(warmup_buffer=11).plan(
        validated,
        universe_count=1,
        open_sessions=sessions(),
    )
    assert plan.required_open_sessions == validated.required_history_bars + 11
    assert plan.earliest_required_date in sessions()


def test_04_complete_local_window_requires_no_download() -> None:
    item = instrument()
    required = sessions(10)
    gap = assess(item, [bar(item, value) for value in required], required)
    assert gap.readiness is ScreeningInstrumentReadiness.READY
    assert gap.needs_backfill is False


def test_05_only_missing_front_segment_is_requested() -> None:
    item = instrument()
    required = sessions(10)
    gap = assess(item, [bar(item, value) for value in required[3:]], required)
    assert gap.missing_sessions == tuple(required[:3])
    assert ScreeningDataGapService.contiguous_ranges(gap.missing_sessions, required) == (
        (required[0], required[2]),
    )


def test_06_only_missing_tail_segment_is_requested() -> None:
    item = instrument()
    required = sessions(10)
    gap = assess(item, [bar(item, value) for value in required[:-2]], required)
    assert gap.missing_sessions == tuple(required[-2:])
    assert ScreeningDataGapService.contiguous_ranges(gap.missing_sessions, required) == (
        (required[-2], required[-1]),
    )


def test_07_middle_gaps_are_split_into_exact_ranges() -> None:
    item = instrument()
    required = sessions(10)
    missing = {required[2], required[3], required[7]}
    gap = assess(
        item,
        [bar(item, value) for value in required if value not in missing],
        required,
    )
    assert ScreeningDataGapService.contiguous_ranges(gap.missing_sessions, required) == (
        (required[2], required[3]),
        (required[7], required[7]),
    )


def test_08_repeated_gap_analysis_is_idempotent() -> None:
    item = instrument()
    required = sessions(8)
    values = [bar(item, value) for value in required[1:]]
    first = assess(item, values, required)
    second = assess(item, values, required)
    assert first == second


def test_09_provider_partial_failure_becomes_per_instrument_status() -> None:
    item = instrument()
    required = sessions(5)
    gap = assess(item, [bar(item, value) for value in required[:-1]], required)
    finalized = ScreeningDataPreparationService._finalize_gap(
        gap,
        backfill_attempted=True,
    )
    assert finalized.readiness is ScreeningInstrumentReadiness.PROVIDER_FAILED
    assert finalized.reason_code == "SCREENING_DATA_STILL_NOT_READY"


def test_10_single_bad_stock_does_not_change_ready_peer() -> None:
    good = instrument(symbol="600001")
    bad = instrument(symbol="600002")
    required = sessions(5)
    duplicate = bar(bad, required[0])
    values = ScreeningDataGapService().assess(
        instruments=[good, bad],
        bars_by_instrument={
            good.id: [bar(good, value) for value in required],
            bad.id: [duplicate, duplicate, *[bar(bad, value) for value in required[1:]]],
        },
        required_sessions=required,
        minimum_rule_sessions=3,
    )
    assert values[0].readiness is ScreeningInstrumentReadiness.READY
    assert values[1].readiness is ScreeningInstrumentReadiness.QUALITY_FAILED


def test_11_suspended_open_session_is_not_treated_as_market_data_gap() -> None:
    item = instrument()
    required = sessions(5)
    suspended_day = required[2]
    gap = assess(
        item,
        [bar(item, value) for value in required if value != suspended_day],
        required,
        suspended={(item.id, suspended_day)},
    )
    assert gap.readiness is ScreeningInstrumentReadiness.READY


def test_12_new_listing_with_short_history_is_not_applicable() -> None:
    required = sessions(10)
    item = instrument(listed_at=required[-2])
    gap = assess(
        item,
        [bar(item, value) for value in required[-2:]],
        required,
        minimum=5,
    )
    assert gap.readiness is ScreeningInstrumentReadiness.NOT_APPLICABLE
    assert gap.reason_code == "LISTING_HISTORY_TOO_SHORT"


def test_13_delisted_sessions_are_excluded_from_required_window() -> None:
    required = sessions(8)
    item = instrument(delisted_at=required[-2])
    lifecycle = [value for value in required if value < required[-2]]
    gap = assess(item, [bar(item, value) for value in lifecycle], required)
    assert gap.readiness is ScreeningInstrumentReadiness.READY


def test_14_missing_reliable_limit_price_is_indeterminate_not_fabricated() -> None:
    item = instrument(name="ST测试", metadata={"is_st": True})
    values = [bar(item, value) for value in sessions(40)]
    outcome = RuleBasedScreeningEngine(builtin_condition_catalog()).evaluate_instrument(
        spec("LIMIT_UP_PULLBACK"),
        item,
        values,
    )
    assert outcome.outcome is ConditionOutcome.INDETERMINATE
    assert outcome.reason_code == "LIMIT_PRICE_NOT_AVAILABLE"


def test_15_reference_missing_has_distinct_readiness() -> None:
    item = instrument()
    gap = InstrumentDataGap(
        instrument_id=item.id,
        readiness=ScreeningInstrumentReadiness.REFERENCE_DATA_MISSING,
        available_bars=70,
        required_bars=70,
        reason_code="SCREENING_REFERENCE_DATA_MISSING",
        reason="缺少复权因子",
    )
    assert gap.readiness is ScreeningInstrumentReadiness.REFERENCE_DATA_MISSING
    assert gap.needs_backfill is False


def test_16_backfill_then_complete_window_becomes_ready() -> None:
    item = instrument()
    required = sessions(6)
    before = assess(item, [bar(item, value) for value in required[:-1]], required)
    after = assess(item, [bar(item, value) for value in required], required)
    assert before.readiness is ScreeningInstrumentReadiness.INSUFFICIENT_HISTORY
    assert after.readiness is ScreeningInstrumentReadiness.READY


def test_17_feature_store_refreshes_when_source_bars_change() -> None:
    item = instrument()
    required = sessions(70)
    store = ScreeningFeatureStore()
    first = store.get(item, [bar(item, value) for value in required[:-1]], required[-1])
    second = store.get(item, [bar(item, value) for value in required], required[-1])
    assert len(second.bars) == len(first.bars) + 1
    assert second is not first


def test_17b_feature_preparation_only_builds_current_rule_features() -> None:
    item = instrument()
    required = sessions(70)
    store = ScreeningFeatureStore(required_condition_keys=("LIMIT_UP_PULLBACK",))

    snapshot = store.get(item, [bar(item, value) for value in required], required[-1])

    assert snapshot.rolling_high_60 is None
    assert snapshot.average_volume_20 is None
    assert snapshot.bullish_candle is None


def test_18_orchestration_stage_transitions_are_durable_domain_states() -> None:
    run = scan_run()
    now = datetime.now(UTC)
    for index, stage in enumerate(
        (
            ScanRunStatus.PLANNING,
            ScanRunStatus.CHECKING_COVERAGE,
            ScanRunStatus.BACKFILLING_MARKET_DATA,
            ScanRunStatus.BACKFILLING_REFERENCE_DATA,
            ScanRunStatus.VERIFYING_DATA,
            ScanRunStatus.PREPARING_FEATURES,
            ScanRunStatus.SCREENING,
        ),
        start=1,
    ):
        run.mark_phase(stage, now, progress_percent=index * 10)
    run.mark_completed(now + timedelta(milliseconds=1_234), 1, 0)
    preparation = ScreeningPreparationRun(
        scan_run_id=run.id,
        stage=ScreeningPreparationStage.COMPLETED,
        current_action="全市场选股已完成",
    )
    assert run.status is ScanRunStatus.COMPLETED
    assert run.progress_percent == 100
    assert run.elapsed_ms == 1_234
    assert preparation.response_dict()["stage"] == "COMPLETED"


def test_19_cancel_stops_preparation_before_screening() -> None:
    run = scan_run()
    now = datetime.now(UTC)
    run.mark_phase(ScanRunStatus.BACKFILLING_MARKET_DATA, now, progress_percent=30)
    run.request_cancel(now)
    run.mark_canceled(now)
    assert run.cancel_requested is True
    assert run.status is ScanRunStatus.CANCELED


@dataclass
class RetryStore:
    run: ScanRun
    members: list[ScanRunMember]
    added: list[ScanRun] = field(default_factory=list)


class RetryRunRepository:
    def __init__(self, store: RetryStore) -> None:
        self.store = store

    async def get_by_id(self, _: UUID) -> ScanRun:
        return deepcopy(self.store.run)

    async def get_by_idempotency_key(self, key: str) -> ScanRun | None:
        return next((item for item in self.store.added if item.idempotency_key == key), None)

    async def add(self, value: ScanRun) -> None:
        self.store.added.append(deepcopy(value))


class RetryMemberRepository:
    def __init__(self, store: RetryStore) -> None:
        self.store = store

    async def list_by_run(self, _: UUID) -> list[ScanRunMember]:
        return deepcopy(self.store.members)


class RetryCalendarRepository:
    async def list(self, **_: object) -> list[object]:
        return [SimpleNamespace(is_open=True)]


class RetryUnitOfWork:
    def __init__(self, store: RetryStore) -> None:
        self.scan_runs = RetryRunRepository(store)
        self.scan_run_members = RetryMemberRepository(store)
        self.trading_calendar = RetryCalendarRepository()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_20_retry_failed_stocks_creates_scoped_new_run() -> None:
    failed = instrument(symbol="600010")
    ready = instrument(symbol="600011")
    original = scan_run()
    original.screening_spec = spec("BOTTOM_VOLUME_EXPANSION").snapshot(builtin_condition_catalog())
    store = RetryStore(
        original,
        [
            member(original, failed, ScanMemberStatus.PROVIDER_FAILED),
            member(original, ready, ScanMemberStatus.MATCHED),
        ],
    )
    service = ScreeningRunService(
        lambda: RetryUnitOfWork(store),
        builtin_condition_catalog(),
    )
    outcome = await service.retry_failed(
        original.id,
        correlation_id=uuid4(),
        idempotency_key="retry-once",
    )
    options = outcome.run.execution_stats["preparation_options"]
    assert options["retry_instrument_ids"] == [str(failed.id)]
    assert len(store.added) == 1


@dataclass
class PreparedPipeline:
    feature_store: ScreeningFeatureStore
    prepared_run_id: UUID | None = None

    async def prepare(
        self,
        run_id: UUID,
        _: object,
    ) -> ScreeningPreparationOutcome:
        self.prepared_run_id = run_id
        return ScreeningPreparationOutcome(
            ready_for_screening=True,
            feature_store=self.feature_store,
        )


@dataclass
class ExistingScreeningProcessor:
    processed_run_id: UUID | None = None
    received_feature_store: ScreeningFeatureStore | None = None

    async def process(
        self,
        run_id: UUID,
        *,
        feature_store: ScreeningFeatureStore | None = None,
    ) -> None:
        self.processed_run_id = run_id
        self.received_feature_store = feature_store

    async def fail(self, _: UUID, __: Exception) -> None:
        return None


@pytest.mark.asyncio
async def test_21_preparation_hands_ready_features_to_existing_screening_engine() -> None:
    run_id = uuid4()
    feature_store = ScreeningFeatureStore()
    preparation = PreparedPipeline(feature_store)
    screening = ExistingScreeningProcessor()
    orchestration = ScreeningOrchestrationService(preparation, screening)  # type: ignore[arg-type]

    async def enqueue(_: dict[str, object]) -> None:
        return None

    await orchestration.process(run_id, enqueue)

    assert preparation.prepared_run_id == run_id
    assert screening.processed_run_id == run_id
    assert screening.received_feature_store is feature_store


def scan_run() -> ScanRun:
    return ScanRun(
        scanner_key="BOTTOM_VOLUME_EXPANSION",
        scanner_version="1.0.0",
        parameters={},
        screening_spec=spec("BOTTOM_VOLUME_EXPANSION").snapshot(builtin_condition_catalog()),
        universe_type="ALL_ACTIVE_A_SHARES",
        instrument_ids=(),
        timeframe=MarketTimeframe.DAY_1,
        as_of=datetime(2026, 7, 22, 7, tzinfo=UTC),
        status=ScanRunStatus.QUEUED,
        idempotency_key=f"test:{uuid4()}",
        request_fingerprint="a" * 64,
        correlation_id=uuid4(),
    )


def member(
    run: ScanRun,
    item: Instrument,
    status: ScanMemberStatus,
) -> ScanRunMember:
    return ScanRunMember(
        scan_run_id=run.id,
        instrument_id=item.id,
        symbol=item.symbol,
        exchange=item.exchange,
        instrument_name=item.name,
        status=status,
    )
