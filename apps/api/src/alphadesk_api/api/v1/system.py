"""System status HTTP and WebSocket endpoints."""

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from alphadesk_api.schemas.system import SystemStatusResponse, WebSocketMessage

LOGGER = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=SystemStatusResponse)
async def system_status(request: Request) -> SystemStatusResponse:
    database_ok, redis_ok = await asyncio.gather(
        request.app.state.database.ping(),
        request.app.state.redis.ping(),
    )
    settings = request.app.state.settings
    return SystemStatusResponse(
        api="online",
        postgresql="online" if database_ok else "offline",
        redis="online" if redis_ok else "offline",
        environment=settings.environment,
        version=settings.app_version,
        server_time=datetime.now(UTC),
        correlation_id=request.state.correlation_id,
    )


async def system_websocket(websocket: WebSocket) -> None:
    """Validate display-only realtime connectivity; never carry trade commands."""

    await websocket.accept()
    settings = websocket.app.state.settings
    await websocket.send_json(
        WebSocketMessage(type="connected", timestamp=datetime.now(UTC)).model_dump(mode="json")
    )
    try:
        while True:
            message = await websocket.receive_text()
            if len(message.encode("utf-8")) > settings.max_websocket_message_bytes:
                await websocket.send_json(
                    WebSocketMessage(
                        type="error",
                        message="Message is too large",
                        timestamp=datetime.now(UTC),
                    ).model_dump(mode="json")
                )
                await websocket.close(code=1009)
                return
            if message.strip().lower() != "ping":
                await websocket.send_json(
                    WebSocketMessage(
                        type="error",
                        message="Only the display-channel ping message is supported",
                        timestamp=datetime.now(UTC),
                    ).model_dump(mode="json")
                )
                continue
            await websocket.send_json(
                WebSocketMessage(type="pong", timestamp=datetime.now(UTC)).model_dump(mode="json")
            )
    except WebSocketDisconnect:
        LOGGER.info("System WebSocket client disconnected")
