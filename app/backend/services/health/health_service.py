from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from app.backend.config import Settings


from app.backend.services.health.models import ComponentCheckResult, HealthCheckResult

logger = logging.getLogger(__name__)


class HealthService:
    """Execute one real, bounded probe for every enabled dependency."""

    def __init__(self, *, resources: Mapping[str, Any], ready: bool, settings: Settings) -> None:
        self.resources = resources
        self.ready = ready
        self.settings = settings

    async def check(self, *, include_optional: bool = True) -> HealthCheckResult:
        """Probe required dependencies, optionally including diagnostic-only components."""

        application_ready = self.ready
        components: dict[str, ComponentCheckResult] = {
            "application": ComponentCheckResult(
                status="ok" if application_ready else "error",
                required=True,
                probe="lifespan_ready_flag",
                latency_ms=0.0,
                error_type=None if application_ready else "LifespanNotReady",
            )
        }

        probes = {
            "filesystem": ("file_store", "check_writable", "create_write_read_delete_temp_file"),
            "sqlite": ("metadata_store", "ping", "select_1"),
            "qdrant": ("vector_store", "ping", "qdrant_collections_and_dimensions"),
            "text_embedding": ("text_embedding_client", "probe", "real_embedding_request"),
            "reranker": ("reranker_client", "probe", "real_reranker_request"),
            "mineru": ("mineru_client", "probe", "mineru_health_request"),
            "llm": ("llm_client", "probe", "minimal_chat_completion"),
        }
        if self.settings.visual_embedding_enabled:
            probes["visual_embedding"] = ("visual_embedding_client", "probe", "visual_embedding_health_request")
        else:
            components["visual_embedding"] = ComponentCheckResult(
                status="disabled",
                required="visual_embedding" in self.settings.health_required_components,
                probe="disabled_by_configuration",
                latency_ms=0.0,
            )

        checks = {
            name: self.probe_state_resource(
                component=name, state_name=resource, probe_name=method, probe=description,
                required=name in self.settings.health_required_components,
                include_optional=include_optional,
            )
            for name, (resource, method, description) in probes.items()
        }
        results = await asyncio.gather(*checks.values())
        components.update(zip(checks, results, strict=True))

        required_components_ok = all(component.status == "ok" for component in components.values() if component.required)

        return HealthCheckResult(
            status="ready" if required_components_ok else "not_ready",
            checked_at=datetime.now(timezone.utc),
            components=components,
        )

    async def probe_state_resource(self, *, component: str, state_name: str, probe_name: str, probe: str, required: bool, include_optional: bool = True) -> ComponentCheckResult:
        """Resolve one lifespan resource and execute its real probe method."""

        if not required and not include_optional:
            return ComponentCheckResult(status="unchecked", required=False, probe="not_probed_for_readiness", latency_ms=0.0)
        resource = self.resources.get(state_name)
        if resource is None:
            return ComponentCheckResult(
                status="error",
                required=required,
                probe=probe,
                latency_ms=0.0,
                error_type="ResourceNotInitialized",
                error_message=f"服务资源尚未初始化：{state_name}",
            )

        operation = getattr(resource, probe_name, None)
        if operation is None or not callable(operation):
            return ComponentCheckResult(
                status="error",
                required=required,
                probe=probe,
                latency_ms=0.0,
                error_type=f"ProbeMethodMissing:{state_name}.{probe_name}",
                error_message=f"健康检查方法不可调用：{state_name}.{probe_name}",
            )

        return await self.run_probe(component=component, operation=operation, probe=probe, required=required, include_optional=include_optional)

    async def run_probe(self, *, component: str, operation: Callable[[], Awaitable[None]], probe: str, required: bool, include_optional: bool = True) -> ComponentCheckResult:
        """Execute one probe with a hard timeout and normalize its result."""

        if not required and not include_optional:
            return ComponentCheckResult(status="unchecked", required=False, probe="not_probed_for_readiness", latency_ms=0.0)
        started_at = perf_counter()
        try:
            await asyncio.wait_for(operation(), timeout=self.settings.health_probe_timeout_seconds)
        except TimeoutError:
            return ComponentCheckResult(
                status="error",
                required=required,
                probe=probe,
                latency_ms=self.elapsed_ms(started_at),
                error_type="ProbeTimeout",
                error_message=f"健康检查超时，已超过 {self.settings.health_probe_timeout_seconds} 秒。",
            )
        except Exception as error:
            root_error = root_cause(error)
            logger.warning(
                "组件%s 健康检查失败 探针%s 目标%s 错误%s:%s 根因%s:%s 上下文:%s",
                component,
                probe,
                probe_target(operation),
                type(error).__name__,
                str(error),
                type(root_error).__name__,
                str(root_error),
                getattr(error, "context", {}),
                exc_info=True,
            )
            return ComponentCheckResult(
                status="error",
                required=required,
                probe=probe,
                latency_ms=self.elapsed_ms(started_at),
                error_type=type(error).__name__,
                error_message="组件检查失败，请查看服务日志",
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


def root_cause(error: BaseException) -> BaseException:
    current = error
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        next_error = current.__cause__ or current.__context__
        if next_error is None:
            break
        current = next_error
    return current


def probe_target(operation: Callable[[], Awaitable[None]]) -> str:
    target = getattr(operation, "__self__", None)
    if target is None:
        return "-"

    endpoint = getattr(target, "endpoint", None)
    if isinstance(endpoint, str) and endpoint:
        return endpoint

    http_client = getattr(target, "http_client", None)
    base_url: Any = getattr(http_client, "base_url", None)
    if base_url is not None:
        return str(base_url)

    path = getattr(target, "path", None)
    if path is not None:
        return str(path)

    settings = getattr(target, "settings", None)
    if settings is not None and getattr(settings, "qdrant_mode", None) == "server":
        return str(getattr(settings, "qdrant_url", "-") or "-")
    if settings is not None and getattr(settings, "qdrant_mode", None) == "local":
        return str(settings.project_path(settings.qdrant_path))

    return target.__class__.__name__
