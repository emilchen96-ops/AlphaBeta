"""Compose API and system routes without crossing domain boundaries."""

from fastapi import APIRouter

from alphadesk_api.api.v1 import (
    accounts,
    health,
    instruments,
    market_data,
    orders,
    strategies,
    system,
    watchlists,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(instruments.router)
api_router.include_router(watchlists.router)
api_router.include_router(market_data.router)
api_router.include_router(accounts.router)
api_router.include_router(orders.router)
api_router.include_router(strategies.router)

health_router = APIRouter()
health_router.include_router(health.router)
