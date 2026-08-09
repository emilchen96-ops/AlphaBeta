"""Long-running Windows MiniQMT read-only market-data agent."""

from __future__ import annotations

import logging
import queue
import time
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx

from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.market_data.miniqmt import (
    MiniQMTMarketDataProvider,
    MiniQMTNotAvailableError,
)
from alphadesk_domain.enums import MarketTimeframe
from alphadesk_domain.intraday import IntradaySessionTemplate

LOGGER = logging.getLogger(__name__)
AGENT_VERSION = "L2.5-A.1"
SHANGHAI = ZoneInfo("Asia/Shanghai")
HISTORY_UPLOAD_TIMEOUT_SECONDS = 120
HISTORY_INGEST_CHUNK_SIZE = 250
API_RETRY_MAX_DELAY_SECONDS = 5.0


class MiniQMTReadOnlyAgent:
    """Reconcile desired subscriptions and forward normalized market data."""

    trading_capability = "DISABLED"
    market_data_capability = "ENABLED"

    def __init__(self, settings: Settings) -> None:
        if not settings.miniqmt_market_data_enabled:
            raise MiniQMTNotAvailableError("MINIQMT_MARKET_DATA_DISABLED")
        if not settings.miniqmt_data_path:
            raise MiniQMTNotAvailableError("MINIQMT_DATA_PATH_NOT_CONFIGURED")
        self._settings = settings
        self._provider = MiniQMTMarketDataProvider(
            data_path=settings.miniqmt_data_path,
            xtquant_path=settings.miniqmt_xtquant_path,
            history_download_timeout_seconds=settings.miniqmt_history_download_timeout_seconds,
        )
        self._http = self._make_http_client()
        self._quotes: queue.Queue[tuple[dict[str, Any], dict[str, object]]] = queue.Queue(
            maxsize=10_000
        )
        self._bars: queue.Queue[tuple[dict[str, Any], dict[str, object]]] = queue.Queue(
            maxsize=2_000
        )
        self._subscriptions: dict[UUID, tuple[int, int]] = {}
        self._items: dict[UUID, dict[str, Any]] = {}
        self._last_market_time: str | None = None
        self._last_received_at: str | None = None
        self._last_minute_bar_time: str | None = None
        self._last_catalog_sync_at: str | None = None
        self._catalog_instrument_count = 0
        self._session_template = IntradaySessionTemplate()
        self._startup_repair_pending = True
        self._last_daily_maintenance_date: date | None = None

    def _make_http_client(self) -> httpx.Client:
        headers = {}
        if self._settings.miniqmt_agent_token is not None:
            headers["X-AlphaDesk-Agent-Token"] = (
                self._settings.miniqmt_agent_token.get_secret_value()
            )
        return httpx.Client(
            base_url=self._settings.miniqmt_agent_api_url.rstrip("/"),
            headers=headers,
            timeout=10,
            # The agent reconciles every five seconds, which can race with
            # Uvicorn's default five-second keep-alive expiry. Retire idle
            # sockets earlier so a normal server close is not mistaken for a
            # market-data disconnection.
            limits=httpx.Limits(keepalive_expiry=2),
        )

    def _reset_http_client(self) -> None:
        try:
            self._http.close()
        except Exception:
            LOGGER.debug("Unable to close stale AlphaDesk API client", exc_info=True)
        self._http = self._make_http_client()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Reach the API without abandoning a claimed history job."""

        attempt = 0
        while True:
            try:
                return self._http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                attempt += 1
                delay = min(0.25 * (2 ** min(attempt - 1, 5)), API_RETRY_MAX_DELAY_SECONDS)
                LOGGER.warning(
                    "AlphaDesk API unavailable; rebuilding connection and retrying "
                    "in %.2fs (attempt %s): %s",
                    delay,
                    attempt,
                    exc,
                )
                self._reset_http_client()
                time.sleep(delay)

    def run(self, *, once: bool = False) -> None:
        while True:
            try:
                self._provider.connect()
                self._startup_repair_pending = True
                self._report_status("CONNECTED")
                self._sync_catalog()
                self._compact_history_queue()
                while True:
                    self._reconcile()
                    self._flush()
                    processed_history = self._process_history()
                    if not processed_history:
                        try:
                            self._automatic_maintenance()
                        except Exception:
                            # Automatic cache warming is best effort.  It must
                            # never tear down subscriptions or starve explicit
                            # scanner/backtest history requests.
                            LOGGER.exception("MiniQMT automatic maintenance failed")
                    # Explicit history work is already serialized and each
                    # batch performs its own API/QMT I/O.  Sleeping five full
                    # seconds after every successful batch made a 109-batch
                    # full-market scan spend more than nine minutes doing
                    # nothing.  Keep the normal reconciliation cadence only
                    # while idle; active history queues drain continuously.
                    delay_seconds = 0.1 if processed_history else (1 if once else 5)
                    deadline = time.monotonic() + delay_seconds
                    while time.monotonic() < deadline:
                        self._flush()
                        time.sleep(0.1)
                    self._report_status("CONNECTED")
                    if once:
                        return
            except KeyboardInterrupt:
                self._report_status("DISCONNECTED")
                self._http.close()
                return
            except Exception as exc:
                LOGGER.exception("MiniQMT read-only agent connection cycle stopped")
                self._report_status(
                    "DISCONNECTED",
                    error_code=getattr(exc, "code", type(exc).__name__),
                    error_message=str(exc)[:512],
                )
                if once:
                    raise
                self._subscriptions.clear()
                self._items.clear()
                time.sleep(5)
            finally:
                if once:
                    self._http.close()

    def _automatic_maintenance(self) -> None:
        if not self._items:
            return
        now = datetime.now(SHANGHAI)
        selected = list(self._items.values())[: self._settings.miniqmt_history_max_instruments]
        if self._startup_repair_pending:
            # Mark the startup maintenance as attempted before any network I/O.
            # A slow ingestion endpoint must not reconnect and repeat the same
            # automatic downloads forever ahead of user-requested history jobs.
            self._startup_repair_pending = False
            self._persist_history(
                selected,
                timeframe="DAY_1",
                start_at=now - timedelta(days=14),
                end_at=now + timedelta(days=1),
            )
            self._persist_history(
                selected,
                timeframe="MINUTE_1",
                start_at=now - timedelta(days=3),
                end_at=now + timedelta(days=1),
            )
            if now.hour > 15 or (now.hour == 15 and now.minute >= 10):
                self._last_daily_maintenance_date = now.date()
            return
        after_close = now.hour > 15 or (now.hour == 15 and now.minute >= 10)
        if after_close and self._last_daily_maintenance_date != now.date():
            self._last_daily_maintenance_date = now.date()
            self._persist_history(
                selected,
                timeframe="DAY_1",
                start_at=now - timedelta(days=7),
                end_at=now + timedelta(days=1),
            )

    def _persist_history(
        self,
        selected: list[dict[str, Any]],
        *,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
    ) -> None:
        period = "1m" if timeframe == "MINUTE_1" else "1d"
        rows = self._provider.history(
            tuple(item["provider_symbol"] for item in selected),
            period=period,
            start_time=self._qmt_time(start_at.isoformat()),
            end_time=self._qmt_time(end_at.isoformat()),
        )
        by_symbol = {item["provider_symbol"]: item for item in selected}
        items = [
            {
                "instrument_id": by_symbol[row["provider_symbol"]]["instrument_id"],
                "timeframe": timeframe,
                **self._json_values(
                    {key: value for key, value in row.items() if key != "provider_symbol"}
                ),
            }
            for row in rows
            if row["provider_symbol"] in by_symbol
        ]
        for offset in range(0, len(items), HISTORY_INGEST_CHUNK_SIZE):
            response = self._request(
                "POST",
                "/api/v1/miniqmt/agent/minute-bars",
                json={"items": items[offset : offset + HISTORY_INGEST_CHUNK_SIZE]},
                timeout=HISTORY_UPLOAD_TIMEOUT_SECONDS,
            )
            response.raise_for_status()

    def _compact_history_queue(self) -> None:
        response = self._request("POST", "/api/v1/miniqmt/agent/history/compact")
        response.raise_for_status()
        result = response.json()["data"]
        if (
            result.get("duplicates_removed")
            or result.get("malformed_removed")
            or result.get("transient_recovered")
        ):
            LOGGER.warning(
                "Compacted MiniQMT history queue: "
                "before=%s remaining=%s duplicates=%s malformed=%s recovered=%s",
                result.get("before"),
                result.get("remaining"),
                result.get("duplicates_removed"),
                result.get("malformed_removed"),
                result.get("transient_recovered"),
            )

    def _sync_catalog(self) -> None:
        catalog = self._provider.instrument_catalog()
        sync_token = uuid4()
        for offset in range(0, len(catalog), 500):
            items = catalog[offset : offset + 500]
            response = self._request(
                "POST",
                "/api/v1/miniqmt/agent/instruments",
                json={
                    "sync_token": str(sync_token),
                    "complete": offset + len(items) >= len(catalog),
                    "items": items,
                },
            )
            response.raise_for_status()
        self._catalog_instrument_count = len(catalog)
        self._last_catalog_sync_at = datetime.now(UTC).isoformat()
        self._report_status("CONNECTED")

    def _reconcile(self) -> None:
        self._request("POST", "/api/v1/market-subscriptions/rebuild").raise_for_status()
        sync = self._request("POST", "/api/v1/market-subscriptions/sync")
        sync.raise_for_status()
        payload = sync.json()["data"]
        plan_items = {UUID(item["instrument_id"]): item for item in payload["plan"]["items"]}
        desired_ids = set(plan_items)
        subscribe_ids = set(payload["diff"]["instruments_to_subscribe"])
        subscribe = {UUID(item) for item in subscribe_ids}
        if not self._subscriptions:
            # Agent restart: provider-side callbacks no longer exist, so rebuild the mirror.
            subscribe = desired_ids
        unsubscribe = (set(self._subscriptions) - desired_ids) | {
            UUID(item) for item in payload["diff"]["instruments_to_unsubscribe"]
        }
        subscription_results: list[dict[str, object]] = []
        unsubscription_results: list[dict[str, object]] = []
        for instrument_id in sorted(unsubscribe, key=str):
            item = self._items.get(instrument_id)
            try:
                ids = self._subscriptions.get(instrument_id)
                if ids is not None:
                    self._provider.unsubscribe(ids[0])
                    self._provider.unsubscribe(ids[1])
                    self._subscriptions.pop(instrument_id, None)
                self._items.pop(instrument_id, None)
                unsubscription_results.append(
                    {
                        "instrument_id": str(instrument_id),
                        "provider_symbol": (
                            item["provider_symbol"] if item is not None else "UNKNOWN"
                        ),
                        "success": True,
                    }
                )
            except Exception as exc:
                unsubscription_results.append(
                    {
                        "instrument_id": str(instrument_id),
                        "provider_symbol": (
                            item["provider_symbol"] if item is not None else "UNKNOWN"
                        ),
                        "success": False,
                        "error_code": type(exc).__name__,
                        "error_message": str(exc)[:512],
                    }
                )
        for instrument_id in sorted(subscribe, key=str):
            item = plan_items[instrument_id]
            if instrument_id in self._subscriptions:
                continue
            tick_id: int | None = None
            try:
                tick_id = self._provider.subscribe_quote(
                    item["provider_symbol"],
                    partial(self._quote_callback, item),
                    period="tick",
                )
                minute_id = self._provider.subscribe_quote(
                    item["provider_symbol"],
                    partial(self._bar_callback, item),
                    period="1m",
                )
                self._subscriptions[instrument_id] = (tick_id, minute_id)
                self._items[instrument_id] = item
                # Seed the cache immediately. During the midday break and after
                # market close MiniQMT may not emit a callback until the next
                # tick, but the latest full-tick snapshot is still available.
                snapshot = self._provider.latest_raw_snapshot(item["provider_symbol"])
                if snapshot is not None:
                    self._put_quote(item, snapshot)
                subscription_results.append(
                    {
                        "instrument_id": str(instrument_id),
                        "provider_symbol": item["provider_symbol"],
                        "success": True,
                        "subscription_id": f"tick:{tick_id},1m:{minute_id}",
                    }
                )
            except Exception as exc:
                if tick_id is not None:
                    try:
                        self._provider.unsubscribe(tick_id)
                    except Exception:
                        LOGGER.warning(
                            "Unable to roll back partial MiniQMT subscription",
                            exc_info=True,
                        )
                subscription_results.append(
                    {
                        "instrument_id": str(instrument_id),
                        "provider_symbol": item["provider_symbol"],
                        "success": False,
                        "error_code": type(exc).__name__,
                        "error_message": str(exc)[:512],
                    }
                )
        report = self._request(
            "POST",
            f"/api/v1/miniqmt/agent/subscription-sync/{payload['sync_run_id']}",
            json={
                "subscriptions": subscription_results,
                "unsubscriptions": unsubscription_results,
            },
        )
        report.raise_for_status()

    def _put_quote(self, item: dict[str, Any], raw: dict[str, Any]) -> None:
        try:
            normalized = self._provider.normalize_quote(raw)
        except (KeyError, ValueError):
            LOGGER.info("Ignoring incomplete MiniQMT quote snapshot", exc_info=True)
            return
        try:
            self._quotes.put_nowait((item, normalized))
        except queue.Full:
            LOGGER.warning("MiniQMT quote queue full; dropping oldest display update")
            self._quotes.get_nowait()
            self._quotes.put_nowait((item, normalized))

    def _quote_callback(self, item: dict[str, Any], _symbol: str, raw: dict[str, Any]) -> None:
        self._put_quote(item, raw)

    def _put_bar(self, item: dict[str, Any], raw: dict[str, Any]) -> None:
        try:
            normalized = self._provider.normalize_minute_bar(raw)
            bar_time = normalized.get("bar_time")
            if not isinstance(bar_time, datetime) or not self._session_template.validate_bar_start(
                bar_time, MarketTimeframe.MINUTE_1
            ):
                LOGGER.info("Ignoring MiniQMT minute callback outside the D03 regular session")
                return
            self._bars.put_nowait((item, normalized))
        except (KeyError, ValueError, queue.Full):
            LOGGER.warning("MiniQMT minute callback rejected", exc_info=True)

    def _bar_callback(self, item: dict[str, Any], _symbol: str, raw: dict[str, Any]) -> None:
        self._put_bar(item, raw)

    def _flush(self) -> None:
        for _ in range(500):
            try:
                item, quote = self._quotes.get_nowait()
            except queue.Empty:
                break
            now = datetime.now(UTC)
            market_time = quote.pop("market_time")
            if not isinstance(market_time, datetime):
                raise ValueError("MiniQMT行情时间无效")
            response = self._request(
                "POST",
                "/api/v1/miniqmt/agent/quotes",
                json={
                    "schema_version": 1,
                    "instrument_id": item["instrument_id"],
                    "symbol": item["symbol"],
                    "exchange": item["exchange"],
                    "market_time": market_time.isoformat(),
                    "received_at": now.isoformat(),
                    "ingested_at": now.isoformat(),
                    "trading_status": self._trading_status(quote.pop("stock_status", None)),
                    **self._json_values(quote),
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                if 400 <= response.status_code < 500:
                    LOGGER.warning(
                        "Dropping invalid MiniQMT quote snapshot: status=%s body=%s",
                        response.status_code,
                        response.text[:512],
                    )
                    continue
                raise
            self._last_market_time = market_time.isoformat()
            self._last_received_at = now.isoformat()
        bars: list[dict[str, object]] = []
        for _ in range(500):
            try:
                item, bar = self._bars.get_nowait()
            except queue.Empty:
                break
            bar_time = bar["bar_time"]
            bars.append(
                {
                    "instrument_id": item["instrument_id"],
                    "timeframe": "MINUTE_1",
                    **self._json_values(bar),
                }
            )
            self._last_minute_bar_time = str(
                bar_time.isoformat() if isinstance(bar_time, datetime) else bar_time
            )
        if bars:
            response = self._request(
                "POST", "/api/v1/miniqmt/agent/minute-bars", json={"items": bars}
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                if 400 <= response.status_code < 500:
                    LOGGER.warning(
                        "Dropping invalid MiniQMT minute callback batch: status=%s body=%s",
                        response.status_code,
                        response.text[:512],
                    )
                else:
                    raise

    def _process_history(self) -> bool:
        response = self._request("GET", "/api/v1/miniqmt/agent/history/next")
        response.raise_for_status()
        request = response.json()["data"]["request"]
        if request is None:
            return False
        request_id = str(request.get("request_id") or "")
        try:
            segments = request.get("segments")
            if isinstance(segments, list) and segments:
                persisted_segment = False
                for segment in segments:
                    if not isinstance(segment, dict):
                        continue
                    selected = list(segment.get("instruments", []))
                    if not selected:
                        instrument_ids = [
                            UUID(item) for item in segment.get("instrument_ids", [])
                        ]
                        selected = [
                            self._items[item] for item in instrument_ids if item in self._items
                        ]
                    if not selected:
                        raise ValueError("MINIQMT_HISTORY_INSTRUMENTS_UNRESOLVED")
                    self._persist_history(
                        selected,
                        timeframe=request["timeframe"],
                        start_at=datetime.fromisoformat(segment["start_at"]),
                        end_at=datetime.fromisoformat(segment["end_at"]),
                    )
                    persisted_segment = True
                if not persisted_segment:
                    raise ValueError("MINIQMT_HISTORY_SEGMENTS_EMPTY")
            else:
                selected = list(request.get("instruments", []))
                if not selected:
                    instrument_ids = [UUID(item) for item in request["instrument_ids"]]
                    selected = [
                        self._items[item] for item in instrument_ids if item in self._items
                    ]
                if not selected:
                    raise ValueError("MINIQMT_HISTORY_INSTRUMENTS_UNRESOLVED")
                self._persist_history(
                    selected,
                    timeframe=request["timeframe"],
                    start_at=datetime.fromisoformat(request["start_at"]),
                    end_at=datetime.fromisoformat(request["end_at"]),
                )
            completed = self._request(
                "POST",
                "/api/v1/miniqmt/agent/history/complete",
                json={"request_id": request_id},
            )
            completed.raise_for_status()
        except Exception as exc:
            LOGGER.exception("MiniQMT history request failed and will be rotated")
            try:
                failed = self._request(
                    "POST",
                    "/api/v1/miniqmt/agent/history/fail",
                    json={
                        "request_id": request_id,
                        "error_code": getattr(exc, "code", type(exc).__name__),
                        "error_message": str(exc)[:512],
                    },
                )
                failed.raise_for_status()
            except Exception:
                # The request is still at the queue head when failure reporting
                # cannot reach the API, so it will survive an agent restart.
                LOGGER.exception("Unable to rotate failed MiniQMT history request")
            if not self._provider.connected:
                # XtQuant history downloads have no native deadline.  The
                # provider deliberately drops its connection state after our
                # watchdog cancels a stalled call; reconnect here before the
                # next queue item so one timeout cannot make every following
                # workflow fail immediately with MINIQMT_NOT_CONNECTED.
                self._provider.connect()
        return True

    def _report_status(
        self,
        state: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        try:
            self._request(
                "POST",
                "/api/v1/miniqmt/agent/status",
                json={
                    "state": state,
                    "checked_at": datetime.now(UTC).isoformat(),
                    "agent_version": AGENT_VERSION,
                    "last_market_time": self._last_market_time,
                    "last_received_at": self._last_received_at,
                    "last_minute_bar_time": self._last_minute_bar_time,
                    "last_catalog_sync_at": self._last_catalog_sync_at,
                    "catalog_instrument_count": self._catalog_instrument_count,
                    "error_code": error_code,
                    "error_message": error_message,
                },
            ).raise_for_status()
        except Exception:
            LOGGER.warning("Unable to report MiniQMT agent status", exc_info=True)

    @staticmethod
    def _json_values(values: dict[str, object]) -> dict[str, object]:
        return {
            key: (
                value.isoformat()
                if isinstance(value, datetime)
                else str(value)
                if hasattr(value, "as_tuple")
                else value
            )
            for key, value in values.items()
        }

    @staticmethod
    def _trading_status(value: object) -> str:
        values: dict[object, str] = {
            0: "TRADING",
            1: "HALTED",
            2: "CLOSED",
            3: "TRADING",
        }
        return values.get(value, "UNKNOWN")

    @staticmethod
    def _qmt_time(value: str) -> str:
        return datetime.fromisoformat(value).astimezone(SHANGHAI).strftime("%Y%m%d%H%M%S")

    def reject_message(self, message: object) -> None:
        """An explicit proof that no order-like message can reach XtQuant."""
        self._provider.reject_trading_command(message)
