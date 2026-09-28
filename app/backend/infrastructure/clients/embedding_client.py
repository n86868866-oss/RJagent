from __future__ import annotations

import asyncio
import logging
from threading import Lock
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.backend.config import Settings
from fastembed import SparseTextEmbedding


logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
RETRYABLE_EXCEPTIONS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.NetworkError)


@dataclass(frozen=True)
class SparseEmbedding:
    indices: list[int]
    values: list[float]

class BM25Encoder:
    def __init__(self):
        self.encoder = None
        self.load_lock = Lock()

    @property
    def encoder(self):
        with self.load_lock:
            if self.encoder is None:
                self.encoder = SparseTextEmbedding(
                    model_name="Qdrant/bm25",
                    language="english",
                    avg_len=256.0,
                )
        return self.encoder

    @staticmethod
    def convert(value) -> SparseEmbedding:
        return SparseEmbedding(
            indices=value.indices.tolist(),
            values=value.values.tolist(),
        )

    def encode_documents(self, texts: list[str]) -> list[SparseEmbedding]:
        return [self.convert(value) for value in self.encoder.embed(texts)]

    def encode_query(self, text: str) -> SparseEmbedding:
        return self.convert(next(self.encoder.query_embed(text)))


class EmbeddingClient:
    """Call a local Hugging Face Text Embeddings Inference service."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if settings.text_embedding_provider != "local_tei":
            raise ValueError("TEXT_EMBEDDING_PROVIDER 必须设置为 local_tei。")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if settings.text_embedding_api_key is not None:
            api_key = settings.text_embedding_api_key.get_secret_value().strip()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        self.endpoint = settings.text_embedding_base_url.rstrip("/") + "/embed"
        self.model = settings.text_embedding_model
        self.dimension = settings.text_embedding_dimension
        self.batch_size = settings.text_embedding_batch_size
        self.max_retries = settings.text_embedding_max_retries
        self.http_client = httpx.AsyncClient(
            headers=headers,
            timeout=settings.text_embedding_timeout_seconds,
            trust_env=False,
            transport=transport,
        )

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed([self.query_instruction(text)])
        return vectors[0]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self.embed(texts)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        cleaned_texts = self.validate_texts(texts)
        vectors: list[list[float]] = []

        for start in range(0, len(cleaned_texts), self.batch_size):
            batch = cleaned_texts[start : start + self.batch_size]
            vectors.extend(await self.request_batch(batch))

        return vectors

    async def request_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {"inputs": texts}
        response = await self.post_embedding_request(payload)
        return self.parse_vectors(response, expected_count=len(texts))

    async def post_embedding_request(self, payload: dict[str, Any]) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.http_client.post(self.endpoint, json=payload)
            except RETRYABLE_EXCEPTIONS as error:
                last_error = error
                if attempt >= self.max_retries:
                    logger.error("嵌入服务请求失败，已用尽 %s 次重试", self.max_retries, exc_info=True)
                    raise  # 保留原异常及堆栈，由全局处理器生成中文响应。
                await asyncio.sleep(0.5 * (2**attempt))
                continue

            if 200 <= response.status_code < 300:
                return response

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                await asyncio.sleep(0.5 * (2**attempt))
                continue

            response.raise_for_status()
            logger.error("嵌入服务请求失败，已用尽 %s 次重试", self.max_retries, exc_info=True)
        
        raise ValueError("嵌入请求结束但没有获得响应。") from last_error

    def parse_vectors(self, response: httpx.Response, *, expected_count: int) -> list[list[float]]:
        try:
            data = response.json()
        except ValueError as error:
            raise ValueError("嵌入服务返回的内容不是有效的 JSON。") from error

        if not isinstance(data, list):
            raise ValueError("嵌入服务的响应必须是 JSON 数组。")
        if len(data) != expected_count:
            raise ValueError(f"嵌入向量数量不匹配：预期 {expected_count}，实际 {len(data)}。")

        vectors: list[list[float]] = []
        for index, item in enumerate(data):
            if not isinstance(item, list):
                raise ValueError(f"第 {index} 项嵌入结果不是向量。")
            if len(item) != self.dimension:
                raise ValueError(f"嵌入向量维度不匹配：预期 {self.dimension}，实际 {len(item)}。")
            try:
                vectors.append([float(value) for value in item])
            except (TypeError, ValueError) as error:
                raise ValueError(f"第 {index} 个嵌入向量包含非数字值。") from error

        return vectors

    @staticmethod
    def validate_texts(texts: Sequence[str]) -> list[str]:
        if isinstance(texts, str):
            raise TypeError("embed_documents 需要字符串序列，不能传入单个字符串。")

        cleaned_texts: list[str] = []
        for index, text in enumerate(texts):
            if not isinstance(text, str):
                raise TypeError(f"第 {index} 项嵌入输入不是字符串。")
            cleaned = text.strip()
            if not cleaned:
                raise ValueError(f"第 {index} 项嵌入输入为空。")
            cleaned_texts.append(cleaned)

        if not cleaned_texts:
            raise ValueError("至少需要一段文本。")

        return cleaned_texts

    @staticmethod
    def query_instruction(text: str) -> str:
        return (
            "Instruct: Given a Chinese or English question, retrieve relevant passages "
            "from English academic papers that answer the question\n"
            f"Query: {text}"
        )

    async def probe(self) -> None:
        vector = await self.embed_query("健康检查")
        logger.info(
            "文本向量健康检查成功 模型:%s 向量维度:%s",
            self.model,
            len(vector),
        )

    async def close(self) -> None:
        await self.http_client.aclose()
