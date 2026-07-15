"""Compose API and system routes without crossing domain boundaries."""

from fastapi import APIRouter

from alphadesk_api.api.v1 import health, system

api_router = APIRouter()
api_router.include_router(system.router)

health_router = APIRouter()
health_router.include_router(health.router)
