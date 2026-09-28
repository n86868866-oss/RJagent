import asyncio
from dataclasses import dataclass
from typing import Any

from app.backend.infrastructure.clients.embedding_client import BM25Encoder, EmbeddingClient
from app.backend.infrastructure.clients.reranker_client import RerankerClient
from app.backend.config import Settings
from app.backend.infrastructure.stores.vector_store import VectorStore


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    point_id: str
    hybrid_score: float
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RerankedCandidate:
    candidate: RetrievalCandidate
    rerank_score: float

class Retriever:
    def __init__(self, *, embedding_client: EmbeddingClient, bm25_encoder: BM25Encoder, vector_store: VectorStore, reranker_client: RerankerClient, settings: Settings) -> None:
        self.embedding_client = embedding_client
        self.bm25_encoder = bm25_encoder
        self.vector_store = vector_store
        self.reranker_client = reranker_client
        self.limit = settings.retriever_candidate_top_k

    async def retrieve(self, *, query: str) -> list[RerankedCandidate]:
        dense_vector = await self.embedding_client.embed_query(query)
        sparse_vector = await asyncio.to_thread(self.bm25_encoder.encode_query, query)

        points = await self.vector_store.hybrid_search(
            dense_query=dense_vector,
            sparse_query=sparse_vector,
            limit=self.limit,
            prefetch_k=30,
        )

        candidates = [
            RetrievalCandidate(
                point_id=str(point.id),
                hybrid_score=float(point.score),
                payload=dict(point.payload or {}),
            )
            for point in points
        ]

        if not candidates:
            return []

        texts = [self.build_rerank_text(candidate.payload) for candidate in candidates]

        scores = await self.reranker_client.rerank(query=query, texts=texts)

        return [
            RerankedCandidate(
                candidate=candidates[item.index],
                rerank_score=item.score,
            )
            for item in scores
        ]

    @staticmethod
    def build_rerank_text(payload: dict) -> str:
        parts = [
            f"Paper title: {payload.get('paper_name')}",
            f"Parent section: {payload.get('parent_title')}",
            f"Section title: {payload.get('section_title')}",
            f"Caption: {payload.get('caption')}",
            "Content:",
            str(payload.get("text") or ""),
        ]
        return "\n".join(part for part in parts if part and not part.endswith(": None"))
