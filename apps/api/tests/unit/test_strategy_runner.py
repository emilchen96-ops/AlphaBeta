from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Self, cast
from uuid import UUID, uuid4

import pytest

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.strategy_runner import (
    StrategyRunner,
    StrategyRunQueryService,
    StrategyRunRequest,
)
from alphadesk_domain.entities import Signal
from alphadesk_domain.enums import MarketTimeframe, OrderSide, SignalType
from alphadesk_domain.strategy import (
    SignalDraft,
    StrategyBar,
    StrategyContext,
    StrategyEnvironment,
    StrategyMetadata,
    StrategyRegistry,
)
from alphadesk_domain.strategy_runs import StrategyRun, StrategyRunStatus, stored_parameters

NOW = datetime(2026, 1, 2, 1, tzinfo=UTC)
INSTRUMENT = UUID("11111111-1111-1111-1111-111111111111")


def bar(minutes: int = 0) -> StrategyBar:
    return StrategyBar(
        instrument_id=INSTRUMENT,
        symbol="000001",
        exchange="SZSE",
        timeframe=MarketTimeframe.MINUTE_1,
        timestamp=NOW + timedelta(minutes=minutes),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("100"),
    )


class RecordingStrategy:
    metadata = StrategyMetadata(
        strategy_key="recording_strategy",
        display_name="Recording",
        description="Test-only recording strategy",
        version="1.2.3",
        supported_timeframes=(MarketTimeframe.MINUTE_1,),
    )

    def __init__(self, parameters: object, *, failure: str | None = None) -> None:
        del parameters
        self.failure = failure
        self.times: list[datetime] = []

    def initialize(self, context: StrategyContext) -> None:
        self.times.append(context.current_time)
        if self.failure == "initialize":
            raise RuntimeError("secret=do-not-persist")

    def on_bar(self, context: StrategyContext, item: StrategyBar) -> list[SignalDraft]:
        self.times.append(context.current_time)
        if self.failure == "on_bar":
            raise RuntimeError("secret=do-not-persist")
        draft = SignalDraft(
            strategy_key=self.metadata.strategy_key,
            strategy_version=self.metadata.version,
            instrument_id=item.instrument_id,
            signal_type=SignalType.ENTRY,
            side=OrderSide.BUY,
            generated_at=context.current_time,
            bar_timestamp=item.timestamp,
            quantity=Decimal("100"),
            reference_price=item.close,
            confidence=Decimal("0.8"),
            reason="test signal",
            metadata={"source": "unit"},
        )
        if self.failure == "invalid_draft":
            draft = replace(draft, instrument_id=uuid4())
        return [draft]

    def finalize(self, context: StrategyContext) -> None:
        self.times.append(context.current_time)
        if self.failure == "finalize":
            raise RuntimeError("secret=do-not-persist")


@dataclass
class Store:
    runs: dict[UUID, StrategyRun]
    signals: list[Signal]
    bars: list[StrategyBar]


class RunRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def add(self, entity: StrategyRun) -> None:
        self.store.runs[entity.id] = deepcopy(entity)

    async def update(self, entity: StrategyRun) -> None:
        self.store.runs[entity.id] = deepcopy(entity)

    async def get_by_id(self, entity_id: UUID) -> StrategyRun | None:
        return deepcopy(self.store.runs.get(entity_id))

    async def get_by_idempotency_key(self, key: str) -> StrategyRun | None:
        return next(
            (deepcopy(item) for item in self.store.runs.values() if item.idempotency_key == key),
            None,
        )

    async def list(
        self, *, offset: int, limit: int, **filters: object
    ) -> tuple[list[StrategyRun], int]:
        del filters
        values = list(self.store.runs.values())
        return deepcopy(values[offset : offset + limit]), len(values)


class SignalRepo:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def append_many(self, entities: list[Signal]) -> None:
        self.store.signals.extend(deepcopy(entities))

    async def list_by_run(
        self, run_id: UUID, offset: int, limit: int, signal_type: str | None = None
    ) -> tuple[list[Signal], int]:
        values = [item for item in self.store.signals if item.strategy_run_id == run_id]
        if signal_type is not None:
            values = [item for item in values if item.signal_type.value == signal_type]
        values.sort(key=lambda item: item.sequence_number or 0)
        return deepcopy(values[offset : offset + limit]), len(values)

    async def list_filtered(
        self, *, offset: int, limit: int, **filters: object
    ) -> tuple[list[Signal], int]:
        values = self.store.signals
        for field in ("strategy_run_id", "strategy_key", "instrument_id", "signal_type"):
            value = filters.get(field)
            if value is not None:
                values = [item for item in values if _filter_value(item, field) == value]
        return deepcopy(values[offset : offset + limit]), len(values)


def _filter_value(item: Signal, field: str) -> object:
    value = getattr(item, field)
    return value.value if field == "signal_type" else value


class Bars:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def list_bars(self, **kwargs: object) -> list[StrategyBar]:
        return deepcopy(self.store.bars)


class FakeUow:
    def __init__(self, shared: Store) -> None:
        self.shared = shared
        self.local = deepcopy(shared)
        self.committed = False

    async def __aenter__(self) -> Self:
        self.strategy_runs = RunRepo(self.local)
        self.signals = SignalRepo(self.local)
        self.historical_bars = Bars(self.local)
        self.strategies = SimpleNamespace(get_by_business_key=self._no_strategy)
        self.instruments = SimpleNamespace(get_many=self._no_instruments)
        return self

    async def _no_strategy(self, key: str) -> None:
        return None

    async def _no_instruments(self, ids: list[UUID]) -> list[object]:
        del ids
        return []

    async def commit(self) -> None:
        self.shared.runs = self.local.runs
        self.shared.signals = self.local.signals
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def __aexit__(self, *args: object) -> None:
        pass


def setup_runner(
    *, bars: list[StrategyBar] | None = None, failure: str | None = None
) -> tuple[StrategyRunner, Store, list[RecordingStrategy]]:
    store = Store({}, [], list(bars or []))
    instances: list[RecordingStrategy] = []
    registry = StrategyRegistry()

    def factory(parameters: object) -> RecordingStrategy:
        instance = RecordingStrategy(parameters, failure=failure)
        instances.append(instance)
        return instance

    registry.register(RecordingStrategy.metadata, (), factory)
    uow_factory = cast(UnitOfWorkFactory, lambda: FakeUow(store))
    return StrategyRunner(uow_factory, registry), store, instances


def request(**changes: object) -> StrategyRunRequest:
    values: dict[str, object] = {
        "idempotency_key": "run-1",
        "strategy_key": "recording_strategy",
        "timeframe": MarketTimeframe.MINUTE_1,
        "start_at": NOW,
        "end_at": NOW + timedelta(hours=1),
        "instrument_ids": (INSTRUMENT,),
        "parameters": {},
    }
    values.update(changes)
    return StrategyRunRequest(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_success_persists_run_and_ordered_signals() -> None:
    runner, store, instances = setup_runner(bars=[bar(0), bar(1)])
    result = await runner.run(request())
    assert result.run.status is StrategyRunStatus.COMPLETED
    assert (result.run.bars_processed, result.run.signals_generated) == (2, 2)
    assert [item.sequence_number for item in result.signals] == [1, 2]
    assert len(store.signals) == 2
    assert instances[0].times == [NOW, NOW, NOW + timedelta(minutes=1), NOW + timedelta(minutes=1)]


@pytest.mark.asyncio
async def test_persisted_signal_has_complete_provenance() -> None:
    runner, _, _ = setup_runner(bars=[bar()])
    result = await runner.run(request())
    signal = result.signals[0]
    assert signal.strategy_run_id == result.run.id
    assert signal.strategy_key == "recording_strategy"
    assert signal.strategy_version == "1.2.3"
    assert signal.bar_timestamp == NOW
    assert signal.confidence == Decimal("0.8")
    assert signal.metadata == {"source": "unit"}


@pytest.mark.asyncio
async def test_no_market_data_completes_with_warning() -> None:
    runner, store, _ = setup_runner()
    result = await runner.run(request())
    assert result.run.status is StrategyRunStatus.COMPLETED
    assert result.warnings == ("NO_MARKET_DATA",)
    assert (result.run.bars_processed, result.run.signals_generated) == (0, 0)
    assert not store.signals


@pytest.mark.asyncio
async def test_same_idempotency_request_replays_without_execution() -> None:
    runner, store, instances = setup_runner(bars=[bar()])
    first = await runner.run(request())
    second = await runner.run(request())
    assert second.replayed is True
    assert second.run.id == first.run.id
    assert len(instances) == 1
    assert len(store.signals) == 1


@pytest.mark.asyncio
async def test_normalized_instrument_order_replays() -> None:
    second_id = UUID("22222222-2222-2222-2222-222222222222")
    runner, _, _ = setup_runner()
    first = await runner.run(request(instrument_ids=(second_id, INSTRUMENT)))
    second = await runner.run(request(instrument_ids=(INSTRUMENT, second_id, INSTRUMENT)))
    assert second.replayed is True
    assert second.run.id == first.run.id


@pytest.mark.asyncio
async def test_idempotency_conflict_is_controlled() -> None:
    runner, store, _ = setup_runner()
    await runner.run(request())
    with pytest.raises(ApplicationError, match="another strategy run") as captured:
        await runner.run(request(end_at=NOW + timedelta(hours=2)))
    assert captured.value.code == "STRATEGY_RUN_IDEMPOTENCY_CONFLICT"
    assert len(store.runs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["initialize", "on_bar", "finalize", "invalid_draft"])
async def test_failure_rolls_back_signals_and_persists_failed_run(failure: str) -> None:
    runner, store, _ = setup_runner(bars=[bar()], failure=failure)
    result = await runner.run(request())
    assert result.run.status is StrategyRunStatus.FAILED
    assert result.run.error_code in {"STRATEGY_EXECUTION_ERROR", "STRATEGY_INVALID_SIGNAL"}
    assert result.run.bars_processed == result.run.signals_generated == 0
    assert not store.signals
    assert all(item.status is not StrategyRunStatus.RUNNING for item in store.runs.values())


@pytest.mark.asyncio
async def test_unexpected_failure_message_is_sanitized() -> None:
    runner, _, _ = setup_runner(bars=[bar()], failure="on_bar")
    result = await runner.run(request())
    assert result.run.error_message == "strategy run failed"
    assert "secret" not in result.run.error_message


@pytest.mark.asyncio
async def test_unsupported_timeframe_fails_before_persistence() -> None:
    runner, store, _ = setup_runner()
    with pytest.raises(ApplicationError) as captured:
        await runner.run(request(timeframe=MarketTimeframe.DAY_1))
    assert captured.value.code == "STRATEGY_TIMEFRAME_NOT_SUPPORTED"
    assert not store.runs


@pytest.mark.asyncio
async def test_query_and_integrity_are_read_only() -> None:
    runner, store, _ = setup_runner(bars=[bar()])
    result = await runner.run(request())
    query = StrategyRunQueryService(cast(UnitOfWorkFactory, lambda: FakeUow(store)))
    before = deepcopy(store)
    assert (await query.get(result.run.id)).id == result.run.id  # type: ignore[union-attr]
    runs, total = await query.list()
    signals, signal_total = await query.list_signals(result.run.id)
    integrity = await query.check_integrity(result.run.id)
    assert total == signal_total == len(runs) == len(signals) == 1
    assert integrity.is_valid
    assert store == before


@pytest.mark.asyncio
async def test_integrity_reports_count_mismatch() -> None:
    runner, store, _ = setup_runner(bars=[bar()])
    result = await runner.run(request())
    store.signals.clear()
    query = StrategyRunQueryService(cast(UnitOfWorkFactory, lambda: FakeUow(store)))
    report = await query.check_integrity(result.run.id)
    assert report.issues == ("SIGNAL_COUNT_MISMATCH",)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"idempotency_key": ""}, "idempotency_key"),
        ({"idempotency_key": "x" * 129}, "128"),
        ({"request_fingerprint": ""}, "request_fingerprint"),
        ({"strategy_key": ""}, "strategy_key"),
        ({"strategy_version": ""}, "strategy_version"),
        ({"environment": StrategyEnvironment.PAPER}, "RESEARCH"),
        ({"end_at": NOW}, "earlier"),
        ({"instrument_ids": ()}, "instrument_ids"),
        ({"bars_processed": -1}, "non-negative"),
        ({"signals_generated": -1}, "non-negative"),
        ({"error_message": "x" * 513}, "512"),
    ],
)
def test_strategy_run_rejects_invalid_state(changes: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "idempotency_key": "key",
        "request_fingerprint": "hash",
        "strategy_key": "recording_strategy",
        "strategy_version": "1.2.3",
        "environment": StrategyEnvironment.RESEARCH,
        "timeframe": MarketTimeframe.MINUTE_1,
        "start_at": NOW,
        "end_at": NOW + timedelta(minutes=1),
        "parameters": {},
        "instrument_ids": (INSTRUMENT,),
        "status": StrategyRunStatus.CREATED,
        "correlation_id": uuid4(),
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        StrategyRun(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        (1, 1),
        (True, True),
        ("value", "value"),
        (Decimal("1.2500"), "1.25"),
        (Decimal("0"), "0"),
    ],
)
def test_stored_parameters_are_stable(value: object, stored: object) -> None:
    assert stored_parameters({"value": value}) == {"value": stored}  # type: ignore[dict-item]
