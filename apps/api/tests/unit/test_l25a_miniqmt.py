import json
import threading
from datetime import UTC, datetime
from decimal import Decimal
from types import ModuleType
from uuid import uuid4

import httpx
import pytest

from alphadesk_api.agents.miniqmt_market_data import MiniQMTReadOnlyAgent
from alphadesk_api.application.miniqmt_market_data import (
    HISTORY_DEAD_LETTER_KEY,
    HISTORY_QUEUE_KEY,
    compact_history_queue,
    complete_history_request,
    enqueue_history_request,
    fail_history_request,
    peek_history_request,
)
from alphadesk_api.infrastructure.market_data.miniqmt import (
    MiniQMTMarketDataProvider,
    MiniQMTNotAvailableError,
)
from alphadesk_domain.miniqmt_market import (
    ActiveSubscriptionRegistry,
    DesiredSubscription,
    MarketSubscriptionPlanService,
    MiniQMTTradingDisabledError,
    QuoteSnapshot,
    SubscriptionOrigin,
    TradingStatus,
)


def test_agent_rebuilds_api_client_and_retries_transport_failure(monkeypatch) -> None:
    class BrokenClient:
        def request(self, method, path, **kwargs):
            del method, path, kwargs
            raise httpx.ConnectError("API restarting")

    class HealthyClient:
        def request(self, method, path, **kwargs):
            del kwargs
            return httpx.Response(200, request=httpx.Request(method, f"http://api{path}"))

    agent = MiniQMTReadOnlyAgent.__new__(MiniQMTReadOnlyAgent)
    agent._http = BrokenClient()
    reset_count = 0

    def reset_client() -> None:
        nonlocal reset_count
        reset_count += 1
        agent._http = HealthyClient()

    monkeypatch.setattr(agent, "_reset_http_client", reset_client)
    monkeypatch.setattr("alphadesk_api.agents.miniqmt_market_data.time.sleep", lambda _: None)

    response = agent._request("GET", "/health")

    assert response.status_code == 200
    assert reset_count == 1


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


class FakeHistoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def set(self, key, value, *, ex=None, nx=False):
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = str(value)
        return True

    async def rpush(self, key, value):
        values = self.lists.setdefault(key, [])
        values.append(value)
        return len(values)

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    async def lindex(self, key, index):
        values = self.lists.get(key, [])
        try:
            return values[index]
        except IndexError:
            return None

    async def lpop(self, key):
        values = self.lists.get(key, [])
        return values.pop(0) if values else None

    async def lmove(self, source, destination, wherefrom, whereto):
        assert wherefrom == "LEFT"
        assert whereto == "RIGHT"
        values = self.lists.get(source, [])
        if not values:
            return None
        value = values.pop(0)
        self.lists.setdefault(destination, []).append(value)
        return value

    async def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        stop = None if end == -1 else end + 1
        return values[start:stop]

    async def lrem(self, key, count, value):
        assert count == 1
        values = self.lists.get(key, [])
        try:
            values.remove(value)
        except ValueError:
            return 0
        return 1


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


@pytest.mark.asyncio
async def test_identical_active_history_requests_are_deduplicated() -> None:
    client = FakeHistoryRedis()
    scope = {
        "timeframe": "MINUTE_1",
        "segments": [
            {
                "start_at": "2026-07-29T16:00:00+00:00",
                "end_at": "2026-07-30T16:00:00+00:00",
                "instrument_ids": [str(uuid4())],
            }
        ],
    }

    first = await enqueue_history_request(
        client, {**scope, "request_id": str(uuid4()), "backtest_run_id": str(uuid4())}
    )
    second = await enqueue_history_request(
        client, {**scope, "request_id": str(uuid4()), "backtest_run_id": str(uuid4())}
    )

    assert first == second == 1
    assert len(client.lists[HISTORY_QUEUE_KEY]) == 1


@pytest.mark.asyncio
async def test_history_request_survives_claim_until_acknowledged() -> None:
    client = FakeHistoryRedis()
    request_id = str(uuid4())
    await enqueue_history_request(
        client,
        {
            "request_id": request_id,
            "timeframe": "DAY_1",
            "instrument_ids": [str(uuid4())],
            "start_at": "2026-07-01T00:00:00+00:00",
            "end_at": "2026-08-01T00:00:00+00:00",
        },
    )

    first_claim = await peek_history_request(client)
    second_claim = await peek_history_request(client)

    assert first_claim is not None
    assert second_claim == first_claim
    assert await client.llen(HISTORY_QUEUE_KEY) == 1
    assert await complete_history_request(client, request_id) is True
    assert await client.llen(HISTORY_QUEUE_KEY) == 0


@pytest.mark.asyncio
async def test_history_queue_fairly_rotates_between_workflows_after_ack() -> None:
    client = FakeHistoryRedis()
    first_run_id = str(uuid4())
    second_run_id = str(uuid4())

    async def enqueue(run_id: str, suffix: str) -> str:
        request_id = str(uuid4())
        await enqueue_history_request(
            client,
            {
                "request_id": request_id,
                "timeframe": "DAY_1",
                "instrument_ids": [str(uuid4())],
                "start_at": f"2026-07-{suffix}T00:00:00+00:00",
                "end_at": "2026-08-01T00:00:00+00:00",
                "scan_run_id": run_id,
            },
        )
        return request_id

    first_request = await enqueue(first_run_id, "01")
    await enqueue(first_run_id, "02")
    await enqueue(first_run_id, "03")
    await enqueue(second_run_id, "04")
    await enqueue(second_run_id, "05")

    assert await complete_history_request(client, first_request) is True
    next_request = await peek_history_request(client)

    assert next_request is not None
    assert next_request["scan_run_id"] == second_run_id


@pytest.mark.asyncio
async def test_legacy_batch_backtests_do_not_block_a_new_scan_workflow() -> None:
    client = FakeHistoryRedis()

    async def enqueue_backtest(suffix: str) -> str:
        request_id = str(uuid4())
        await enqueue_history_request(
            client,
            {
                "request_id": request_id,
                "timeframe": "MINUTE_1",
                "instrument_ids": [str(uuid4())],
                "start_at": f"2026-07-{suffix}T00:00:00+00:00",
                "end_at": "2026-08-01T00:00:00+00:00",
                "origin": "BT02_A_INTRADAY_BACKTEST",
                "backtest_run_id": str(uuid4()),
            },
        )
        return request_id

    first_request = await enqueue_backtest("01")
    await enqueue_backtest("02")
    scan_run_id = str(uuid4())
    await enqueue_history_request(
        client,
        {
            "request_id": str(uuid4()),
            "timeframe": "DAY_1",
            "instrument_ids": [str(uuid4())],
            "start_at": "2026-07-03T00:00:00+00:00",
            "end_at": "2026-08-01T00:00:00+00:00",
            "origin": "SC02_D",
            "scan_run_id": scan_run_id,
        },
    )

    assert await complete_history_request(client, first_request) is True
    next_request = await peek_history_request(client)

    assert next_request is not None
    assert next_request["scan_run_id"] == scan_run_id


@pytest.mark.asyncio
async def test_failed_history_request_rotates_then_enters_dead_letter() -> None:
    client = FakeHistoryRedis()
    request_id = str(uuid4())
    payload = {
        "request_id": request_id,
        "timeframe": "DAY_1",
        "instrument_ids": [str(uuid4())],
        "start_at": "2026-07-01T00:00:00+00:00",
        "end_at": "2026-08-01T00:00:00+00:00",
    }
    await enqueue_history_request(client, payload)

    for attempt in (1, 2):
        result = await fail_history_request(
            client,
            request_id,
            error_code="UPSTREAM_TIMEOUT",
            error_message="timeout",
        )
        assert result == {"accepted": True, "status": "REQUEUED", "attempts": attempt}

    result = await fail_history_request(
        client,
        request_id,
        error_code="UPSTREAM_TIMEOUT",
        error_message="timeout",
    )
    assert result == {"accepted": True, "status": "QUARANTINED", "attempts": 3}
    assert await client.llen(HISTORY_QUEUE_KEY) == 0
    assert await client.llen(HISTORY_DEAD_LETTER_KEY) == 1


@pytest.mark.asyncio
async def test_history_queue_compaction_keeps_newest_duplicate() -> None:
    client = FakeHistoryRedis()
    instrument_id = str(uuid4())
    scope = {
        "timeframe": "DAY_1",
        "instrument_ids": [instrument_id],
        "start_at": "2026-07-01T00:00:00+00:00",
        "end_at": "2026-08-01T00:00:00+00:00",
    }
    older_id = str(uuid4())
    newer_id = str(uuid4())
    await client.rpush(HISTORY_QUEUE_KEY, json.dumps({**scope, "request_id": older_id}))
    await client.rpush(HISTORY_QUEUE_KEY, "not-json")
    await client.rpush(HISTORY_QUEUE_KEY, json.dumps({**scope, "request_id": newer_id}))

    result = await compact_history_queue(client)

    assert result == {
        "before": 3,
        "remaining": 1,
        "duplicates_removed": 1,
        "malformed_removed": 1,
        "transient_recovered": 0,
    }
    assert (await peek_history_request(client))["request_id"] == newer_id


@pytest.mark.asyncio
async def test_disconnect_failure_does_not_consume_attempt_budget() -> None:
    client = FakeHistoryRedis()
    request_id = str(uuid4())
    await enqueue_history_request(
        client,
        {
            "request_id": request_id,
            "timeframe": "DAY_1",
            "instrument_ids": [str(uuid4())],
            "start_at": "2026-07-01T00:00:00+00:00",
            "end_at": "2026-08-01T00:00:00+00:00",
        },
    )

    result = await fail_history_request(
        client,
        request_id,
        error_code="MiniQMTNotAvailableError",
        error_message="MINIQMT_NOT_CONNECTED",
    )

    assert result == {
        "accepted": True,
        "status": "REQUEUED_AFTER_RECONNECT",
        "attempts": 0,
    }
    assert await client.llen(HISTORY_QUEUE_KEY) == 1
    assert await client.llen(HISTORY_DEAD_LETTER_KEY) == 0


@pytest.mark.asyncio
async def test_compaction_recovers_disconnect_dead_letters() -> None:
    client = FakeHistoryRedis()
    request_id = str(uuid4())
    payload = {
        "request_id": request_id,
        "timeframe": "DAY_1",
        "instrument_ids": [str(uuid4())],
        "start_at": "2026-07-01T00:00:00+00:00",
        "end_at": "2026-08-01T00:00:00+00:00",
        "_queue_attempts": 3,
        "_queue_last_error_code": "MiniQMTNotAvailableError",
        "_queue_last_error_message": "MINIQMT_NOT_CONNECTED",
    }
    await client.rpush(HISTORY_DEAD_LETTER_KEY, json.dumps(payload))

    result = await compact_history_queue(client)

    assert result["transient_recovered"] == 1
    assert result["remaining"] == 1
    restored = await peek_history_request(client)
    assert restored is not None
    assert restored["request_id"] == request_id
    assert restored["_queue_attempts"] == 0
    assert await client.llen(HISTORY_DEAD_LETTER_KEY) == 0


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
        if _symbol == "510300.SH":
            return {
                "InstrumentName": "沪深300ETF",
                "OpenDate": "20120528",
                "ExpireDate": "99999999",
            }
        return {
            "InstrumentName": "浦发银行",
            "OpenDate": "19991110",
            "ExpireDate": "99999999",
        }

    def get_sector_list(self) -> list[str]:
        return ["沪深京A股", "沪市ETF"]

    def get_stock_list_in_sector(self, sector: str) -> list[str]:
        if sector == "沪深京A股":
            return ["600000.SH", "810011.BJ"]
        if sector == "沪市ETF":
            return ["510300.SH"]
        return []


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


def test_miniqmt_catalog_treats_qmt_no_expiry_sentinel_as_active(fake_provider) -> None:
    catalog = fake_provider.instrument_catalog()
    assert [(item["provider_symbol"], item["asset_type"]) for item in catalog] == [
        ("510300.SH", "ETF"),
        ("600000.SH", "STOCK"),
    ]
    assert all(item["is_active"] is True for item in catalog)
    assert all(item["delisted_at"] is None for item in catalog)


@pytest.mark.parametrize(
    ("provider_symbol", "expected"),
    [
        ("600000.SH", True),
        ("688001.SH", True),
        ("000001.SZ", True),
        ("300285.SZ", True),
        ("920001.BJ", True),
        ("810011.BJ", False),
        ("900901.SH", False),
        ("200002.SZ", False),
    ],
)
def test_miniqmt_catalog_recognizes_a_share_code_ranges(
    provider_symbol: str, expected: bool
) -> None:
    assert MiniQMTMarketDataProvider._is_a_share_symbol(provider_symbol) is expected


@pytest.mark.parametrize("value", ["99999999", "10111011", "10001011", "not-a-date"])
def test_miniqmt_catalog_rejects_qmt_invalid_dates(value: str) -> None:
    assert MiniQMTMarketDataProvider._catalog_date(value) is None


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


def test_miniqmt_provider_drops_zero_optional_prices_and_rejects_zero_last(
    fake_provider,
) -> None:
    normalized = fake_provider.normalize_quote(
        {
            "time": 1784773337000,
            "lastPrice": 9.01,
            "open": 0,
            "high": 0,
            "low": 0,
            "lastClose": 0,
            "bidPrice": [0],
            "askPrice": [0],
        }
    )
    assert normalized["open_price"] is None
    assert normalized["previous_close"] is None
    assert normalized["bid_price_1"] is None

    with pytest.raises(ValueError, match="MINIQMT_QUOTE_LAST_PRICE_NOT_POSITIVE"):
        fake_provider.normalize_quote({"time": 1784773337000, "lastPrice": 0})


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


def test_miniqmt_history_timeout_cancels_stalled_qmt_download(monkeypatch) -> None:
    stopped = threading.Event()

    class Client:
        def stop_supply_history_data2(self) -> None:
            stopped.set()

    class StalledXtData(FakeXtData):
        def __init__(self) -> None:
            super().__init__()
            self.client = Client()

        def get_client(self) -> object:
            return self.client

        def download_history_data2(self, *args, **kwargs) -> None:
            del args, kwargs
            stopped.wait(timeout=1)

    module = ModuleType("xtquant")
    module.xtdata = StalledXtData()  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "xtquant", module)
    provider = MiniQMTMarketDataProvider(
        data_path=r"D:\QMT\userdata_mini",
        history_download_timeout_seconds=0.01,
    )
    provider.connect()

    with pytest.raises(MiniQMTNotAvailableError, match="MINIQMT_HISTORY_DOWNLOAD_TIMEOUT"):
        provider.history(
            ("600000.SH",),
            period="1d",
            start_time="20260701000000",
            end_time="20260801000000",
        )

    assert stopped.is_set()
    assert provider.connected is False


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
