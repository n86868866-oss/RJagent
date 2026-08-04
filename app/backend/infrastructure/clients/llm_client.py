from __future__ import annotations

from typing import Any

from app.backend.config import Settings


class LLMProtocolError(RuntimeError):
    """Raised when an OpenAI-compatible LLM response is unusable."""


class LLMClient:
    """Shared OpenAI-compatible client for chat generation."""

    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMClient | None":
        if not settings.llm_base_url or not settings.llm_model or not settings.llm_api_key:
            return None

        try:
            from openai import AsyncOpenAI
        except ImportError as error:  # pragma: no cover - environment failure
            raise RuntimeError(
                "The openai package is required for the OpenAI-compatible LLM client."
            ) from error

        return cls(
            client=AsyncOpenAI(
                api_key=settings.llm_api_key.get_secret_value(),
                base_url=settings.llm_base_url.rstrip("/"),
                timeout=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
            ),
            model=settings.llm_model,
        )

    async def probe(self) -> None:
        """Make one minimal real chat-completion request."""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with OK.",
                }
            ],
            max_tokens=1,
            temperature=0,
        )

        if not response.choices:
            raise LLMProtocolError("LLM health probe returned no choices.")

    async def close(self) -> None:
        await self.client.close()
