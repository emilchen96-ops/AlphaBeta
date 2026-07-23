from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType
from uuid import uuid4

import pytest

from alphadesk_api.agents.miniqmt_market_data import MiniQMTReadOnlyAgent
from alphadesk_api.infrastructure.market_data.miniqmt import MiniQMTMarketDataProvider
from alphadesk_domain.miniqmt_market import (
    ActiveSubscriptionRegistry,
    DesiredSubscription,
    MarketSubscriptionPlanService,
    MiniQMTTradingDisabledError,
    QuoteSnapshot,
    SubscriptionOrigin,
    TradingStatus,
)


def subscription(
    symbol: str,
    origin: SubscriptionOrigin,
    *,
    exchange: str = "SSE",
) -> DesiredSubscription:
    return DesiredSubscription(
        instrument_id=uuid4(),
        symbol=symbol,
        exchange=exchange,
        name=f"股票{symbol}",
        origins=(origin,),
    )


def test_quote_snapshot_preserves_decimal_and_three_times() -> None:
    now = datetime.now(UTC)
    quote = QuoteSnapshot(
        instrument_id=uuid4(),
        symbol="600000",
        exchange="SSE",
        market_time=now,
        received_at=now,
        ingested_at=now,
        last_price=Decimal("9.0100"),
        volume=Decimal("213000"),
        trading_status=TradingStatus.TRADING,
    )
    assert quote.last_price == Decimal("9.0100")
    assert quote.market_time.tzinfo is not None
    assert quote.received_at == quote.ingested_at


def test_quote_snapshot_rejects_naive_time_and_invalid_price() -> None:
    now = datetime.now()
    with pytest.raises(ValueError):
        QuoteSnapshot(
            instrument_id=uuid4(),
            symbol="600000",
            exchange="SSE",
            market_time=now,
            received_at=now,
            ingested_at=now,
            last_price=Decimal("0"),
        )


def test_subscription_planner_merges_origins_and_is_stably_sorted() -> None:
    first = subscription("600000", SubscriptionOrigin.WATCHLIST)
    duplicate = DesiredSubscription(
        instrument_id=first.instrument_id,
        symbol=first.symbol,
        exchange=first.exchange,
        name=first.name,
        origins=(SubscriptionOrigin.SCANNER,),
    )
    benchmark = subscription("510300", SubscriptionOrigin.BENCHMARK)
    plan = MarketSubscriptionPlanService().build(
        candidates=(first, duplicate, benchmark),
        current_instrument_ids=(),
        max_subscriptions=10,
        plan_version="v1",
    )
    assert [item.symbol for item in plan.desired_instruments] == ["510300", "600000"]
    assert set(plan.desired_instruments[1].origins) == {
        SubscriptionOrigin.WATCHLIST,
        SubscriptionOrigin.SCANNER,
    }


def test_subscription_planner_diff_and_limit_are_explicit() -> None:
    values = (
        subscription("600000", SubscriptionOrigin.WATCHLIST),
        subscription("000001", SubscriptionOrigin.WATCHLIST, exchange="SZSE"),
    )
    unknown_current = uuid4()
    plan = MarketSubscriptionPlanService().build(
        candidates=values,
        current_instrument_ids=(values[0].instrument_id, unknown_current),
        max_subscriptions=1,
        plan_version="v1",
    )
    assert len(plan.desired_instruments) == 1
    assert len(plan.rejected_instruments) == 1
    assert plan.rejected_instruments[0][1] == "SUBSCRIPTION_LIMIT_EXCEEDED"
    assert unknown_current in plan.instruments_to_unsubscribe


def test_subscription_planner_reports_unsupported_exchange() -> None:
    value = subscription("U01001", SubscriptionOrigin.SCANNER, exchange="U01")
    plan = MarketSubscriptionPlanService().build(
        candidates=(value,),
        current_instrument_ids=(),
        max_subscriptions=10,
        plan_version="v1",
    )
    assert plan.desired_instruments == ()
    assert plan.rejected_instruments == ((value, "UNSUPPORTED_EXCHANGE"),)


def test_subscription_planner_repeated_calculation_is_idempotent() -> None:
    value = subscription("600000", SubscriptionOrigin.WATCHLIST)
    planner = MarketSubscriptionPlanService()
    first = planner.build(
        candidates=(value,),
        current_instrument_ids=(),
        max_subscriptions=10,
        plan_version="same",
    )
    second = planner.build(
        candidates=(value, value),
        current_instrument_ids=(),
        max_subscriptions=10,
        plan_version="same",
    )
    assert first == second


def test_active_registry_can_recover_agent_reported_state() -> None:
    instrument_id = uuid4()
    registry = ActiveSubscriptionRegistry()
    registry.replace({instrument_id: 8})
    assert registry.by_instrument == {instrument_id: 8}


class FakeXtData:
    def __init__(self) -> None:
        self.unsubscribed: list[int] = []

    def connect(self) -> None:
        pass

    def get_client(self) -> object:
        return object()

    def get_full_tick(self, symbols: list[str]) -> dict[str, dict[str, object]]:
        return {symbols[0]: {"time": 1784773337000, "lastPrice": 9.01}}

    def subscribe_quote(self, *args: object, **kwargs: object) -> int:
        callback = kwargs.get("callback")
        if callable(callback):
            callback(
                {
                    str(args[0]): [
                        {
                            "time": 1784773337000,
                            "lastPrice": 9.01,
                            "close": 9.01,
                        }
                    ]
                }
            )
        return 7

    def unsubscribe_quote(self, subscription_id: int) -> None:
        self.unsubscribed.append(subscription_id)

    def get_instrument_detail(self, _symbol: str, *, iscomplete: bool) -> dict[str, object]:
        assert iscomplete
        return {"InstrumentName": "浦发银行"}


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> MiniQMTMarketDataProvider:
    module = ModuleType("xtquant")
    fake = FakeXtData()
    module.xtdata = fake  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "xtquant", module)
    provider = MiniQMTMarketDataProvider(data_path=r"D:\QMT\userdata_mini")
    provider.connect()
    return provider


def test_miniqmt_provider_connects_and_reads_snapshot(fake_provider) -> None:
    assert fake_provider.connected is True
    assert fake_provider.latest_raw_snapshot("600000.SH") == {
        "time": 1784773337000,
        "lastPrice": 9.01,
    }
    assert fake_provider.instrument_detail("600000.SH")["InstrumentName"] == "浦发银行"


def test_miniqmt_provider_normalizes_timezone_decimal_and_order_book(fake_provider) -> None:
    normalized = fake_provider.normalize_quote(
        {
            "time": 1784773337000,
            "lastPrice": 9.01,
            "lastClose": 9.0,
            "bidPrice": [9.0],
            "askPrice": [9.01],
            "bidVol": [100],
            "askVol": [200],
        }
    )
    assert normalized["last_price"] == Decimal("9.01")
    assert normalized["market_time"].tzinfo is not None
    assert normalized["bid_volume_1"] == Decimal("100")


def test_miniqmt_provider_subscribe_and_unsubscribe(fake_provider) -> None:
    received: list[dict[str, object]] = []
    subscription_id = fake_provider.subscribe_quote(
        "600000.SH", lambda _symbol, raw: received.append(raw)
    )
    fake_provider.unsubscribe(subscription_id)
    assert subscription_id == 7
    assert received == [{"time": 1784773337000, "lastPrice": 9.01, "close": 9.01}]


def test_miniqmt_provider_rejects_every_trading_message(fake_provider) -> None:
    with pytest.raises(MiniQMTTradingDisabledError) as exc_info:
        fake_provider.reject_trading_command({"type": "SUBMIT_ORDER"})
    assert exc_info.value.code == "MINIQMT_TRADING_DISABLED"


def test_qmt_history_time_uses_exchange_local_time() -> None:
    assert MiniQMTReadOnlyAgent._qmt_time("2026-07-23T01:30:00+00:00") == "20260723093000"


def test_qmt_history_accepts_pandas_float_epoch(fake_provider) -> None:
    normalized = fake_provider.normalize_minute_bar(
        {
            "time": 1_784_683_860_000.0,
            "open": 9,
            "high": 9.1,
            "low": 8.9,
            "close": 9.05,
            "volume": 100,
            "amount": 905,
        }
    )
    assert normalized["bar_time"] == datetime(2026, 7, 22, 1, 30, tzinfo=UTC)


def test_miniqmt_module_never_imports_trade_sdk() -> None:
    import inspect

    from alphadesk_api.infrastructure.market_data import miniqmt

    source = inspect.getsource(miniqmt).lower()
    assert "from xtquant import xtdata" in source
    assert "from xtquant import xttrader" not in source
    assert "import xttrader" not in source
    assert all(
        forbidden not in source
        for forbidden in (
            "query_account",
            "query_asset",
            "query_position",
            "query_order",
            "query_trade",
            "order_stock",
            "cancel_order",
        )
    )
