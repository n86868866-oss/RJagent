from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ComponentStatus = Literal["ok", "error", "disabled"]
HealthStatus = Literal["ready", "not_ready"]


class LivenessResponse(BaseModel):
    """Contract for GET /health/live."""

    status: Literal["ok"]
    name: str
    version: str


class ReadinessComponentResponse(BaseModel):
    """Minimal component contract for GET /health/ready."""

    model_config = ConfigDict(from_attributes=True)

    status: ComponentStatus
    required: bool


class ReadinessResponse(BaseModel):
    """Minimal readiness contract used for traffic decisions."""

    model_config = ConfigDict(from_attributes=True)

    status: HealthStatus
    checked_at: datetime
    components: dict[str, ReadinessComponentResponse]


class DetailedComponentHealthResponse(BaseModel):
    """Diagnostic component contract for GET /health/details."""

    model_config = ConfigDict(from_attributes=True)

    status: ComponentStatus
    required: bool
    probe: str
    latency_ms: float = Field(ge=0)
    error_type: str | None = None


class HealthDetailsResponse(BaseModel):
    """Restricted diagnostic contract with safe probe metadata."""

    model_config = ConfigDict(from_attributes=True)

    status: HealthStatus
    checked_at: datetime
    components: dict[str, DetailedComponentHealthResponse]
