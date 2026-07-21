"""U01 demo initialization and verification HTTP schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, model_validator


class DemoInitializeRequest(BaseModel):
    mode: Literal["fixture", "existing-data"] = "existing-data"
    reset_demo: bool = False
    confirm_reset: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def require_reset_confirmation(self) -> "DemoInitializeRequest":
        if self.reset_demo and not self.confirm_reset:
            raise ValueError("confirm_reset=true is required when reset_demo=true")
        return self


class DemoStepResponse(BaseModel):
    key: str
    status: str
    message: str
    entity_id: UUID | None = None
    replayed: bool = False


class DemoInitializationResponse(BaseModel):
    status: str
    mode: str
    dry_run: bool
    steps: list[DemoStepResponse]
    required_actions: list[str]


class VerificationItemResponse(BaseModel):
    key: str
    label: str
    status: str
    reason: str
    evidence: dict[str, object]
    required_actions: list[str]
    link: str | None = None
    available: bool
    checked_at: datetime


class ResearchVerificationResponse(BaseModel):
    status: str
    generated_at: datetime
    items: list[VerificationItemResponse]
