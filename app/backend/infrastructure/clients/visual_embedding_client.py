from __future__ import annotations

import httpx

from app.backend.config import Settings


class VisualEmbeddingClient:
    """Shared HTTP connection for the optional visual embedding service."""

    def __init__(self, http_client: httpx.AsyncClient, model: str) -> None:
        self.http_client = http_client
        self.model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "VisualEmbeddingClient | None":
        if not settings.visual_embedding_enabled:
            return None

        headers: dict[str, str] = {}
        if settings.visual_embedding_api_key:
            headers["Authorization"] = (
                f"Bearer {settings.visual_embedding_api_key.get_secret_value()}"
            )

        return cls(
            http_client=httpx.AsyncClient(
                base_url=settings.visual_embedding_base_url.rstrip("/") + "/",
                headers=headers,
                timeout=settings.visual_embedding_timeout_seconds,
                trust_env=False,
            ),
            model=settings.visual_embedding_model,
        )

    async def probe(self) -> None:
        """Call the visual service's expected lightweight GET /health endpoint."""

        response = await self.http_client.get("health")
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            try:
                payload = response.json()
            except ValueError as error:
                raise ValueError(
                    "视觉嵌入健康检查返回的 JSON 无效。"
                ) from error
            if not isinstance(payload, dict):
                raise ValueError(
                    "视觉嵌入健康检查返回的对象格式不正确。"
                )

    async def close(self) -> None:
        await self.http_client.aclose()
