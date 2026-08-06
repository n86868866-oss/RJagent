from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Literal

from fastapi import FastAPI

from app.backend.config import Settings
from app.backend.infrastructure.clients.pymupdf_client import PyMuPDFClient


ComponentStatus = Literal["ok", "error", "disabled"]
HealthStatus = Literal["ready", "not_ready"]

PROBE_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class ComponentCheckResult:
    status: ComponentStatus
    required: bool
    probe: str
    latency_ms: float
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    status: HealthStatus
    checked_at: datetime
    components: dict[str, ComponentCheckResult]


class HealthService:
    """Execute one real, bounded probe for every enabled dependency."""

    def __init__(self, app: FastAPI, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def check(self) -> HealthCheckResult:
        """Run a fresh full check and return the complete internal result."""

        application_ready = bool(getattr(self.app.state, "ready", False))
        components: dict[str, ComponentCheckResult] = {
            "application": ComponentCheckResult(
                status="ok" if application_ready else "error",
                required=True,
                probe="lifespan_ready_flag",
                latency_ms=0.0,
                error_type=None if application_ready else "LifespanNotReady",
            )
        }

        names = ("filesystem", "sqlite", "qdrant", "text_embedding", "mineru", "llm", "pymupdf")
        checks = (
            self.probe_state_resource(
                state_name="file_store",
                probe_name="check_writable",
                probe="create_write_read_delete_temp_file",
                required=True,
            ),
            self.probe_state_resource(
                state_name="metadata_store",
                probe_name="ping",
                probe="select_1",
                required=True,
            ),
            self.probe_state_resource(
                state_name="vector_store",
                probe_name="ping",
                probe="qdrant_collections_and_dimensions",
                required=True,
            ),
            self.probe_state_resource(
                state_name="text_embedding_client",
                probe_name="probe",
                probe="real_embedding_request",
                required=True,
            ),
            self.probe_state_resource(
                state_name="mineru_client",
                probe_name="probe",
                probe="mineru_health_request",
                required=True,
            ),
            self.probe_state_resource(
                state_name="llm_client",
                probe_name="probe",
                probe="minimal_chat_completion",
                required=True,
            ),
            self.run_probe(
                operation=PyMuPDFClient.probe,
                probe="create_serialize_reopen_pdf",
                required=True,
            ),
        )

        results = await asyncio.gather(*checks)
        components.update(dict(zip(names, results, strict=True)))

        if self.settings.visual_embedding_enabled:
            components["visual_embedding"] = await self.probe_state_resource(
                state_name="visual_embedding_client",
                probe_name="probe",
                probe="visual_embedding_health_request",
                required=True,
            )
        else:
            components["visual_embedding"] = ComponentCheckResult(
                status="disabled",
                required=False,
                probe="disabled_by_configuration",
                latency_ms=0.0,
            )

        required_components_ok = all(component.status == "ok" for component in components.values() if component.required)

        return HealthCheckResult(
            status="ready" if required_components_ok else "not_ready",
            checked_at=datetime.now(timezone.utc),
            components=components,
        )

    async def probe_state_resource(
        self,
        *,
        state_name: str,
        probe_name: str,
        probe: str,
        required: bool,
    ) -> ComponentCheckResult:
        """Resolve one lifespan resource and execute its real probe method."""

        resource = getattr(self.app.state, state_name, None)
        if resource is None:
            return ComponentCheckResult(
                status="error",
                required=required,
                probe=probe,
                latency_ms=0.0,
                error_type="ResourceNotInitialized",
            )

        operation = getattr(resource, probe_name, None)
        if operation is None or not callable(operation):
            return ComponentCheckResult(
                status="error",
                required=required,
                probe=probe,
                latency_ms=0.0,
                error_type=f"ProbeMethodMissing:{state_name}.{probe_name}",
            )

        return await self.run_probe(operation=operation, probe=probe, required=required)

    async def run_probe(
        self,
        *,
        operation: Callable[[], Awaitable[None]],
        probe: str,
        required: bool,
    ) -> ComponentCheckResult:
        """Execute one probe with a hard timeout and normalize its result."""

        started_at = perf_counter()
        try:
            await asyncio.wait_for(operation(), timeout=PROBE_TIMEOUT_SECONDS)
        except TimeoutError:
            return ComponentCheckResult(
                status="error",
                required=required,
                probe=probe,
                latency_ms=self.elapsed_ms(started_at),
                error_type="ProbeTimeout",
            )
        except Exception as error:
            return ComponentCheckResult(
                status="error",
                required=required,
                probe=probe,
                latency_ms=self.elapsed_ms(started_at),
                error_type=type(error).__name__,
            )

        return ComponentCheckResult(
            status="ok",
            required=required,
            probe=probe,
            latency_ms=self.elapsed_ms(started_at),
        )

    @staticmethod
    def elapsed_ms(started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 2)
