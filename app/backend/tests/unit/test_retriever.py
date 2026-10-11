"""Retriever business orchestration tests without external services."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.backend.infrastructure.clients.embedding_client import SparseEmbedding
from app.backend.services.chat.retriver import Retriever


def build_retriever(*, points):
    embedding = SimpleNamespace(embed_query=AsyncMock(return_value=[1.0, 0.0]))
    encoder = SimpleNamespace(encode_query=Mock(return_value=SparseEmbedding([1], [1.0])))
    store = SimpleNamespace(hybrid_search=AsyncMock(return_value=points))
    reranker = SimpleNamespace(
        rerank=AsyncMock(return_value=[SimpleNamespace(index=0, score=0.9)])
    )
    service = Retriever(
        embedding_client=embedding,
        bm25_encoder=encoder,
        vector_store=store,
        reranker_client=reranker,
        settings=SimpleNamespace(retriever_candidate_top_k=20),
    )
    return service, embedding, encoder, store, reranker


def test_retrieve_combines_dense_sparse_and_reranker_results():
    async def run():
        point = SimpleNamespace(
            id="point-1",
            score=0.5,
            payload={"paper_name": "Paper", "text": "Evidence"},
        )
        service, embedding, encoder, store, reranker = build_retriever(points=[point])

        result = await service.retrieve(query="episodes")

        embedding.embed_query.assert_awaited_once_with("episodes")
        encoder.encode_query.assert_called_once_with("episodes")
        assert store.hybrid_search.call_args.kwargs["sparse_query"] == SparseEmbedding([1], [1.0])
        reranker.rerank.assert_awaited_once()
        assert result[0].candidate.point_id == "point-1"
        assert result[0].candidate.hybrid_score == 0.5
        assert result[0].rerank_score == 0.9

    asyncio.run(run())


def test_retrieve_skips_reranker_when_no_candidates():
    async def run():
        service, _, _, _, reranker = build_retriever(points=[])
        assert await service.retrieve(query="missing") == []
        reranker.rerank.assert_not_awaited()

    asyncio.run(run())