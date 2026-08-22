from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client.models import PointStruct, FieldCondition, Filter, MatchValue

from app.backend.config import Settings
from app.backend.services.papers.models import PaperChunk


class VectorStore:
    """Qdrant connection and collection compatibility checks."""

    def __init__(self, client: Any, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    @classmethod
    async def connect(cls, settings: Settings) -> "VectorStore":
        try:
            from qdrant_client import AsyncQdrantClient
        except ImportError as error:  # pragma: no cover - environment failure
            raise RuntimeError(
                "qdrant-client is required. Install the packages from requirements.txt."
            ) from error

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
        await self.ensure_collection(name=self.settings.qdrant_text_collection, dimension=self.settings.text_embedding_dimension)
        if self.settings.visual_embedding_enabled:
            await self.ensure_collection(name=self.settings.qdrant_figure_collection, dimension=self.settings.visual_embedding_dimension)

    async def ensure_collection(self, *, name: str, dimension: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        distance_map = {
            "cosine": Distance.COSINE,
            "dot": Distance.DOT,
            "euclid": Distance.EUCLID,
            "manhattan": Distance.MANHATTAN,
        }
        distance = distance_map[self.settings.qdrant_distance]

        exists = await self.client.collection_exists(name)
        if self.settings.qdrant_recreate_collections and exists:
            await self.client.delete_collection(name)
            exists = False

        if not exists:
            await self.client.create_collection(collection_name=name, vectors_config=VectorParams(size=dimension, distance=distance))
            return

        actual_dimension = await self.read_collection_dimension(name)
        if actual_dimension != dimension:
            raise RuntimeError(
                f"Qdrant collection '{name}' has dimension {actual_dimension}; "
                f"configuration expects {dimension}."
            )

    async def upsert_vectors(self, *, paper_chunks: list[PaperChunk], vectors: list[list[float]]) -> None:
        """Upsert vectors into the Qdrant collection."""
        if len(paper_chunks) != len(vectors):
            raise RuntimeError(f"Chunk/vector count mismatch: chunks={len(paper_chunks)}, vectors={len(vectors)}.")

        for index, vector in enumerate(vectors):
            if len(vector) != self.settings.text_embedding_dimension:
                raise RuntimeError(
                    f"Vector dimension mismatch at index {index}: "
                    f"expected {self.settings.text_embedding_dimension}, received {len(vector)}."
                )

        points = [
            PointStruct(
                id=str(uuid5(NAMESPACE_URL, chunk.chunk_id)),
                vector=vector,
                payload={
                    "paper_id": chunk.paper_id,
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "paper_name": chunk.metadata.get("paper_name"),
                    "section_title": chunk.metadata.get("section_title"),
                    "parent_title": chunk.metadata.get("parent_title"),
                    "section_level": chunk.metadata.get("section_level"),
                    "section_index": chunk.metadata.get("section_index"),
                    "page_start": chunk.metadata.get("page_start"),
                    "page_end": chunk.metadata.get("page_end"),
                    "text": chunk.text,
                },
            )
            for chunk, vector in zip(paper_chunks, vectors, strict=True)
        ]
        await self.client.upsert(
            collection_name=self.settings.qdrant_text_collection,
            points=points,
            wait=True,
        )

    async def delete_vectors(self, *, paper_id: str) -> None:
        """Delete all vectors for a given paper_id from the Qdrant collection."""
        await self.client.delete(
            collection_name=self.settings.qdrant_text_collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="paper_id",
                        match=MatchValue(value=paper_id),
                    )
                ]
            ),
            wait=True,
        )

    async def ping(self) -> None:
        """Query Qdrant and validate every enabled collection dimension."""

        await self.client.get_collections()
        await self.assert_collection_dimension(name=self.settings.qdrant_text_collection, expected=self.settings.text_embedding_dimension)
        if self.settings.visual_embedding_enabled:
            await self.assert_collection_dimension(name=self.settings.qdrant_figure_collection, expected=self.settings.visual_embedding_dimension)

    async def assert_collection_dimension(self, *, name: str, expected: int) -> None:
        actual = await self.read_collection_dimension(name)
        if actual != expected:
            raise RuntimeError(
                f"Qdrant collection '{name}' dimension changed "
                f"from {expected} to {actual}."
            )

    async def read_collection_dimension(self, name: str) -> int | None:
        info = await self.client.get_collection(name)
        vectors_config = info.config.params.vectors
        if isinstance(vectors_config, dict):
            if len(vectors_config) != 1:
                raise RuntimeError(
                    f"Qdrant collection '{name}' uses named or multiple vectors; "
                    "the MVP expects one unnamed vector."
                )
            vector_params = next(iter(vectors_config.values()))
        else:
            vector_params = vectors_config
        return getattr(vector_params, "size", None)

    async def close(self) -> None:
        await self.client.close()
