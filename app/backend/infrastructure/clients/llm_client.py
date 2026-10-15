from __future__ import annotations

from typing import Any
from collections.abc import Sequence

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage

import logging

from app.backend.config import Settings
from app.backend.core.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)


class LLMClient:
    """Shared OpenAI-compatible client for chat generation."""

    def __init__(self, settings: Settings) -> None:
        self.model = settings.llm_model
        self.client = AsyncOpenAI(
                    api_key=settings.llm_api_key.get_secret_value(),
                    base_url=settings.llm_base_url,
                    timeout=settings.llm_timeout_seconds,
                    max_retries=settings.llm_max_retries,
                ) if settings.llm_base_url and settings.llm_model and settings.llm_api_key else None
        self.timeout_seconds = settings.llm_timeout_seconds
        self.max_retries = settings.llm_max_retries
        self.temperature = settings.llm_temperature

    async def complete(self, *, messages: Sequence[dict[str, Any]], max_tokens: int = 1024, tools: list[dict[str, Any]] | None = None, tool_choice: str = "auto", temperature: float | None = None) -> tuple[ChatCompletionMessage, dict[str, int | None]]:
        if self.client is None:
            raise ServiceUnavailableError("大语言模型服务尚未配置。")
        request: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            parallel_tool_calls=False,
            max_tokens=max_tokens,
            temperature=self.temperature if temperature is None else temperature,
            top_p=0.8,
            extra_body={"top_k": 20},
        )
        if tools is not None:
            request.update(tools=tools, tool_choice=tool_choice)
        response = await self.client.chat.completions.create(**request)

        if not response.choices:
            raise ValueError("大语言模型未返回候选回答。")

        logger.info(
            "大语言模型补全成功 模型:%s 提示token数:%s 补全token数:%s 总token数:%s",
            self.model,
            response.usage.prompt_tokens if response.usage else None,
            response.usage.completion_tokens if response.usage else None,
            response.usage.total_tokens if response.usage else None,
        )

        logger.debug("LLM completion response: %s", response)

        return response.choices[0].message, {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else None,
            "completion_tokens": response.usage.completion_tokens if response.usage else None,
            "total_tokens": response.usage.total_tokens if response.usage else None,
        }

    async def probe(self) -> None:
        """Make one minimal real chat-completion request."""

        if self.client is None:
            raise ServiceUnavailableError("大语言模型服务尚未配置。")
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
            raise ValueError("大语言模型健康检查未返回候选回答。")

        usage = response.usage
        
        logger.info(
            "大语言模型健康检查成功 模型:%s 提示token数:%s 补全token数:%s 总token数:%s",
            self.model,
            usage.prompt_tokens if usage else None,
            usage.completion_tokens if usage else None,
            usage.total_tokens if usage else None,
            )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
