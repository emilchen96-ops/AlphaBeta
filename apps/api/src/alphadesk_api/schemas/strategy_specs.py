"""HTTP contracts for the UX02 strategy builder."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrategyTextParseBody(StrictBody):
    text: str = Field(min_length=1, max_length=1000)


class StrategySpecBody(StrictBody):
    spec: dict[str, Any]


class StrategyParseResponse(BaseModel):
    status: str
    parser_source: str
    spec: dict[str, Any] | None
    preview: list[str]
    warnings: list[str]
    missing_fields: list[str]
    ai_assistance: str


class StrategyValidationResponse(BaseModel):
    valid: bool
    spec: dict[str, Any]
    preview: list[str]
    compiled_strategy_key: str


class StrategyPreviewResponse(BaseModel):
    preview: list[str]


class StrategyTemplateResponse(BaseModel):
    key: str
    name: str
    description: str
    category: str
    spec: dict[str, Any] | None
    preview: list[str]
    recommended: bool


class UserStrategyWriteBody(StrictBody):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    spec: dict[str, Any]


class UserStrategyResponse(BaseModel):
    id: UUID
    name: str
    description: str
    current_version: int
    archived: bool
    spec: dict[str, Any]
    preview: list[str]
    created_at: datetime
    updated_at: datetime


class UserStrategyPageResponse(BaseModel):
    items: list[UserStrategyResponse]
    page: int
    page_size: int
    total: int
