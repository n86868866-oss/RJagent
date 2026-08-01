from __future__ import annotations

import json
import math
import os
import unittest
from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import httpx

from app.backend.clients.text_embedding_client import TextEmbeddingClient, TextEmbeddingError
from app.backend.config import Settings, get_settings


RUN_INTEGRATION_TEST = os.getenv("RUN_DASHSCOPE_INTEGRATION_TEST", "").strip().lower() in {"1", "true", "yes"}


def read_request(request: httpx.Request) -> tuple[list[str], int]:
    payload = json.loads(request.content.decode("utf-8"))
    return payload["input"]["texts"], payload["parameters"]["dimension"]


def create_success_response(request: httpx.Request, vector_dimension: int | None = None, reverse_items: bool = False, omit_text_index: bool = False, response_count: int | None = None, text_indexes: list[int] | None = None) -> httpx.Response:
    texts, requested_dimension = read_request(request)
    actual_dimension = requested_dimension if vector_dimension is None else vector_dimension
    actual_count = len(texts) if response_count is None else response_count
    indexes = list(range(actual_count)) if text_indexes is None else text_indexes
    embeddings: list[dict[str, object]] = []

    for position, text_index in enumerate(indexes):
        item: dict[str, object] = {"embedding": [float(position + 1)] * actual_dimension}

        if not omit_text_index:
            item["text_index"] = text_index

        embeddings.append(item)

    if reverse_items:
        embeddings.reverse()

    return httpx.Response(status_code=200, json={"output": {"embeddings": embeddings}})


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Vectors must have the same dimension.")

    dot_product = sum(left_value * right_value for left_value, right_value in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))

    if left_norm == 0 or right_norm == 0:
        raise ValueError("Cosine similarity is undefined for a zero vector.")

    return dot_product / (left_norm * right_norm)


class TextEmbeddingClientUnitTests(unittest.IsolatedAsyncioTestCase):
    def create_client(self, handler: Callable[[httpx.Request], httpx.Response], **setting_updates: object) -> tuple[TextEmbeddingClient, Settings]:
        updates: dict[str, object] = {"text_embedding_batch_size": 10, "text_embedding_max_retries": 0, **setting_updates}
        settings = get_settings().model_copy(update=updates)
        client = TextEmbeddingClient(settings, transport=httpx.MockTransport(handler))
        return client, settings

    async def test_01_single_query_returns_1024_dimensions(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return create_success_response(request)

        client, settings = self.create_client(handler)

        try:
            vector = await client.embed_query("What is retrieval-augmented generation?")
        finally:
            await client.close()

        self.assertEqual(len(vector), settings.text_embedding_dimension)
        self.assertEqual(len(vector), 1024)

    async def test_02_wrong_vector_dimension_fails(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return create_success_response(request, vector_dimension=100)

        client, _ = self.create_client(handler)

        try:
            with self.assertRaisesRegex(TextEmbeddingError, "dimension"):
                await client.embed_query("What is RAG?")
        finally:
            await client.close()

    async def test_03_multiple_documents_keep_count_and_order(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return create_success_response(request)

        client, settings = self.create_client(handler)
        documents = ["First document chunk.", "Second document chunk.", "Third document chunk."]

        try:
            vectors = await client.embed_documents(documents)
        finally:
            await client.close()

        self.assertEqual(len(vectors), len(documents))
        self.assertEqual([vector[0] for vector in vectors], [1.0, 2.0, 3.0])
        self.assertTrue(all(len(vector) == settings.text_embedding_dimension for vector in vectors))

    async def test_04_empty_text_is_rejected(self) -> None:
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return create_success_response(request)

        client, _ = self.create_client(handler)

        try:
            with self.assertRaisesRegex(ValueError, "empty"):
                await client.embed_documents([""])
        finally:
            await client.close()

        self.assertEqual(request_count, 0)

    async def test_05_whitespace_text_is_rejected(self) -> None:
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return create_success_response(request)

        client, _ = self.create_client(handler)

        try:
            with self.assertRaisesRegex(ValueError, "empty"):
                await client.embed_documents(["   \n\t   "])
        finally:
            await client.close()

        self.assertEqual(request_count, 0)

    async def test_06_324_texts_are_split_into_ten_and_one(self) -> None:
        batch_sizes: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            texts, dimension = read_request(request)
            batch_sizes.append(len(texts))
            self.assertEqual(dimension, 1024)
            return create_success_response(request)

        client, settings = self.create_client(handler, text_embedding_batch_size=10)
        documents = [f"Document chunk number {index}" for index in range(324)]

        try:
            vectors = await client.embed_documents(documents)
        finally:
            await client.close()

        self.assertEqual(batch_sizes, [10] * 32 + [4])
        self.assertEqual(len(vectors), 324)
        self.assertTrue(all(len(vector) == settings.text_embedding_dimension for vector in vectors))

    async def test_07_out_of_order_text_indexes_are_restored(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return create_success_response(request, reverse_items=True)

        client, _ = self.create_client(handler)

        try:
            vectors = await client.embed_documents(["First chunk.", "Second chunk.", "Third chunk."])
        finally:
            await client.close()

        self.assertEqual([vector[0] for vector in vectors], [1.0, 2.0, 3.0])

    async def test_08_missing_text_index_fails(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return create_success_response(request, omit_text_index=True)

        client, _ = self.create_client(handler)

        try:
            with self.assertRaisesRegex(TextEmbeddingError, "text_index"):
                await client.embed_query("What is RAG?")
        finally:
            await client.close()

    async def test_09_non_continuous_text_indexes_fail(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return create_success_response(request, text_indexes=[0, 2])

        client, _ = self.create_client(handler)

        try:
            with self.assertRaisesRegex(TextEmbeddingError, "text_index"):
                await client.embed_documents(["First chunk.", "Second chunk."])
        finally:
            await client.close()

    async def test_10_429_is_retried_and_then_succeeds(self) -> None:
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1

            if request_count == 1:
                return httpx.Response(status_code=429, json={"message": "Simulated rate limit."})

            return create_success_response(request)

        client, settings = self.create_client(handler, text_embedding_max_retries=1)

        try:
            with patch("app.backend.clients.text_embedding_client.asyncio.sleep", new=AsyncMock()) as mocked_sleep:
                vector = await client.embed_query("What is RAG?")
        finally:
            await client.close()

        self.assertEqual(request_count, 2)
        self.assertEqual(len(vector), settings.text_embedding_dimension)
        mocked_sleep.assert_awaited_once()

    async def test_11_401_is_not_retried(self) -> None:
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(status_code=401, json={"message": "Simulated invalid API key."})

        client, _ = self.create_client(handler, text_embedding_max_retries=3)

        try:
            with self.assertRaisesRegex(TextEmbeddingError, "401"):
                await client.embed_query("What is RAG?")
        finally:
            await client.close()

        self.assertEqual(request_count, 1)

    async def test_12_connection_timeout_is_retried(self) -> None:
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1

            if request_count == 1:
                raise httpx.ConnectTimeout("Simulated connection timeout.", request=request)

            return create_success_response(request)

        client, settings = self.create_client(handler, text_embedding_max_retries=1)

        try:
            with patch("app.backend.clients.text_embedding_client.asyncio.sleep", new=AsyncMock()) as mocked_sleep:
                vector = await client.embed_query("What is RAG?")
        finally:
            await client.close()

        self.assertEqual(request_count, 2)
        self.assertEqual(len(vector), settings.text_embedding_dimension)
        mocked_sleep.assert_awaited_once()

    async def test_13_non_json_response_has_clear_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=200, text="<html>Simulated gateway page</html>", headers={"Content-Type": "text/html"})

        client, _ = self.create_client(handler)

        try:
            with self.assertRaisesRegex(TextEmbeddingError, "non-JSON"):
                await client.embed_query("What is RAG?")
        finally:
            await client.close()

    async def test_14_response_count_matches_input_count(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return create_success_response(request, response_count=1)

        client, _ = self.create_client(handler)

        try:
            with self.assertRaisesRegex(TextEmbeddingError, "count mismatch"):
                await client.embed_documents(["First chunk.", "Second chunk."])
        finally:
            await client.close()


@unittest.skipUnless(RUN_INTEGRATION_TEST, "Set RUN_DASHSCOPE_INTEGRATION_TEST=1 to call the real DashScope API.")
class DashScopeEmbeddingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_dashscope_embedding_api(self) -> None:
        settings = get_settings()
        client = TextEmbeddingClient(settings)
        query = "How does retrieval-augmented generation reduce unsupported answers?"
        documents = [
            "Retrieval-augmented generation retrieves supporting evidence before answer generation and can attach citations.",
            "Convolutional neural networks are commonly used for image classification.",
            "SQLite stores relational data in a local file.",
        ]

        try:
            query_vector = await client.embed_query(query)
            document_vectors = await client.embed_documents(documents)
        finally:
            await client.close()

        self.assertEqual(len(query_vector), settings.text_embedding_dimension)
        self.assertEqual(len(document_vectors), len(documents))
        self.assertTrue(all(len(vector) == settings.text_embedding_dimension for vector in document_vectors))
        self.assertTrue(any(value != 0 for value in query_vector))
        self.assertTrue(all(any(value != 0 for value in vector) for vector in document_vectors))

        scores = [cosine_similarity(query_vector, document_vector) for document_vector in document_vectors]

        self.assertTrue(all(math.isfinite(score) for score in scores))
        self.assertEqual(scores.index(max(scores)), 0)

        print()
        print("Real DashScope integration result")
        print("Provider:", settings.text_embedding_provider)
        print("Model:", settings.text_embedding_model)
        print("Dimension:", len(query_vector))
        print("Document count:", len(document_vectors))
        print("Cosine scores:", [round(score, 6) for score in scores])


if __name__ == "__main__":
    unittest.main(verbosity=2)
