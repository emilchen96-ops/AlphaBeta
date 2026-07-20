"""Compose API and system routes without crossing domain boundaries."""

from fastapi import APIRouter

from alphadesk_api.api.v1 import (
    accounts,
    ai_research,
    backtests,
    health,
    information,
    instruments,
    market_data,
    orders,
    risk,
    scanners,
    simulated_executions,
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
api_router.include_router(simulated_executions.router)
api_router.include_router(risk.router)
api_router.include_router(strategies.router)
api_router.include_router(scanners.router)
api_router.include_router(information.router)
api_router.include_router(ai_research.router)
api_router.include_router(backtests.router)

health_router = APIRouter()
health_router.include_router(health.router)
