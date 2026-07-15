"""Compose API and system routes without crossing domain boundaries."""

from fastapi import APIRouter

from alphadesk_api.api.v1 import health, instruments, market_data, system, watchlists

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(instruments.router)
api_router.include_router(watchlists.router)
api_router.include_router(market_data.router)

health_router = APIRouter()
health_router.include_router(health.router)
