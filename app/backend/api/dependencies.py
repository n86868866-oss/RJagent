"""FastAPI's composition root: lifespan resources -> services -> routes.

Use Depends for nested providers so overrides and request-scoped caching work.
Services themselves use ordinary constructor injection, without FastAPI imports.
"""
from typing import Annotated

from fastapi import Depends, Request

from app.backend.config import Settings
from app.backend.core.exceptions import ServiceUnavailableError
from app.backend.infrastructure.clients.embedding_client import BM25Encoder, EmbeddingClient
from app.backend.infrastructure.clients.llm_client import LLMClient
from app.backend.infrastructure.clients.mineru_client import MinerUClient
from app.backend.infrastructure.clients.reranker_client import RerankerClient
from app.backend.infrastructure.stores.file_store import FileStore
from app.backend.infrastructure.stores.metadata_store import MetadataStore
from app.backend.infrastructure.stores.vector_store import VectorStore
from app.backend.services.health.health_service import HealthService
from app.backend.services.papers.paper_service import PaperService
from app.backend.services.chat.retriver import Retriever
from app.backend.services.chat.chat import ChatService


def resource(request: Request, name: str):
    value = getattr(request.app.state, name, None)
    if value is None:
        raise ServiceUnavailableError(f"服务资源尚未初始化：{name}")
    return value


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_file_store(request: Request) -> FileStore:
    return resource(request, "file_store")


def get_metadata_store(request: Request) -> MetadataStore:
    return resource(request, "metadata_store")


def get_mineru_client(request: Request) -> MinerUClient:
    return resource(request, "mineru_client")


def get_embedding_client(request: Request) -> EmbeddingClient:
    return resource(request, "text_embedding_client")


def get_bm25_encoder(request: Request) -> BM25Encoder:
    return resource(request, "bm25_encoder")


def get_vector_store(request: Request) -> VectorStore:
    return resource(request, "vector_store")


def get_reranker_client(request: Request) -> RerankerClient:
    return resource(request, "reranker_client")


def get_llm_client(request: Request) -> LLMClient:
    return resource(request, "llm_client")


def get_health_service(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> HealthService:
    names = ("file_store", "metadata_store", "vector_store", "text_embedding_client",
             "reranker_client", "mineru_client", "llm_client", "visual_embedding_client")
    return HealthService(
        resources={name: getattr(request.app.state, name, None) for name in names},
        ready=bool(getattr(request.app.state, "ready", False)),
        settings=settings,
    )


def get_paper_service(
    settings: Annotated[Settings, Depends(get_settings)],
    metadata_store: Annotated[MetadataStore, Depends(get_metadata_store)],
    file_store: Annotated[FileStore, Depends(get_file_store)],
    mineru_client: Annotated[MinerUClient, Depends(get_mineru_client)],
    embedding_client: Annotated[EmbeddingClient, Depends(get_embedding_client)],
    bm25_encoder: Annotated[BM25Encoder, Depends(get_bm25_encoder)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
) -> PaperService:
    return PaperService(settings=settings, metadata_store=metadata_store, file_store=file_store,
                        mineru_client=mineru_client, text_embedding_client=embedding_client,
                        bm25_encoder=bm25_encoder, vector_store=vector_store)


def get_retriever_service(
    settings: Annotated[Settings, Depends(get_settings)],
    embedding_client: Annotated[EmbeddingClient, Depends(get_embedding_client)],
    bm25_encoder: Annotated[BM25Encoder, Depends(get_bm25_encoder)],
    vector_store: Annotated[VectorStore, Depends(get_vector_store)],
    reranker_client: Annotated[RerankerClient, Depends(get_reranker_client)],
) -> Retriever:
    return Retriever(embedding_client=embedding_client, bm25_encoder=bm25_encoder,
                     vector_store=vector_store, reranker_client=reranker_client, settings=settings)


def get_chat_service(
    settings: Annotated[Settings, Depends(get_settings)],
    retriever: Annotated[Retriever, Depends(get_retriever_service)],
    llm_client: Annotated[LLMClient, Depends(get_llm_client)],
) -> ChatService:
    return ChatService(retriever=retriever, llm_client=llm_client, settings=settings)
