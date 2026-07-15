"""Liveness and readiness endpoints."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from alphadesk_api.schemas.system import LiveResponse, ReadyResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LiveResponse)
async def live(request: Request) -> LiveResponse:
    settings = request.app.state.settings
    return LiveResponse(
        status="alive",
        service=settings.app_name,
        version=settings.app_version,
        timestamp=datetime.now(UTC),
    )


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request) -> ReadyResponse | JSONResponse:
    database_ok, redis_ok = await asyncio.gather(
        request.app.state.database.ping(),
        request.app.state.redis.ping(),
    )
    payload = ReadyResponse(
        status="ready" if database_ok and redis_ok else "not_ready",
        postgresql="online" if database_ok else "offline",
        redis="online" if redis_ok else "offline",
        timestamp=datetime.now(UTC),
    )
    if database_ok and redis_ok:
        return payload
    return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))
