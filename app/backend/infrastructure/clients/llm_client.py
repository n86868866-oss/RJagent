from __future__ import annotations

from typing import Any
from collections.abc import Sequence

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage

import logging

from app.backend.config import Settings

logger = logging.getLogger(__name__)


class LLMProtocolError(RuntimeError):
    """Raised when an OpenAI-compatible LLM response is unusable."""


class LLMClient:
    """Shared OpenAI-compatible client for chat generation."""

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_base_url or not settings.llm_model or not settings.llm_api_key:
            raise ValueError("LLMClient requires llm_base_url, llm_model, and llm_api_key to be set in settings.")
        self.model = settings.llm_model
        self.client = AsyncOpenAI(
                    api_key=settings.llm_api_key.get_secret_value(),
                    base_url=settings.llm_base_url,
                    timeout=settings.llm_timeout_seconds,
                    max_retries=settings.llm_max_retries,
                )
        self.timeout_seconds = settings.llm_timeout_seconds
        self.max_retries = settings.llm_max_retries
        self.temperature = settings.llm_temperature

    async def complete(self, *, messages: Sequence[dict[str, Any]], max_tokens: int = 1024, tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto") -> ChatCompletionMessage:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            parallel_tool_calls=False,
            max_tokens=max_tokens,
            temperature=self.temperature,
            top_p=0.8,
            extra_body={"top_k": 20},
        )

        if not response.choices:
            raise LLMProtocolError("LLM completion returned no choices.")

        logger.info(
            "大语言模型补全成功 模型:%s 提示token数:%s 补全token数:%s 总token数:%s",
            self.model,
            response.usage.prompt_tokens if response.usage else None,
            response.usage.completion_tokens if response.usage else None,
            response.usage.total_tokens if response.usage else None,
        )

        logger.debug("LLM completion response: %s", response)

        return response.choices[0].message

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

        usage = response.usage
        
        logger.info(
            "大语言模型健康检查成功 模型:%s 提示token数:%s 补全token数:%s 总token数:%s",
            self.model,
            usage.prompt_tokens if usage else None,
            usage.completion_tokens if usage else None,
            usage.total_tokens if usage else None,
            )

    async def close(self) -> None:
        await self.client.close()
