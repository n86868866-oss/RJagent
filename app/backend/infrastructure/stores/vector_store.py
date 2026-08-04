from __future__ import annotations

from pathlib import Path
from typing import Any

from app.backend.config import Settings


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
            api_key = (
                settings.qdrant_api_key.get_secret_value()
                if settings.qdrant_api_key
                else None
            )
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
        await self._ensure_collection(
            name=self.settings.qdrant_text_collection,
            dimension=self.settings.text_embedding_dimension,
        )
        if self.settings.visual_embedding_enabled:
            await self._ensure_collection(
                name=self.settings.qdrant_figure_collection,
                dimension=self.settings.visual_embedding_dimension,
            )

    async def _ensure_collection(self, *, name: str, dimension: int) -> None:
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
            await self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dimension, distance=distance),
            )
            return

        actual_dimension = await self._read_collection_dimension(name)
        if actual_dimension != dimension:
            raise RuntimeError(
                f"Qdrant collection '{name}' has dimension {actual_dimension}; "
                f"configuration expects {dimension}."
            )

    async def ping(self) -> None:
        """Query Qdrant and validate every enabled collection dimension."""

        await self.client.get_collections()
        await self._assert_collection_dimension(
            name=self.settings.qdrant_text_collection,
            expected=self.settings.text_embedding_dimension,
        )
        if self.settings.visual_embedding_enabled:
            await self._assert_collection_dimension(
                name=self.settings.qdrant_figure_collection,
                expected=self.settings.visual_embedding_dimension,
            )

    async def _assert_collection_dimension(
        self,
        *,
        name: str,
        expected: int,
    ) -> None:
        actual = await self._read_collection_dimension(name)
        if actual != expected:
            raise RuntimeError(
                f"Qdrant collection '{name}' dimension changed "
                f"from {expected} to {actual}."
            )

    async def _read_collection_dimension(self, name: str) -> int | None:
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
