"""Versioned market-data WebSocket with one Redis listener per API process."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from alphadesk_api.core.config import Settings
from alphadesk_api.infrastructure.free_market_cache import (
    QUOTE_CHANNEL,
    QuoteCache,
    quote_payload,
)


@dataclass(slots=True)
class ClientState:
    queue: asyncio.Queue[dict[str, Any]]
    subscriptions: set[UUID] = field(default_factory=set)
    dropped_messages: int = 0


class MarketDataWebSocketHub:
    def __init__(self, client: Redis, settings: Settings) -> None:
        self._redis = client
        self._settings = settings
        self._clients: dict[UUID, ClientState] = {}
        self._listener_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._listener_task is None:
            self._listener_task = asyncio.create_task(self._listen(), name="market-redis-listener")
            self._heartbeat_task = asyncio.create_task(self._heartbeat(), name="market-heartbeat")

    async def stop(self) -> None:
        self._stopping.set()
        for task in (self._listener_task, self._heartbeat_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    def register(self) -> tuple[UUID, ClientState]:
        client_id = uuid4()
        state = ClientState(queue=asyncio.Queue(self._settings.free_market_websocket_queue_size))
        self._clients[client_id] = state
        return client_id, state

    def unregister(self, client_id: UUID) -> None:
        self._clients.pop(client_id, None)

    def update_subscriptions(
        self, state: ClientState, ids: set[UUID], *, replace: bool = False, remove: bool = False
    ) -> None:
        if replace:
            state.subscriptions = ids
        elif remove:
            state.subscriptions.difference_update(ids)
        else:
            state.subscriptions.update(ids)

    def enqueue(self, state: ClientState, event: dict[str, Any]) -> None:
        if state.queue.full():
            with suppress(asyncio.QueueEmpty):
                state.queue.get_nowait()
            state.dropped_messages += 1
        state.queue.put_nowait(event)

    async def _listen(self) -> None:
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(QUOTE_CHANNEL)
        try:
            while not self._stopping.is_set():
                message = await pubsub.get_message(timeout=1.0)
                if message is None:
                    continue
                try:
                    event = json.loads(str(message["data"]))
                    instrument_id = (
                        UUID(event["instrument_id"])
                        if event.get("type") == "quote_update"
                        else None
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError, AttributeError):
                    continue
                for state in tuple(self._clients.values()):
                    if instrument_id is None or instrument_id in state.subscriptions:
                        self.enqueue(state, event)
        finally:
            close_pubsub = cast(Callable[[], Awaitable[Any]], pubsub.aclose)
            await close_pubsub()

    async def _heartbeat(self) -> None:
        while not self._stopping.is_set():
            await asyncio.sleep(self._settings.websocket_heartbeat_seconds)
            event = {
                "schema_version": 1,
                "type": "heartbeat",
                "server_time": datetime.now(UTC).isoformat(),
            }
            for state in tuple(self._clients.values()):
                self.enqueue(state, event)


async def market_data_websocket(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        await websocket.close(code=1008, reason="origin not allowed")
        return
    hub: MarketDataWebSocketHub | None = getattr(websocket.app.state, "market_ws_hub", None)
    if hub is None:
        await websocket.close(code=1013, reason="realtime cache unavailable")
        return
    await websocket.accept()
    client_id, state = hub.register()
    cache = QuoteCache(websocket.app.state.redis.client, settings.miniqmt_quote_ttl_seconds)
    hub.enqueue(
        state,
        {
            "schema_version": 1,
            "type": "connected",
            "client_id": str(client_id),
            "server_time": datetime.now(UTC).isoformat(),
            "usage": ["RESEARCH_ONLY", "NON_TRADING_GRADE"],
        },
    )

    async def sender() -> None:
        while True:
            event = await state.queue.get()
            if state.dropped_messages:
                event = {**event, "dropped_messages": state.dropped_messages}
                state.dropped_messages = 0
            await websocket.send_json(event)

    send_task = asyncio.create_task(sender())
    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw.encode()) > settings.max_websocket_message_bytes:
                hub.enqueue(
                    state, {"schema_version": 1, "type": "error", "code": "MESSAGE_TOO_LARGE"}
                )
                continue
            try:
                message = json.loads(raw)
                message_type = message.get("type")
                ids = {UUID(item) for item in message.get("instrument_ids", [])}
            except (TypeError, ValueError, json.JSONDecodeError):
                hub.enqueue(
                    state, {"schema_version": 1, "type": "error", "code": "INVALID_MESSAGE"}
                )
                continue
            if len(ids) > settings.free_market_max_subscriptions_per_client:
                hub.enqueue(
                    state, {"schema_version": 1, "type": "error", "code": "SUBSCRIPTION_LIMIT"}
                )
                continue
            if message_type in {"hello", "subscribe"}:
                hub.update_subscriptions(state, ids, replace=message_type == "hello")
                snapshots = await cache.get_many(list(ids))
                hub.enqueue(
                    state,
                    {
                        "schema_version": 1,
                        "type": "subscription_ack",
                        "instrument_ids": [
                            str(item) for item in sorted(state.subscriptions, key=str)
                        ],
                    },
                )
                if snapshots:
                    hub.enqueue(
                        state,
                        {
                            "schema_version": 1,
                            "type": "quote_snapshot",
                            "items": [
                                {
                                    **quote_payload(item.quote),
                                    "revision": item.revision.revision,
                                }
                                for item in snapshots
                            ],
                        },
                    )
            elif message_type == "unsubscribe":
                hub.update_subscriptions(state, ids, remove=True)
                hub.enqueue(
                    state,
                    {
                        "schema_version": 1,
                        "type": "subscription_ack",
                        "instrument_ids": [
                            str(item) for item in sorted(state.subscriptions, key=str)
                        ],
                    },
                )
            elif message_type == "ping":
                hub.enqueue(
                    state,
                    {
                        "schema_version": 1,
                        "type": "pong",
                        "server_time": datetime.now(UTC).isoformat(),
                    },
                )
            else:
                hub.enqueue(state, {"schema_version": 1, "type": "error", "code": "UNKNOWN_TYPE"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(client_id)
        send_task.cancel()
        with suppress(asyncio.CancelledError):
            await send_task
