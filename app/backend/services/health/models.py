"""健康检查领域模型及公开就绪视图，由服务和路由共同使用。"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict


ComponentStatus = Literal["ok", "error", "disabled", "unchecked"]
HealthStatus = Literal["ready", "not_ready"]

@dataclass(frozen=True, slots=True)
class ComponentCheckResult:
    status: ComponentStatus
    required: bool
    probe: str
    latency_ms: float
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    status: HealthStatus
    checked_at: datetime
    components: dict[str, ComponentCheckResult]


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
