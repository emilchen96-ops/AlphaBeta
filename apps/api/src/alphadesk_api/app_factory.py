"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from alphadesk_api.api.v1.router import api_router, health_router
from alphadesk_api.api.v1.system import system_websocket
from alphadesk_api.core.config import Settings, get_settings
from alphadesk_api.core.errors import register_exception_handlers
from alphadesk_api.core.logging import configure_logging
from alphadesk_api.core.middleware import CorrelationIdMiddleware
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.infrastructure.redis import RedisService


class ManagedProbe(Protocol):
    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


def create_app(
    settings: Settings | None = None,
    *,
    database: ManagedProbe | None = None,
    redis_service: ManagedProbe | None = None,
) -> FastAPI:
    """Build an independently testable API application."""

    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    database_service = database or DatabaseService(resolved_settings)
    resolved_redis_service = redis_service or RedisService(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved_settings
        app.state.database = database_service
        app.state.redis = resolved_redis_service
        try:
            yield
        finally:
            await resolved_redis_service.close()
            await database_service.close()

    app = FastAPI(
        title="AlphaDesk API",
        summary="M01 local infrastructure API; no trading capability",
        description=(
            "Local-development infrastructure endpoints only. No market data, strategy, "
            "order, broker, or real-trading capability is implemented."
        ),
        version=resolved_settings.app_version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.database = database_service
    app.state.redis = resolved_redis_service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", resolved_settings.correlation_id_header],
        expose_headers=[resolved_settings.correlation_id_header],
    )
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name=resolved_settings.correlation_id_header,
    )
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router, prefix=resolved_settings.api_prefix)
    # WebSocket stays outside the versioned HTTP prefix and is display-only.
    app.add_api_websocket_route("/ws/system", system_websocket)
    return app
