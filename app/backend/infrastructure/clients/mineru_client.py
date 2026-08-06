from __future__ import annotations

import httpx

from app.backend.config import Settings


class MinerUProtocolError(RuntimeError):
    """Raised when the MinerU health response is invalid."""


class MinerUClient:
    """Shared HTTP connection for the MinerU parsing service."""

    def __init__(self, http_client: httpx.AsyncClient, mode: str) -> None:
        self.http_client = http_client
        self.mode = mode

    @classmethod
    def from_settings(cls, settings: Settings) -> "MinerUClient":
        if settings.mineru_mode == "cloud_api":
            base_url = settings.mineru_api_base
            assert base_url is not None
            assert settings.mineru_api_token is not None
            headers = {
                "Authorization": f"Bearer {settings.mineru_api_token.get_secret_value()}"
            }
        else:
            base_url = settings.mineru_base_url
            headers = {}

        return cls(
            http_client=httpx.AsyncClient(
                base_url=base_url.rstrip("/") + "/",
                headers=headers,
                timeout=settings.mineru_timeout_seconds,
                trust_env=False,
            ),
            mode=settings.mineru_mode,
        )

    async def probe(self) -> None:
        """Call MinerU's documented lightweight GET /health endpoint."""

        response = await self.http_client.get("health")
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as error:
            raise MinerUProtocolError("MinerU health endpoint returned non-JSON content.") from error

        if not isinstance(payload, dict):
            raise MinerUProtocolError("MinerU health endpoint returned an invalid JSON object.")

    async def close(self) -> None:
        await self.http_client.aclose()
