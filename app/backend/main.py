import logging
from contextlib import AsyncExitStack, asynccontextmanager, AbstractAsyncContextManager
from typing import AsyncIterator
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.backend.api.router import root_router
from app.backend.config import Settings, get_settings
from app.backend.core.exception_handlers import register_exception_handlers
from app.backend.core.logging import configure_logging
from app.backend.infrastructure.clients.llm_client import LLMClient
from app.backend.infrastructure.clients.mineru_client import MinerUClient
from app.backend.infrastructure.clients.embedding_client import EmbeddingClient
from app.backend.infrastructure.clients.reranker_client import RerankerClient
from app.backend.infrastructure.clients.visual_embedding_client import VisualEmbeddingClient
from app.backend.infrastructure.stores.file_store import FileStore
from app.backend.infrastructure.stores.metadata_store import MetadataStore
from app.backend.infrastructure.stores.sqlite import SQLiteDatabase
from app.backend.infrastructure.stores.vector_store import VectorStore
from app.backend.middleware.access_log import access_log_middleware
from app.backend.middleware.request_context import request_context_middleware

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create shared resources and close them in reverse order."""

    settings: Settings = app.state.settings
    startup_completed = False

    try:
        async with AsyncExitStack() as stack:
            file_store = FileStore.from_settings(settings)
            await file_store.initialize()

            sqlite = await SQLiteDatabase.connect(
                settings.project_path(settings.sqlite_path),
                busy_timeout_ms=settings.sqlite_busy_timeout_ms,
                enable_wal=settings.sqlite_enable_wal,
            )
            stack.push_async_callback(sqlite.close)

            metadata_store = MetadataStore(sqlite)
            await metadata_store.initialize()

            vector_store = await VectorStore.connect(settings)
            stack.push_async_callback(vector_store.close)

            text_embedding_client = EmbeddingClient(settings)
            stack.push_async_callback(text_embedding_client.close)

            reranker_client = RerankerClient(settings=settings)
            stack.push_async_callback(reranker_client.close)

            llm_client = LLMClient(settings)
            if llm_client is not None:
                stack.push_async_callback(llm_client.close)

            mineru_client = MinerUClient.from_settings(settings)
            stack.push_async_callback(mineru_client.close)

            visual_embedding_client = VisualEmbeddingClient.from_settings(settings)
            if visual_embedding_client is not None:
                stack.push_async_callback(visual_embedding_client.close)

            app.state.file_store = file_store
            app.state.metadata_store = metadata_store
            app.state.vector_store = vector_store
            app.state.text_embedding_client = text_embedding_client
            app.state.llm_client = llm_client
            app.state.mineru_client = mineru_client
            app.state.visual_embedding_client = visual_embedding_client
            app.state.reranker_client = reranker_client
            app.state.ready = True
            startup_completed = True

            logger.info(
                "应用启动完成 名称:%s 版本:%s 环境:%s",
                settings.app_name,
                settings.app_version,
                settings.app_env,
            )

            try:
                yield
            finally:
                app.state.ready = False

    except Exception:
        phase = "shutdown" if startup_completed else "startup"
        phase_message = "关闭" if phase == "shutdown" else "启动"
        logger.exception("应用%s失败", phase_message)
        raise

    logger.info("应用已停止 名称:%s", settings.app_name)


LifespanCallable = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(settings: Settings | None = None, *, lifespan_context: LifespanCallable = lifespan) -> FastAPI:
    """Create one fully configured FastAPI application instance."""

    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan_context,
    )
    app.state.settings = settings
    app.state.ready = False

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_middleware(BaseHTTPMiddleware, dispatch=access_log_middleware)
    app.add_middleware(BaseHTTPMiddleware, dispatch=request_context_middleware)

    register_exception_handlers(app)
    app.include_router(root_router)
    return app


app = create_app()
