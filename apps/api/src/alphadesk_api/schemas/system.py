"""Health and system status response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LiveResponse(BaseModel):
    status: Literal["alive"]
    service: str
    version: str
    timestamp: datetime


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    postgresql: Literal["online", "offline"]
    redis: Literal["online", "offline"]
    timestamp: datetime


class SystemStatusResponse(BaseModel):
    api: Literal["online"]
    postgresql: Literal["online", "offline"]
    redis: Literal["online", "offline"]
    environment: str
    version: str
    server_time: datetime
    correlation_id: str


class WebSocketMessage(BaseModel):
    type: Literal["connected", "pong", "error"]
    timestamp: datetime
    message: str | None = None
