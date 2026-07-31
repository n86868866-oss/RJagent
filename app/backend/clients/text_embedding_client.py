from __future__ import annotations

from collections.abc import Sequence

import httpx

from app.backend.config import Settings


class TextEmbeddingClient:
    """Call the native DashScope text embedding HTTP API."""

    RESOURCE_PATH = "services/embeddings/text-embedding/text-embedding"

    def __init__(self, settings: Settings) -> None:
        if settings.text_embedding_provider != "dashscope_native":
            raise ValueError(
                "TEXT_EMBEDDING_PROVIDER must be dashscope_native."
            )

        base_url = settings.text_embedding_base_url.rstrip("/")
        if not base_url.endswith("/api/v1"):
            raise ValueError(
                "TEXT_EMBEDDING_BASE_URL must end with /api/v1."
            )

        self.endpoint = f"{base_url}/{self.RESOURCE_PATH}"
        self.model = settings.text_embedding_model
        self.dimension = settings.text_embedding_dimension
        self.batch_size = settings.text_embedding_batch_size
        self.query_text_type = settings.text_embedding_query_input_type
        self.document_text_type = settings.text_embedding_document_input_type
        self.output_type = settings.text_embedding_output_type

        self.http_client = httpx.AsyncClient(
            headers={
                "Authorization": (
                    "Bearer "
                    + settings.text_embedding_api_key.get_secret_value()
                ),
                "Content-Type": "application/json",
            },
            timeout=settings.text_embedding_timeout_seconds,
            trust_env=False,
        )

    async def embed_query(self, text: str) -> list[float]:
        """Generate one query vector."""

        vectors = await self.embed(
            texts=[text],
            text_type=self.query_text_type,
        )
        return vectors[0]

    async def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]:
        """Generate document vectors while preserving input order."""

        return await self.embed(
            texts=texts,
            text_type=self.document_text_type,
        )

    async def embed(
        self,
        texts: Sequence[str],
        text_type: str,
    ) -> list[list[float]]:
        """Validate texts, split them into batches, and call DashScope."""

        cleaned_texts = self.validate_texts(texts)
        vectors: list[list[float]] = []

        for start in range(0, len(cleaned_texts), self.batch_size):
            batch = cleaned_texts[start : start + self.batch_size]
            batch_vectors = await self.request_batch(
                texts=batch,
                text_type=text_type,
            )
            vectors.extend(batch_vectors)

        return vectors

    async def request_batch(
        self,
        texts: list[str],
        text_type: str,
    ) -> list[list[float]]:
        """Send one native DashScope HTTP request."""

        response = await self.http_client.post(
            self.endpoint,
            json={
                "model": self.model,
                "input": {
                    "texts": texts,
                },
                "parameters": {
                    "dimension": self.dimension,
                    "text_type": text_type,
                    "output_type": self.output_type,
                },
            },
        )

        response.raise_for_status()
        data = response.json()

        items = data["output"]["embeddings"]
        ordered_items = sorted(
            items,
            key=lambda item: item["text_index"],
        )

        vectors: list[list[float]] = []

        for expected_index, item in enumerate(ordered_items):
            if item["text_index"] != expected_index:
                raise RuntimeError(
                    "DashScope returned an unexpected text_index."
                )

            vector = item["embedding"]

            if len(vector) != self.dimension:
                raise RuntimeError(
                    "Unexpected embedding dimension: "
                    f"expected {self.dimension}, received {len(vector)}."
                )

            vectors.append(vector)

        return vectors

    @staticmethod
    def validate_texts(
        texts: Sequence[str],
    ) -> list[str]:
        """Reject empty inputs and remove surrounding whitespace."""

        if isinstance(texts, str):
            raise TypeError(
                "embed_documents expects a sequence of strings."
            )

        cleaned_texts: list[str] = []

        for index, text in enumerate(texts):
            cleaned = text.strip()

            if not cleaned:
                raise ValueError(
                    f"Embedding input at index {index} is empty."
                )

            cleaned_texts.append(cleaned)

        if not cleaned_texts:
            raise ValueError(
                "At least one text is required."
            )

        return cleaned_texts

    async def close(self) -> None:
        """Close the reusable HTTP connection pool."""

        await self.http_client.aclose()
