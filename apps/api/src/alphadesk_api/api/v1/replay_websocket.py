"""Read-only RT01 WebSocket backed by committed PostgreSQL replay events."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect

from alphadesk_api.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


async def replay_websocket(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        await websocket.close(code=1008, reason="origin not allowed")
        return
    try:
        replay_id = UUID(websocket.path_params["replay_id"])
        after_sequence = max(int(websocket.query_params.get("after_sequence", "0")), 0)
    except (ValueError, TypeError):
        await websocket.close(code=1008, reason="invalid replay cursor")
        return
    database = websocket.app.state.database
    session_factory = getattr(database, "session_factory", None)
    if session_factory is None:
        await websocket.close(code=1013, reason="database unavailable")
        return
    await websocket.accept()
    try:
        while True:
            async with SqlAlchemyUnitOfWork(session_factory) as uow:
                run = await uow.replay_runs.get_by_id(replay_id)
                if run is None:
                    await websocket.send_json({"type": "error", "code": "REPLAY_NOT_FOUND"})
                    await websocket.close(code=1008)
                    return
                events, _ = await uow.replay_events.list_by_run(
                    replay_id, after_sequence=after_sequence, offset=0, limit=500
                )
            for event in events:
                await websocket.send_json(event.envelope())
                after_sequence = event.sequence_number
            if not events:
                await websocket.send_json(
                    {
                        "schema_version": 1,
                        "replay_id": str(replay_id),
                        "sequence_number": after_sequence,
                        "event_type": "HEARTBEAT",
                        "business_time": datetime.now(UTC).isoformat(),
                        "occurred_at": datetime.now(UTC).isoformat(),
                        "payload": {},
                    }
                )
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
