from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import models, AsyncQdrantClient
from qdrant_client.models import PointStruct, FieldCondition, Filter, MatchValue, Distance

from app.backend.config import Settings
from app.backend.services.papers.models import PaperChunk
from app.backend.infrastructure.clients.embedding_client import SparseEmbedding

class VectorStore:
    """Qdrant connection and collection compatibility checks."""

    def __init__(self, client: Any, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    @classmethod
    async def connect(cls, settings: Settings) -> "VectorStore":
        if settings.qdrant_mode == "local":
            path: Path = settings.project_path(settings.qdrant_path)
            path.mkdir(parents=True, exist_ok=True)
            client = AsyncQdrantClient(path=str(path))
        else:
            api_key = (settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None)
            client = AsyncQdrantClient(
                url=settings.qdrant_url,
                api_key=api_key,
                timeout=settings.qdrant_timeout_seconds,
                prefer_grpc=settings.qdrant_prefer_grpc,
                check_compatibility=settings.qdrant_check_compatibility,
            )

        store = cls(client=client, settings=settings)
        try:
            await store.ensure_collections()
        except Exception:
            await client.close()
            raise
        return store

    async def ensure_collections(self) -> None:
        await self.ensure_hybrid_collection(
            name=self.settings.qdrant_hybrid_collection,
            dimension=self.settings.text_embedding_dimension,
        )
        if self.settings.visual_embedding_enabled:
            await self.ensure_dense_collection(
                name=self.settings.qdrant_figure_collection,
                dimension=self.settings.visual_embedding_dimension,
            )

    def distance(self) -> Distance:
        return {
            "cosine": Distance.COSINE,
            "dot": Distance.DOT,
            "euclid": Distance.EUCLID,
            "manhattan": Distance.MANHATTAN,
        }[self.settings.qdrant_distance]

    async def ensure_hybrid_collection(self, *, name: str, dimension: int) -> None:
        distance = self.distance()

        exists = await self.client.collection_exists(name)
        if self.settings.qdrant_recreate_collections and exists:
            await self.client.delete_collection(name)
            exists = False

        if not exists:
            await self.client.create_collection(
                collection_name=name,
                vectors_config={"dense": models.VectorParams(size=dimension, distance=distance)},
                sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )
            await self.client.create_payload_index(
                collection_name=name,
                field_name="paper_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )
            return

        await self.assert_hybrid_schema(name, dimension)
        await self.client.create_payload_index(
            collection_name=name, field_name="paper_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True,
        )

    async def ensure_dense_collection(self, *, name: str, dimension: int) -> None:
        exists = await self.client.collection_exists(name)
        if self.settings.qdrant_recreate_collections and exists:
            await self.client.delete_collection(name)
            exists = False

        if not exists:
            await self.client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=dimension,
                    distance=self.distance(),
                ),
            )
            return

        await self.assert_dense_schema(name, dimension)
    async def upsert_vectors(self, *, paper_chunks: list[PaperChunk], dense_vectors: list[list[float]], sparse_vectors: list[SparseEmbedding]) -> None:
        """Upsert vectors into the Qdrant collection."""
        if not (len(paper_chunks) == len(dense_vectors) == len(sparse_vectors)):
            raise RuntimeError(f"Chunk/vector count mismatch: chunks={len(paper_chunks)}, dense={len(dense_vectors)}, sparse={len(sparse_vectors)}.")

        if not paper_chunks:
            return

        for index, vector in enumerate(dense_vectors):
            if len(vector) != self.settings.text_embedding_dimension:
                raise RuntimeError(
                    f"Vector dimension mismatch at index {index}: "
                    f"expected {self.settings.text_embedding_dimension}, received {len(vector)}."
                )

        points = [
            PointStruct(
                id=str(uuid5(NAMESPACE_URL, chunk.chunk_id)),
                vector={
                    "dense": dense_vector,
                    "sparse": models.SparseVector(
                        indices=sparse_vector.indices,
                        values=sparse_vector.values,
                    ),
                },
                payload={
                    "paper_id": chunk.paper_id,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "paper_name": chunk.metadata.get("paper_name"),
                    "section_id": chunk.metadata.get("section_id"),
                    "section_title": chunk.metadata.get("section_title"),
                    "parent_title": chunk.metadata.get("parent_title"),
                    "section_level": chunk.metadata.get("section_level"),
                    "section_index": chunk.metadata.get("section_index"),
                    "page_numbers": chunk.metadata.get("page_numbers", []),
                    "text": chunk.text,
                    "content_type": chunk.metadata.get("content_type"),
                    "caption": chunk.metadata.get("caption"),
                    "image_path": chunk.metadata.get("image_path"),
                },
            )
            for chunk, dense_vector, sparse_vector in zip(paper_chunks, dense_vectors, sparse_vectors, strict=True)
        ]
        await self.client.upsert(
            collection_name=self.settings.qdrant_hybrid_collection,
            points=points,
            wait=True,
        )

    async def delete_vectors(self, *, paper_id: str) -> None:
        """Delete all vectors for a given paper_id from the Qdrant collection."""
        await self.client.delete(
            collection_name=self.settings.qdrant_hybrid_collection,
            points_selector=Filter(must=[FieldCondition(key="paper_id", match=MatchValue(value=paper_id))]),
            wait=True,
        )

    async def query_text_chunks(self, *, query_vector: list[float], limit: int):
        result = await self.client.query_points(
            collection_name=self.settings.qdrant_hybrid_collection,
            query=query_vector,
            using="dense",
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return result.points

    async def hybrid_search(
        self, *, dense_query: list[float], sparse_query: SparseEmbedding,
        limit: int = 20, prefetch_k: int = 30,
    ):
        if limit < 1 or prefetch_k < 1:
            raise ValueError("Retrieval limits must be positive.")
        if len(dense_query) != self.settings.text_embedding_dimension:
            raise ValueError("Query vector dimension mismatch.")
        prefetch_depth = max(limit, prefetch_k)
        routes = [models.Prefetch(query=dense_query, using="dense", limit=prefetch_depth)]
        if sparse_query.indices:
            routes.append(models.Prefetch(query=models.SparseVector(indices=sparse_query.indices, values=sparse_query.values), using="sparse", limit=prefetch_depth))

        result = await self.client.query_points(
            collection_name=self.settings.qdrant_hybrid_collection,
            prefetch=routes,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return result.points

    async def ping(self) -> None:
        await self.client.get_collections()
        await self.assert_hybrid_schema(
            self.settings.qdrant_hybrid_collection,
            self.settings.text_embedding_dimension,
        )
        if self.settings.visual_embedding_enabled:
            await self.assert_dense_schema(
                self.settings.qdrant_figure_collection,
                self.settings.visual_embedding_dimension,
            )

    async def assert_hybrid_schema(self, name: str, dimension: int) -> None:
        info = await self.client.get_collection(name)
        params = info.config.params
        dense = params.vectors
        sparse = params.sparse_vectors or {}
        valid = (
            isinstance(dense, dict)
            and "dense" in dense
            and dense["dense"].size == dimension
            and dense["dense"].distance == self.distance()
            and "sparse" in sparse
            and sparse["sparse"].modifier == models.Modifier.IDF
        )
        if not valid:
            raise RuntimeError(
                f"Hybrid collection '{name}' requires named dense ({dimension} dimensions, "
                f"{self.settings.qdrant_distance}) and sparse with IDF. "
                "Use a new compatible collection and backfill; existing data was not changed."
            )

    async def assert_dense_schema(self, name: str, dimension: int) -> None:
        info = await self.client.get_collection(name)
        vectors = info.config.params.vectors
        if (
            isinstance(vectors, dict)
            or vectors.size != dimension
            or vectors.distance != self.distance()
        ):
            raise RuntimeError(
                f"Dense collection '{name}' requires one unnamed vector "
                f"({dimension} dimensions, {self.settings.qdrant_distance})."
            )
    async def close(self) -> None:
        await self.client.close()
