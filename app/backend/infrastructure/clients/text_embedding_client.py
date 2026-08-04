from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx

from app.backend.config import Settings


RETRYABLE_STATUS_CODES = {
    408,  # Request Timeout
    429,  # Too Many Requests
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


class TextEmbeddingError(RuntimeError):
    """Raised when the embedding request or response is invalid."""


class TextEmbeddingClient:
    """Call the native DashScope text embedding HTTP API."""

    RESOURCE_PATH = "services/embeddings/text-embedding/text-embedding"

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if settings.text_embedding_provider != "dashscope_native":
            raise ValueError("TEXT_EMBEDDING_PROVIDER must be dashscope_native.")

        base_url = settings.text_embedding_base_url.rstrip("/")

        if not base_url.endswith("/api/v1"):
            raise ValueError("TEXT_EMBEDDING_BASE_URL must end with /api/v1.")

        self.endpoint = f"{base_url}/{self.RESOURCE_PATH}"
        self.model = settings.text_embedding_model
        self.dimension = settings.text_embedding_dimension
        self.batch_size = settings.text_embedding_batch_size
        self.max_retries = settings.text_embedding_max_retries
        self.query_text_type = settings.text_embedding_query_input_type
        self.document_text_type = settings.text_embedding_document_input_type
        self.output_type = settings.text_embedding_output_type

        self.http_client = httpx.AsyncClient(
            headers={
                "Authorization": "Bearer " + settings.text_embedding_api_key.get_secret_value(),
                "Content-Type": "application/json",
            },
            timeout=settings.text_embedding_timeout_seconds,
            trust_env=False,
            transport=transport,
        )

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed([text], self.query_text_type)
        return vectors[0]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self.embed(texts, self.document_text_type)

    async def embed(self, texts: Sequence[str], text_type: str) -> list[list[float]]:
        cleaned_texts = self.validate_texts(texts)
        vectors: list[list[float]] = []

        for start in range(0, len(cleaned_texts), self.batch_size):
            batch = cleaned_texts[start:start + self.batch_size]
            vectors.extend(await self.request_batch(batch, text_type))

        return vectors

    async def request_batch(self, texts: list[str], text_type: str) -> list[list[float]]:
        payload = self.create_payload(texts, text_type)
        response = await self.post_embedding_request(payload)
        items = self.parse_embedding_items(response)
        return self.build_vectors(items, len(texts))

    def create_payload(self, texts: list[str], text_type: str) -> dict:
        return {
            "model": self.model,
            "input": {"texts": texts},
            "parameters": {
                "dimension": self.dimension,
                "text_type": text_type,
                "output_type": self.output_type,
            },
        }

    async def post_embedding_request(self, payload: dict) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.http_client.post(self.endpoint, json=payload)
            except RETRYABLE_EXCEPTIONS as error:
                last_error = error

                if attempt >= self.max_retries:
                    raise TextEmbeddingError(f"Embedding request failed after {self.max_retries + 1} attempts.") from error

                await asyncio.sleep(0.5 * (2 ** attempt))
                continue

            if 200 <= response.status_code < 300:
                return response

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                await asyncio.sleep(0.5 * (2 ** attempt))
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise TextEmbeddingError(f"DashScope HTTP request failed with status {response.status_code}.") from error

        raise TextEmbeddingError("Embedding request did not produce a response.") from last_error

    @staticmethod
    def parse_embedding_items(response: httpx.Response) -> list[object]:
        try:
            data = response.json()
        except ValueError as error:
            raise TextEmbeddingError("DashScope returned a non-JSON response.") from error

        if not isinstance(data, dict):
            raise TextEmbeddingError("DashScope returned an invalid JSON object.")

        output = data.get("output")

        if not isinstance(output, dict):
            raise TextEmbeddingError("DashScope response is missing 'output'.")

        items = output.get("embeddings")

        if not isinstance(items, list):
            raise TextEmbeddingError("DashScope response is missing 'output.embeddings'.")

        return items

    def build_vectors(self, items: list[object], expected_count: int) -> list[list[float]]:
        ordered_items = sorted(items, key=self.read_text_index)

        if len(ordered_items) != expected_count:
            raise TextEmbeddingError(f"Embedding count mismatch: expected {expected_count}, received {len(ordered_items)}.")

        vectors: list[list[float]] = []

        for expected_index, item in enumerate(ordered_items):
            actual_index = self.read_text_index(item)

            if actual_index != expected_index:
                raise TextEmbeddingError(f"Unexpected text_index: expected {expected_index}, received {actual_index}.")

            vector = item.get("embedding")

            if not isinstance(vector, list):
                raise TextEmbeddingError("Embedding item is missing a valid dense vector.")

            if len(vector) != self.dimension:
                raise TextEmbeddingError(f"Unexpected embedding dimension: expected {self.dimension}, received {len(vector)}.")

            try:
                vectors.append([float(value) for value in vector])
            except (TypeError, ValueError) as error:
                raise TextEmbeddingError("Embedding vector contains a non-numeric value.") from error

        return vectors

    @staticmethod
    def read_text_index(item: object) -> int:
        if not isinstance(item, dict):
            raise TextEmbeddingError("Embedding item must be a JSON object.")

        text_index = item.get("text_index")

        if not isinstance(text_index, int) or isinstance(text_index, bool):
            raise TextEmbeddingError("Embedding item has no valid text_index.")

        return text_index

    @staticmethod
    def validate_texts(texts: Sequence[str]) -> list[str]:
        if isinstance(texts, str):
            raise TypeError("embed_documents expects a sequence of strings, not one plain string.")

        cleaned_texts: list[str] = []

        for index, text in enumerate(texts):
            if not isinstance(text, str):
                raise TypeError(f"Embedding input at index {index} is not a string.")

            cleaned = text.strip()

            if not cleaned:
                raise ValueError(f"Embedding input at index {index} is empty.")

            cleaned_texts.append(cleaned)

        if not cleaned_texts:
            raise ValueError("At least one text is required.")

        return cleaned_texts

    async def probe(self) -> None:
        """Make one real query request and validate the returned vector."""

        vector = await self.embed_query("health check")
        if len(vector) != self.dimension:
            raise TextEmbeddingError(
                f"Health probe expected dimension {self.dimension}, "
                f"received {len(vector)}."
            )

    async def close(self) -> None:
        await self.http_client.aclose()


""" 先验证每条记录能否读取索引
→ 排序
→ 检查记录数量
→ 检查索引连续性
→ 检查每条记录是否包含合法向量
→ 检查向量维度 """
