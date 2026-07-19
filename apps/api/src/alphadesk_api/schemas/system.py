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


class CapabilityDataCountsResponse(BaseModel):
    instrument_count: int | None = None
    market_bar_count: int | None = None
    daily_market_bar_count: int | None = None
    market_bar_instrument_count: int | None = None
    earliest_market_bar_at: datetime | None = None
    latest_market_bar_at: datetime | None = None
    simulated_account_count: int | None = None
    scan_run_count: int | None = None
    strategy_run_count: int | None = None
    strategy_experiment_count: int | None = None
    information_source_count: int | None = None
    information_item_count: int | None = None
    market_event_count: int | None = None
    ai_analysis_run_count: int | None = None
    order_count: int | None = None
    executable_order_count: int | None = None
    fill_count: int | None = None
    risk_decision_count: int | None = None


class SystemCapabilityResponse(BaseModel):
    module_key: str
    implementation_status: Literal["WORKING", "PARTIAL", "PLACEHOLDER", "NOT_IMPLEMENTED"]
    data_status: Literal["READY", "MISSING", "DISABLED", "NOT_REQUIRED", "UNKNOWN"]
    configuration_status: Literal["READY", "MISSING", "DISABLED", "NOT_REQUIRED", "UNKNOWN"]
    available: bool
    reason: str
    required_actions: list[str]


class SystemCapabilitiesResponse(BaseModel):
    generated_at: datetime
    database_reachable: bool
    counts: CapabilityDataCountsResponse
    items: list[SystemCapabilityResponse]


class WebSocketMessage(BaseModel):
    type: Literal["connected", "pong", "error"]
    timestamp: datetime
    message: str | None = None
