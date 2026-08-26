from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parents[1]


class Settings(BaseSettings):
    """Validated runtime configuration for Research Journey Agent."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------

    app_name: str = Field(
        default="Research Journey Agent",
        title="Application name",
        description="Name shown in API documentation and the web interface.",
    )
    app_version: str = Field(
        default="0.1.0",
        title="Application version",
        description="Version of the application.",
    )
    app_env: Literal["development", "test", "production"] = Field(
        default="development",
        title="Application environment",
        description="Current runtime environment.",
    )
    host: str = Field(
        default="127.0.0.1",
        title="Host",
        description="Network address used by the FastAPI application.",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        title="Port",
        description="TCP port used by the FastAPI application.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        title="Log level",
        description="Minimum application log level.",
    )
    log_format: Literal["text", "json"] = Field(
        default="text",
        title="Log format",
        description="Application log output format.",
    )
    log_access_enabled: bool = Field(
        default=True,
        title="Enable access log",
        description="Whether project access logging middleware is enabled.",
    )
    trust_inbound_request_id: bool = Field(
        default=False,
        title="Trust inbound request ID",
        description="Whether a valid inbound X-Request-ID header may be reused.",
    )
    app_secret_key: SecretStr | None = Field(
        default=None,
        repr=False,
        title="Application secret key",
        description="Required only when signed cookies, sessions, or tokens are enabled.",
    )
    cors_origins: str = Field(
        default="",
        title="CORS origins",
        description="Comma-separated origins allowed to call the API.",
    )
    docs_enabled: bool = Field(
        default=True,
        title="Enable API documentation",
        description="Whether to enable the API documentation.",
    )
    health_details_enabled: bool = Field(
        default=True,   
        title="Enable health details",
        description="Whether to enable detailed health checks.",
    )
    # -------------------------------------------------------------------------
    # Data directories and SQLite
    # -------------------------------------------------------------------------

    data_dir: Path = Field(
        default=Path("./data"),
        title="Data directory",
        description="Root directory for runtime data.",
    )
    raw_pdf_dir: Path = Field(
        default=Path("./data/raw"),
        title="Raw PDF directory",
        description="Directory used to store uploaded PDF files.",
    )
    parsed_document_dir: Path = Field(
        default=Path("./data/parsed"),
        title="Parsed document directory",
        description="Directory used to store parsed Markdown and JSON files.",
    )
    document_asset_dir: Path = Field(
        default=Path("./data/assets"),
        title="Document asset directory",
        description="Directory used to store extracted figures, tables, and assets.",
    )
    sqlite_path: Path = Field(
        default=Path("./data/app.db"),
        title="SQLite path",
        description="SQLite database file used for metadata, chat history, and preferences.",
    )
    sqlite_busy_timeout_ms: int = Field(
        default=5000,
        ge=0,
        title="SQLite busy timeout",
        description="Maximum lock wait time in milliseconds.",
    )
    sqlite_enable_wal: bool = Field(
        default=True,
        title="Enable SQLite WAL",
        description="Whether SQLite write-ahead logging is enabled.",
    )

    # -------------------------------------------------------------------------
    # Large language model
    # -------------------------------------------------------------------------

    llm_provider: str = Field(
        default="openai_compatible",
        title="LLM provider",
        description="Protocol or provider used by the chat model client.",
    )
    llm_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        title="LLM API key",
        description="Credential used to call the chat model service.",
    )
    llm_base_url: str | None = Field(
        default=None,
        title="LLM base URL",
        description="Base URL of the chat model API.",
    )
    llm_model: str | None = Field(
        default=None,
        title="LLM model",
        description="Model used for question answering and evidence assessment.",
    )
    llm_timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        title="LLM timeout",
        description="Maximum duration of one LLM request in seconds.",
    )
    llm_max_retries: int = Field(
        default=2,
        ge=0,
        title="LLM retry count",
        description="Maximum retry count after a failed LLM request.",
    )
    llm_temperature: float = Field(
        default=0.1,
        ge=0,
        le=2,
        title="LLM temperature",
        description="Sampling temperature used for generated answers.",
    )

    # -------------------------------------------------------------------------
    # PDF parsing
    # -------------------------------------------------------------------------

    pdf_parser_primary: Literal["mineru", "pymupdf"] = Field(
        default="mineru",
        title="Primary PDF parser",
        description="Parser used first during document ingestion.",
    )
    pdf_parser_fallback: Literal["mineru", "pymupdf"] = Field(
        default="pymupdf",
        title="Fallback PDF parser",
        description="Parser used when the primary parser fails.",
    )

    mineru_mode: Literal["local_service", "cloud_api"] = Field(
        default="local_service",
        title="MinerU mode",
        description="Whether MinerU runs as a local service or a cloud API.",
    )
    mineru_base_url: str = Field(
        default="http://127.0.0.1:8001",
        title="MinerU local base URL",
        description="Base URL of the locally running MinerU service.",
    )
    mineru_api_base: str | None = Field(
        default=None,
        title="MinerU cloud API base URL",
        description="Base URL used only when MinerU cloud mode is enabled.",
    )
    mineru_api_token: SecretStr | None = Field(
        default=None,
        repr=False,
        title="MinerU cloud API token",
        description="Credential used only when MinerU cloud mode is enabled.",
    )
    mineru_timeout_seconds: float = Field(
        default=900.0,
        gt=0,
        title="MinerU timeout",
        description="Maximum duration of one parsing task in seconds.",
    )
    mineru_backend: Literal["pipeline", "vlm-engine", "hybrid-engine", "vlm-http-client", "hybrid-http-client"] = Field(
        default="hybrid-engine",
        title="MinerU parse backend",
        description="Backend parameter sent to MinerU's file_parse API.",
    )
    mineru_poll_interval_seconds: float = Field(
        default=2.0,
        gt=0,
        title="MinerU polling interval",
        description="Interval between asynchronous task status checks.",
    )
    mineru_max_concurrency: int = Field(
        default=1,
        ge=1,
        title="MinerU maximum concurrency",
        description="Maximum number of parsing tasks processed concurrently.",
    )
    mineru_output_format: Literal["json", "markdown"] = Field(
        default="json",
        title="MinerU output format",
        description="Preferred format of the MinerU parsing result.",
    )

    pymupdf_validate_pdf: bool = Field(
        default=True,
        title="Validate PDFs with PyMuPDF",
        description="Whether uploaded files are validated with PyMuPDF.",
    )
    pymupdf_enable_text_fallback: bool = Field(
        default=True,
        title="Enable PyMuPDF text fallback",
        description="Whether PyMuPDF may extract text when MinerU is unavailable.",
    )
    pymupdf_render_dpi: int = Field(
        default=150,
        ge=72,
        title="PyMuPDF render DPI",
        description="Resolution used when rendering PDF pages as images.",
    )

    # -------------------------------------------------------------------------
    # Text embedding
    # -------------------------------------------------------------------------

    text_embedding_provider: Literal["dashscope_native", "dashscope_openai_compatible", "local_tei"] = Field(
        default="local_tei",
        title="Text embedding provider",
        description="API protocol used by the text embedding client.",
    )
    text_embedding_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        title="Text embedding API key",
        description="Credential used to call the text embedding service. Local TEI does not require it by default.",
    )
    text_embedding_base_url: str = Field(
        default="http://127.0.0.1:8080",
        title="Text embedding base URL",
        description="Base URL of the text embedding service.",
    )
    text_embedding_model: str = Field(
        default="Qwen/Qwen3-Embedding-0.6B",
        title="Text embedding model",
        description="Model used to embed document chunks and user queries.",
    )
    text_embedding_dimension: int = Field(
        default=1024,
        ge=1,
        title="Text embedding dimension",
        description="Dimension of each dense text embedding vector.",
    )
    text_embedding_batch_size: int = Field(
        default=10,
        ge=1,
        le=20,
        title="Text embedding batch size",
        description="Maximum number of texts sent in one synchronous request.",
    )
    text_embedding_timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        title="Text embedding timeout",
        description="Maximum duration of one embedding request in seconds.",
    )
    text_embedding_max_retries: int = Field(
        default=2,
        ge=0,
        title="Text embedding retry count",
        description="Maximum retry count after a failed embedding request.",
    )
    text_embedding_query_input_type: str = Field(
        default="query",
        title="Query input type",
        description="DashScope input type used for user queries.",
    )
    text_embedding_document_input_type: str = Field(
        default="document",
        title="Document input type",
        description="DashScope input type used for document chunks.",
    )
    text_embedding_output_type: str = Field(
        default="dense",
        title="Text embedding output type",
        description="Embedding output format. The MVP uses dense vectors.",
    )

    # -------------------------------------------------------------------------
    # Visual embedding
    # -------------------------------------------------------------------------
    reranker_base_url: str = Field(
        default="http://127.0.0.1:8081",
        title="Reranker base URL",
        description="Base URL of the reranker service.",
    )
    reranker_model: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        title="Reranker model",
        description="Model used for reranking documents.",
    )
    reranker_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        title="Reranker timeout",
        description="Maximum duration of one reranking request in seconds.",
    )
    reranker_max_retries: int = Field(
        default=2,
        ge=0,
        title="Reranker retry count",
        description="Maximum retry count after a failed reranking request.",
    )

    retriever_candidate_top_k: int = Field(
        default=20,
        ge=1,
        title="Retriever candidate top K",
        description="Number of candidates returned by the initial retrieval stage.",
    )
    retriever_final_top_k: int = Field(
        default=6,
        ge=1,
        title="Retriever final top K",
        description="Number of candidates retained for the final LLM context.",
    )
    # -------------------------------------------------------------------------
    # Visual embedding
    # -------------------------------------------------------------------------

    visual_embedding_enabled: bool = Field(
        default=False,
        title="Enable visual embedding",
        description="Whether visual indexing and retrieval are enabled.",
    )
    visual_embedding_provider: str = Field(
        default="bge_visualized_service",
        title="Visual embedding provider",
        description="Provider used by the visual embedding client.",
    )
    visual_embedding_base_url: str = Field(
        default="http://127.0.0.1:8002",
        title="Visual embedding base URL",
        description="Base URL of the local visual embedding service.",
    )
    visual_embedding_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        title="Visual embedding API key",
        description="Optional credential used by the visual embedding service.",
    )
    visual_embedding_model: str = Field(
        default="BAAI/bge-visualized-m3",
        title="Visual embedding model",
        description="Model used to embed extracted figures and diagrams.",
    )
    visual_embedding_dimension: int = Field(
        default=1024,
        ge=1,
        title="Visual embedding dimension",
        description="Dimension of each visual embedding vector.",
    )
    visual_embedding_batch_size: int = Field(
        default=4,
        ge=1,
        title="Visual embedding batch size",
        description="Maximum number of images sent in one request.",
    )
    visual_embedding_timeout_seconds: float = Field(
        default=180.0,
        gt=0,
        title="Visual embedding timeout",
        description="Maximum duration of one visual embedding request in seconds.",
    )

    bge_visualized_text_model: str = Field(
        default="BAAI/bge-m3",
        title="BGE text model",
        description="Text encoder used by the visual embedding model.",
    )
    bge_visualized_weight_path: Path = Field(
        default=Path("./models/Visualized_m3.pth"),
        title="BGE visualized weight path",
        description="Local path of the visual embedding model weights.",
    )
    bge_visualized_device: str = Field(
        default="cuda",
        title="BGE visualized device",
        description="Execution device used by the visual embedding model.",
    )
    bge_visualized_allow_remote_code: bool = Field(
        default=False,
        title="Allow BGE remote code",
        description="Whether remote model repository code may be executed.",
    )

    # -------------------------------------------------------------------------
    # Ingestion, chunking, retrieval, and agent limits
    # -------------------------------------------------------------------------

    max_upload_mb: int = Field(
        default=50,
        ge=1,
        title="Maximum upload size",
        description="Maximum allowed PDF upload size in megabytes.",
    )
    retrieval_top_k: int = Field(
        default=6,
        ge=1,
        title="Retrieval top K",
        description="Default number of retrieved chunks.",
    )
    chunk_size_chars: int = Field(
        default=1800,
        ge=1,
        title="Chunk size",
        description="Target chunk size measured in characters.",
    )
    chunk_overlap_chars: int = Field(
        default=250,
        ge=0,
        title="Chunk overlap",
        description="Character overlap between adjacent chunks.",
    )
    min_chunk_chars: int = Field(
        default=120,
        ge=1,
        title="Minimum chunk size",
        description="Minimum character count before a short chunk is merged.",
    )
    ingestion_max_concurrency: int = Field(
        default=1,
        ge=1,
        title="Ingestion maximum concurrency",
        description="Maximum number of papers ingested concurrently.",
    )

    retrieval_candidate_top_k: int = Field(
        default=20,
        ge=1,
        title="Candidate retrieval top K",
        description="Number of chunks returned by the initial retrieval stage.",
    )
    retrieval_final_top_k: int = Field(
        default=6,
        ge=1,
        title="Final retrieval top K",
        description="Number of chunks retained for the final LLM context.",
    )
    figure_retrieval_top_k: int = Field(
        default=6,
        ge=1,
        title="Figure retrieval top K",
        description="Number of figures returned by visual retrieval.",
    )
    max_retrieval_attempts: int = Field(
        default=2,
        ge=1,
        title="Maximum retrieval attempts",
        description="Maximum number of query rewrite and retrieval attempts.",
    )
    max_agent_steps: int = Field(
        default=4,
        ge=1,
        title="Maximum agent steps",
        description="Maximum number of agent loop iterations per question.",
    )

    chat_recent_messages: int = Field(
        default=6,
        ge=0,
        title="Recent chat messages",
        description="Number of recent messages included in the active context.",
    )
    chat_summary_trigger_messages: int = Field(
        default=12,
        ge=1,
        title="Chat summary trigger",
        description="Message count that triggers conversation summarization.",
    )
    query_rewrite_messages: int = Field(
        default=4,
        ge=0,
        title="Query rewrite messages",
        description="Number of prior messages used during query rewriting.",
    )
    max_history_chars: int = Field(
        default=8000,
        ge=0,
        title="Maximum history characters",
        description="Maximum chat history size included in one request.",
    )
    require_citations: bool = Field(
        default=True,
        title="Require citations",
        description="Whether answers must include evidence citations.",
    )
    refuse_without_evidence: bool = Field(
        default=True,
        title="Refuse without evidence",
        description="Whether unsupported answers must be refused.",
    )
    allow_remote_model_code: bool = Field(
        default=False,
        title="Allow remote model code",
        description="Whether model loaders may execute remote custom code.",
    )

    # -------------------------------------------------------------------------
    # Qdrant
    # -------------------------------------------------------------------------

    vector_store_backend: Literal["qdrant"] = Field(
        default="qdrant",
        title="Vector store backend",
        description="Vector database used by the application.",
    )
    qdrant_mode: Literal["local", "server"] = Field(
        default="local",
        title="Qdrant mode",
        description="Embedded local mode or independent server mode.",
    )
    qdrant_path: Path = Field(
        default=Path("./data/qdrant"),
        title="Qdrant local path",
        description="Persistent directory used by Qdrant Local Mode.",
    )
    qdrant_url: str | None = Field(
        default=None,
        title="Qdrant server URL",
        description="Service URL used by Qdrant Server Mode.",
    )
    qdrant_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        title="Qdrant API key",
        description="Credential used by a protected Qdrant server or Qdrant Cloud.",
    )
    qdrant_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        title="Qdrant timeout",
        description="Maximum duration of one Qdrant request in seconds.",
    )
    qdrant_prefer_grpc: bool = Field(
        default=False,
        title="Prefer Qdrant gRPC",
        description="Whether Server Mode should prefer gRPC over HTTP.",
    )
    qdrant_check_compatibility: bool = Field(
        default=True,
        title="Check Qdrant compatibility",
        description="Whether client and server compatibility is checked.",
    )
    qdrant_text_collection: str = Field(
        default="paper_text__qwen3_embedding_0_6b__1024__v1",
        title="Text collection",
        description="Qdrant collection used for document chunk vectors.",
    )
    qdrant_figure_collection: str = Field(
        default="paper_figures__bge_visualized_m3__1024__v1",
        title="Figure collection",
        description="Qdrant collection used for visual vectors.",
    )
    qdrant_distance: Literal["cosine", "dot", "euclid", "manhattan"] = Field(
        default="cosine",
        title="Qdrant distance metric",
        description="Distance metric used for vector similarity search.",
    )
    qdrant_recreate_collections: bool = Field(
        default=False,
        title="Recreate Qdrant collections",
        description="Whether collections are deleted and recreated at startup.",
    )
    index_version: str = Field(
        default="v1",
        title="Index version",
        description="Version identifier of the current vector index schema.",
    )

    # -------------------------------------------------------------------------
    # Derived values and cross-field validation
    # -------------------------------------------------------------------------

    @property
    def cors_origin_list(self) -> list[str]:
        """Return CORS origins as a normalized list."""

        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    def project_path(self, value: Path) -> Path:
        """Resolve a relative path against the project root."""

        if value.is_absolute():
            return value
        return (PROJECT_ROOT / value).resolve()

    @model_validator(mode="after")
    def validate_related_settings(self) -> "Settings":
        """Validate settings whose correctness depends on other settings."""

        if self.chunk_overlap_chars >= self.chunk_size_chars:
            raise ValueError(
                "CHUNK_OVERLAP_CHARS must be smaller than CHUNK_SIZE_CHARS."
            )

        if self.retrieval_final_top_k > self.retrieval_candidate_top_k:
            raise ValueError(
                "RETRIEVAL_FINAL_TOP_K cannot exceed RETRIEVAL_CANDIDATE_TOP_K."
            )

        embedding_batch_limits = {
            "text-embedding-v4": 10,
            "qwen3.7-text-embedding": 20,
        }
        model_batch_limit = embedding_batch_limits.get(self.text_embedding_model)
        if model_batch_limit and self.text_embedding_batch_size > model_batch_limit:
            raise ValueError(
                f"{self.text_embedding_model} supports at most "
                f"{model_batch_limit} texts per synchronous request."
            )

        if self.text_embedding_provider != "local_tei" and (
            not self.text_embedding_api_key or not self.text_embedding_api_key.get_secret_value().strip()
        ):
            raise ValueError("TEXT_EMBEDDING_API_KEY cannot be empty.")

        embedding_base_url = self.text_embedding_base_url.rstrip("/")
        if self.text_embedding_provider == "local_tei" and not embedding_base_url:
            raise ValueError("local_tei requires a non-empty TEXT_EMBEDDING_BASE_URL.")
        if (
            self.text_embedding_provider == "dashscope_native"
            and not embedding_base_url.endswith("/api/v1")
        ):
            raise ValueError(
                "dashscope_native requires a TEXT_EMBEDDING_BASE_URL ending in /api/v1."
            )
        if (
            self.text_embedding_provider == "dashscope_openai_compatible"
            and not embedding_base_url.endswith("/compatible-mode/v1")
        ):
            raise ValueError(
                "dashscope_openai_compatible requires a TEXT_EMBEDDING_BASE_URL "
                "ending in /compatible-mode/v1."
            )

        if self.qdrant_mode == "server" and not self.qdrant_url:
            raise ValueError("QDRANT_URL is required when QDRANT_MODE=server.")

        if self.mineru_mode == "cloud_api":
            if not self.mineru_api_base:
                raise ValueError(
                    "MINERU_API_BASE is required when MINERU_MODE=cloud_api."
                )
            if not self.mineru_api_token or not self.mineru_api_token.get_secret_value().strip():
                raise ValueError(
                    "MINERU_API_TOKEN is required when MINERU_MODE=cloud_api."
                )

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load, validate, and cache the application settings."""

    return Settings()
