"""Offline regression tests: no Settings(), dotenv, or external services."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest
from qdrant_client import AsyncQdrantClient, models

from app.backend.infrastructure.clients.embedding_client import BM25Encoder, SparseEmbedding
from app.backend.infrastructure.stores.vector_store import VectorStore
from app.backend.services.chat.retriver import Retriever
from app.backend.services.papers.models import PaperChunk


def settings(**updates):
    values = dict(
        qdrant_hybrid_collection="hybrid", qdrant_text_collection="legacy",
        qdrant_figure_collection="figures", text_embedding_dimension=2,
        visual_embedding_dimension=3, visual_embedding_enabled=False,
        qdrant_distance="cosine", qdrant_recreate_collections=False,
        retriever_candidate_top_k=20,
    )
    return SimpleNamespace(**(values | updates))


def chunk(key, paper="p1"):
    return PaperChunk(key, paper, 0, "training episodes", {
        "paper_name": paper, "section_title": "Experiments",
        "page_numbers": [1],
    })


def test_encoder_initializes_and_uses_query_encoding(monkeypatch):
    model = Mock()
    monkeypatch.setattr(
        "app.backend.infrastructure.clients.embedding_client.SparseTextEmbedding",
        Mock(return_value=model),
    )
    encoder = BM25Encoder()
    value = SimpleNamespace(indices=np.array([7]), values=np.array([1.5]))
    model.embed.return_value = iter([value, value])
    model.query_embed.return_value = iter([value])
    result = encoder.encode_documents(["first", "second"])
    assert isinstance(result, list) and len(result) == 2
    assert encoder.encode_query("question") == SparseEmbedding([7], [1.5])
    model.query_embed.assert_called_once_with("question")


def test_real_qdrant_hybrid_sparse_only_hit_fallback_and_delete():
    async def run():
        client = AsyncQdrantClient(location=":memory:")
        store = VectorStore(client, settings())
        try:
            await store.ensure_collections()
            await store.ensure_collections()  # Existing schema validation.
            await store.upsert_vectors(
                paper_chunks=[chunk("dense-hit"), chunk("sparse-hit", "p2")],
                dense_vectors=[[1.0, 0.0], [0.0, 1.0]],
                sparse_vectors=[SparseEmbedding([1], [1.0]), SparseEmbedding([2], [1.0])],
            )
            hits = await store.hybrid_search(
                dense_query=[1.0, 0.0], sparse_query=SparseEmbedding([2], [1.0]),
                prefetch_k=1, limit=1,
            )
            # Verify the sparse branch can find a point absent from dense Top1.
            raw = await client.query_points(
                collection_name="hybrid", using="sparse",
                query=models.SparseVector(indices=[2], values=[1.0]), limit=1,
            )
            assert raw.points[0].payload["chunk_id"] == "sparse-hit"
            assert hits
            union = await store.hybrid_search(
                dense_query=[1.0, 0.0], sparse_query=SparseEmbedding([2], [1.0]), limit=2,
            )
            assert {p.payload["chunk_id"] for p in union} == {"dense-hit", "sparse-hit"}
            fallback = await store.hybrid_search(
                dense_query=[1.0, 0.0], sparse_query=SparseEmbedding([], []), limit=1,
            )
            assert fallback[0].payload["chunk_id"] == "dense-hit"
            dense = await store.query_text_chunks(query_vector=[1.0, 0.0], limit=1)
            assert dense[0].payload["chunk_id"] == "dense-hit"
            await store.ping()
            assert not await client.collection_exists("legacy")
            await store.delete_vectors(paper_id="p1")
            assert (await client.count("hybrid", exact=True)).count == 1
            points, _ = await client.scroll("hybrid", with_vectors=True)
            assert points[0].payload["paper_id"] == "p2"
            assert set(points[0].vector) == {"dense", "sparse"}
        finally:
            await client.close()
    asyncio.run(run())


@pytest.mark.parametrize("schema", ["unnamed", "missing_sparse", "missing_idf", "wrong_dimension", "wrong_distance"])
def test_incompatible_collection_rejected_without_recreation(schema):
    async def run():
        client = AsyncQdrantClient(location=":memory:")
        try:
            dense = models.VectorParams(
                size=3 if schema == "wrong_dimension" else 2,
                distance=models.Distance.DOT if schema == "wrong_distance" else models.Distance.COSINE,
            )
            await client.create_collection(
                "hybrid", vectors_config=dense if schema == "unnamed" else {"dense": dense},
                sparse_vectors_config={} if schema == "missing_sparse" else {
                    "sparse": models.SparseVectorParams(
                        modifier=None if schema == "missing_idf" else models.Modifier.IDF,
                    )
                },
            )
            store = VectorStore(client, settings())
            with pytest.raises(ValueError):
                await store.ensure_collections()
            assert await client.collection_exists("hybrid")
        finally:
            await client.close()
    asyncio.run(run())


def test_figure_collection_remains_unnamed_dense():
    async def run():
        client = AsyncQdrantClient(location=":memory:")
        try:
            store = VectorStore(client, settings(visual_embedding_enabled=True))
            await store.ensure_collections()
            info = await client.get_collection("figures")
            assert info.config.params.vectors.size == 3
            assert not info.config.params.sparse_vectors
            await store.ping()
        finally:
            await client.close()
    asyncio.run(run())


def test_mismatched_vector_counts_never_write():
    async def run():
        client = SimpleNamespace(upsert=AsyncMock())
        store = VectorStore(client, settings())
        with pytest.raises(ValueError):
            await store.upsert_vectors(paper_chunks=[chunk("a")], dense_vectors=[[1., 0.]], sparse_vectors=[])
        client.upsert.assert_not_called()
    asyncio.run(run())


def test_prefetch_depth_and_sparse_qdrant_conversion():
    async def run():
        client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
        store = VectorStore(client, settings())
        await store.hybrid_search(dense_query=[1., 0.], sparse_query=SparseEmbedding([3], [1.]), limit=50)
        args = client.query_points.call_args.kwargs
        assert args["collection_name"] == "hybrid"
        assert all(route.limit >= 50 for route in args["prefetch"])
        assert isinstance(args["prefetch"][1].query, models.SparseVector)
    asyncio.run(run())


def test_retriever_encodes_and_reranks_fused_results():
    async def run():
        embedding = SimpleNamespace(embed_query=AsyncMock(return_value=[1., 0.]))
        encoder = SimpleNamespace(encode_query=Mock(return_value=SparseEmbedding([1], [1.])))
        point = SimpleNamespace(id="point", score=0.5, payload={"text": "evidence"})
        store = SimpleNamespace(hybrid_search=AsyncMock(return_value=[point]))
        reranker = SimpleNamespace(rerank=AsyncMock(return_value=[SimpleNamespace(index=0, score=0.9)]))
        retriever = Retriever(embedding_client=embedding, bm25_encoder=encoder,
                              vector_store=store, reranker_client=reranker, settings=settings())
        result = await retriever.retrieve(query="episodes")
        assert result[0].candidate.hybrid_score == 0.5
        assert result[0].rerank_score == 0.9
        assert store.hybrid_search.call_args.kwargs["sparse_query"] == SparseEmbedding([1], [1.])
        store.hybrid_search.return_value = []
        reranker.rerank.reset_mock()
        assert await retriever.retrieve(query="missing") == []
        reranker.rerank.assert_not_called()
    asyncio.run(run())


def test_upload_uses_body_for_sparse_and_cleans_up_uncertain_write(monkeypatch):
    from app.backend.services.papers import paper_service as module

    async def run():
        paper_chunk = chunk("upload")
        service = module.PaperService.__new__(module.PaperService)
        service.settings = SimpleNamespace(max_upload_mb=20)
        service.metadata_store = SimpleNamespace(paper_name_exists=AsyncMock(return_value=False))
        service.mineru_client = SimpleNamespace(parse_pdf=AsyncMock(return_value=object()))
        service.file_store = SimpleNamespace(
            validate_pdf_upload=Mock(),
            save_temporary_upload=AsyncMock(return_value="temporary.pdf"),
            discard_temporary_upload=AsyncMock(),
        )
        service.document_builder = SimpleNamespace(build=Mock(return_value=([], [])))
        service.chunker = SimpleNamespace(
            split_documents=Mock(return_value=[]),
            build_paper_chunks=Mock(return_value=[paper_chunk]),
        )
        service.text_embedding_client = SimpleNamespace(embed_documents=AsyncMock(return_value=[[1., 0.]]))
        service.bm25_encoder = SimpleNamespace(encode_documents=Mock(return_value=[SparseEmbedding([1], [1.])]))
        service.vector_store = SimpleNamespace(
            upsert_vectors=AsyncMock(side_effect=TimeoutError("response lost after write")),
            delete_vectors=AsyncMock(),
        )
        monkeypatch.setattr(module, "require_paper_name", lambda value: "Paper")
        monkeypatch.setattr(module, "require_text_blocks", lambda value: [object()])
        monkeypatch.setattr(module, "require_normalized_text", lambda value: "body")
        monkeypatch.setattr(module, "require_content_list", lambda value: [])
        with pytest.raises(TimeoutError):
            await service.upload_pdf(filename="test.pdf", content_type="application/pdf", payload=b"%PDF-test")
        service.bm25_encoder.encode_documents.assert_called_once_with([paper_chunk.text])
        dense_text = service.text_embedding_client.embed_documents.call_args.args[0][0]
        assert "Paper title:" in dense_text
        service.vector_store.delete_vectors.assert_awaited_once()
    asyncio.run(run())


def test_backfill_preserves_ids_payload_and_dense_and_refuses_overwrite():
    from app.backend.scripts.migrations.backfill_hybrid_vectors import backfill
    from uuid import uuid4

    async def run():
        client = AsyncQdrantClient(location=":memory:")
        try:
            await client.create_collection("legacy", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
            point_id = str(uuid4())
            payload = {"chunk_id": "a", "paper_id": "p", "text": "original body", "caption": "caption"}
            await client.upsert("legacy", points=[models.PointStruct(id=point_id, vector=[1., 0.], payload=payload)])
            encoder = SimpleNamespace(encode_documents=Mock(return_value=[SparseEmbedding([4], [1.])]))
            assert await backfill(client, encoder, "legacy", "hybrid", batch_size=1) == 1
            points, _ = await client.scroll("hybrid", with_vectors=True)
            assert points[0].id == point_id and points[0].payload == payload
            assert points[0].vector["dense"] == [1., 0.]
            assert points[0].vector["sparse"].indices == [4]
            encoder.encode_documents.assert_called_once_with(["original body"])
            assert (await client.count("legacy", exact=True)).count == 1
            with pytest.raises(ValueError, match="must be empty"):
                await backfill(client, encoder, "legacy", "hybrid")
        finally:
            await client.close()
    asyncio.run(run())

