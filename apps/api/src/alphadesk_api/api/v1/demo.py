"""Development/test-only U01 research demo endpoints."""

import asyncio
from dataclasses import asdict
from typing import cast

from fastapi import APIRouter, Request

from alphadesk_api.application.common import ApplicationError, UnitOfWorkFactory
from alphadesk_api.application.demo import (
    ResearchDemoInitializationService,
    ResearchDemoVerificationService,
)
from alphadesk_api.infrastructure.database import DatabaseService
from alphadesk_api.schemas.demo import (
    DemoInitializationResponse,
    DemoInitializeRequest,
    ResearchVerificationResponse,
)

router = APIRouter(prefix="/demo", tags=["demo"])


def _guard_request(request: Request) -> None:
    if request.app.state.settings.environment not in ("development", "test"):
        raise ApplicationError("DEMO_DISABLED", "demo endpoints require development/test")


def _factory(request: Request) -> UnitOfWorkFactory:
    database = request.app.state.database
    if not isinstance(database, DatabaseService):
        raise ApplicationError("DEMO_DATABASE_UNAVAILABLE", "demo requires PostgreSQL")
    return cast(UnitOfWorkFactory, database.unit_of_work)


async def _verification(request: Request) -> ResearchVerificationResponse:
    _guard_request(request)
    postgresql_ok, redis_ok = await asyncio.gather(
        request.app.state.database.ping(), request.app.state.redis.ping()
    )
    result = await ResearchDemoVerificationService(
        request.app.state.capability_data_provider,
        request.app.state.settings,
        postgresql_ok=postgresql_ok,
        redis_ok=redis_ok,
    ).verify()
    return ResearchVerificationResponse(**asdict(result))


@router.post("/initialize-research", response_model=DemoInitializationResponse)
async def initialize_research(
    payload: DemoInitializeRequest, request: Request
) -> DemoInitializationResponse:
    _guard_request(request)
    service = ResearchDemoInitializationService(
        _factory(request),
        request.app.state.strategy_registry,
        request.app.state.scanner_registry,
        request.app.state.settings,
    )
    result = await service.initialize(
        mode=payload.mode,
        reset_demo=payload.reset_demo,
        dry_run=payload.dry_run,
    )
    return DemoInitializationResponse(**asdict(result))


@router.get("/research-status", response_model=ResearchVerificationResponse)
async def research_status(request: Request) -> ResearchVerificationResponse:
    return await _verification(request)


@router.post("/verify-research", response_model=ResearchVerificationResponse)
async def verify_research(request: Request) -> ResearchVerificationResponse:
    return await _verification(request)
