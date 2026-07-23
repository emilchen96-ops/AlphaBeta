"""System status HTTP and WebSocket endpoints."""

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from alphadesk_api.application.system_capabilities import (
    SystemCapability,
    assess_system_capabilities,
)
from alphadesk_api.infrastructure.ai_research_provider import describe_ai_provider
from alphadesk_api.schemas.system import (
    CapabilityDataCountsResponse,
    SystemCapabilitiesResponse,
    SystemCapabilityResponse,
    SystemStatusResponse,
    WebSocketMessage,
)

LOGGER = logging.getLogger(__name__)
router = APIRouter(tags=["system"])
Availability = Literal[
    "READY",
    "NEEDS_DATA",
    "NEEDS_CONFIG",
    "DEMO_ONLY",
    "DISABLED",
    "PARTIAL",
    "NOT_IMPLEMENTED",
    "AVAILABLE",
    "DEGRADED",
    "NOT_AVAILABLE",
]


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
    ai_snapshot = describe_ai_provider(selected_provider)
    replay_worker_available = False
    miniqmt_agent_connected = False
    try:
        replay_worker_available = bool(
            await request.app.state.redis.client.get("alphadesk:replays:v1:worker:heartbeat")
        )
    except Exception:
        replay_worker_available = False
    try:
        miniqmt_status = await request.app.state.redis.client.get(
            "alphadesk:miniqmt:v1:agent:status"
        )
        if miniqmt_status:
            miniqmt_agent_connected = json.loads(str(miniqmt_status)).get("state") == "CONNECTED"
    except Exception:
        miniqmt_agent_connected = False
    items = assess_system_capabilities(
        request.app.state.settings,
        data,
        ai_provider_configured=selected_provider.configured,
        ai_provider_key=selected_provider.provider_key,
        ai_provider_available=ai_snapshot.available,
        ai_provider_mode=ai_snapshot.mode,
        replay_worker_available=replay_worker_available,
        miniqmt_agent_connected=miniqmt_agent_connected,
    )
    count_fields = {name: getattr(data, name) for name in CapabilityDataCountsResponse.model_fields}

    def response_item(item: SystemCapability) -> SystemCapabilityResponse:
        raw = asdict(item)
        module_key = raw["module_key"]
        availability: Availability
        provider: str | None
        mode: str
        if module_key == "ai_research":
            provider_availability = {
                "FAKE": "DEMO_ONLY",
                "REAL_AVAILABLE": "AVAILABLE" if raw["available"] else "DEGRADED",
                "REAL_CONFIGURED": "DEGRADED",
                "REAL_UNAVAILABLE": "DEGRADED",
                "DISABLED": "NOT_AVAILABLE",
            }[ai_snapshot.mode]
            availability = cast(Availability, provider_availability)
            provider = ai_snapshot.provider_key
            mode = ai_snapshot.mode
        elif module_key in {
            "trading_calendar",
            "adjustment_factors",
            "suspension_data",
            "instrument_lifecycle",
            "adjusted_strategy_data",
        }:
            provider_by_module = {
                "trading_calendar": request.app.state.settings.market_calendar_provider,
                "adjustment_factors": request.app.state.settings.market_adjustment_provider,
                "suspension_data": request.app.state.settings.market_suspension_provider,
                "instrument_lifecycle": request.app.state.settings.market_suspension_provider,
                "adjusted_strategy_data": request.app.state.settings.market_adjustment_provider,
            }
            provider = provider_by_module[module_key]
            availability = "READY" if raw["available"] else "NEEDS_DATA"
            mode = "LOCAL_REFERENCE"
        elif module_key == "miniqmt_trading":
            availability = "NOT_AVAILABLE"
            provider = "MINIQMT"
            mode = "READ_ONLY"
        elif raw["implementation_status"] == "NOT_IMPLEMENTED":
            availability = "NOT_IMPLEMENTED"
            provider = None
            mode = "PLANNED"
        elif raw["implementation_status"] == "PARTIAL" and module_key == "audit":
            availability = "PARTIAL"
            provider = "postgresql"
            mode = "READ_ONLY"
        elif raw["configuration_status"] == "DISABLED":
            availability = "DISABLED"
            provider = request.app.state.settings.realtime_market_provider
            mode = "DISABLED"
        elif module_key in {
            "realtime_market_data",
            "miniqmt_market_data",
            "realtime_quotes",
            "market_subscription",
            "intraday_persistence",
        }:
            availability = "AVAILABLE" if raw["available"] else "DEGRADED"
            provider = "MINIQMT"
            mode = "READ_ONLY"
        elif raw["available"]:
            availability = "READY"
            provider = "postgresql"
            mode = "LOCAL"
        elif raw["data_status"] in ("MISSING", "UNKNOWN"):
            availability = "NEEDS_DATA"
            provider = "postgresql"
            mode = "LOCAL"
        else:
            availability = "NEEDS_CONFIG"
            provider = None
            mode = "LOCAL"
        last_success_at = (
            ai_snapshot.last_success_at
            if module_key == "ai_research"
            else (
                data.latest_market_bar_at
                if module_key
                in {
                    "historical_market_data",
                    "scanner",
                    "strategy_research",
                    "strategy_experiments",
                    "daily_backtest",
                    "historical_replay",
                }
                else None
            )
        )
        return SystemCapabilityResponse(
            **raw,
            availability=availability,
            last_success_at=last_success_at,
            provider=provider,
            provider_status=(
                "READY"
                if raw["configuration_status"] == "READY"
                else ("DISABLED" if raw["configuration_status"] == "DISABLED" else "MISSING")
            ),
            mode=mode,
        )

    return SystemCapabilitiesResponse(
        generated_at=datetime.now(UTC),
        database_reachable=data.database_reachable,
        counts=CapabilityDataCountsResponse(**count_fields),
        items=[response_item(item) for item in items],
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
