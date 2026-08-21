from __future__ import annotations

from fastapi import Request

from app.backend.config import Settings
from app.backend.infrastructure.clients.mineru_client import MinerUClient
from app.backend.infrastructure.stores.file_store import FileStore
from app.backend.infrastructure.stores.metadata_store import MetadataStore
from app.backend.services.health_service import HealthService
from app.backend.services.papers.paper_service import PaperService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_health_service(request: Request) -> HealthService:
    return HealthService(
        app=request.app,
        settings=request.app.state.settings,
    )


def get_file_store(request: Request) -> FileStore:
    return request.app.state.file_store


def get_metadata_store(request: Request) -> MetadataStore:
    return request.app.state.metadata_store


def get_mineru_client(request: Request) -> MinerUClient:
    return request.app.state.mineru_client


def get_paper_service(request: Request) -> PaperService:
    return PaperService(
        settings=request.app.state.settings,
        metadata_store=request.app.state.metadata_store,
        file_store=request.app.state.file_store,
        mineru_client=request.app.state.mineru_client,
        text_embedding_client=request.app.state.text_embedding_client,
        vector_store=request.app.state.vector_store,
    )
