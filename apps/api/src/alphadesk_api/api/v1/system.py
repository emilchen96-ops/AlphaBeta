"""System status HTTP and WebSocket endpoints."""

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from alphadesk_api.application.system_capabilities import assess_system_capabilities
from alphadesk_api.schemas.system import (
    CapabilityDataCountsResponse,
    SystemCapabilitiesResponse,
    SystemCapabilityResponse,
    SystemStatusResponse,
    WebSocketMessage,
)

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


@router.get("/system/capabilities", response_model=SystemCapabilitiesResponse)
async def system_capabilities(request: Request) -> SystemCapabilitiesResponse:
    """Report implementation, data and configuration readiness without secrets."""

    data = await request.app.state.capability_data_provider.snapshot()
    selected_provider = request.app.state.ai_research_provider
    items = assess_system_capabilities(
        request.app.state.settings,
        data,
        ai_provider_configured=selected_provider.configured,
        ai_provider_key=selected_provider.provider_key,
    )
    count_fields = {name: getattr(data, name) for name in CapabilityDataCountsResponse.model_fields}
    return SystemCapabilitiesResponse(
        generated_at=datetime.now(UTC),
        database_reachable=data.database_reachable,
        counts=CapabilityDataCountsResponse(**count_fields),
        items=[SystemCapabilityResponse(**asdict(item)) for item in items],
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
