from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ComponentStatus = Literal["ok", "error", "disabled"]
HealthStatus = Literal["ready", "not_ready"]


class LivenessData(BaseModel):
    """Data contract for GET /health/live."""

    status: Literal["ok"]
    name: str
    version: str


class ReadinessComponentData(BaseModel):
    """Minimal component data for GET /health/ready."""

    model_config = ConfigDict(from_attributes=True)

    status: ComponentStatus
    required: bool


class ReadinessData(BaseModel):
    """Minimal readiness data used for traffic decisions."""

    model_config = ConfigDict(from_attributes=True)

    status: HealthStatus
    checked_at: datetime
    components: dict[str, ReadinessComponentData]


class DetailedComponentHealthData(BaseModel):
    """Diagnostic component data for GET /health/details."""

    model_config = ConfigDict(from_attributes=True)

    status: ComponentStatus
    required: bool
    probe: str
    latency_ms: float = Field(ge=0)
    error_type: str | None = None


class HealthDetailsData(BaseModel):
    """Restricted diagnostic data with safe probe metadata."""

    model_config = ConfigDict(from_attributes=True)

    status: HealthStatus
    checked_at: datetime
    components: dict[str, DetailedComponentHealthData]
