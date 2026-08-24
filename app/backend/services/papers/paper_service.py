from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from uuid import uuid4

from app.backend.config import Settings
from app.backend.core.codes import CommonCode
from app.backend.core.exceptions import (
    AppError,
    DuplicatePaperError,
    FileStorageUnavailableError,
    LangChainUnavailableError,
    MinerUResultInvalidError,
    MinerUUnavailableError,
    PaperFormatUnsupportedError,
    SQLiteUnavailableError,
    TextEmbeddingError,
    QdrantUnavailableError,
)
from app.backend.infrastructure.clients.mineru_client import MinerUProtocolError, MinerUServiceError, MinerUClient
from app.backend.infrastructure.clients.embedding_client import EmbeddingClient
from app.backend.infrastructure.stores.file_store import FileStore
from app.backend.infrastructure.stores.metadata_store import MetadataStore
from app.backend.infrastructure.stores.vector_store import VectorStore
from app.backend.services.papers.ingestion.chunker import Chunker
from app.backend.services.papers.ingestion.doc_clean import MarkdownCleaner
from app.backend.services.papers.ingestion.normalizer import (
    load_content_list,
    build_text_blocks,
    extract_document_metadata,
    extract_paper_name,
    join_block_text,
    normalize_paper_name_key,
    read_markdown,
)
from app.backend.services.papers.models import PaperChunk, PaperParseResult, PaperDeleteResult


logger = logging.getLogger(__name__)

PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


class PaperService:
    def __init__(self, *, settings: Settings, metadata_store: MetadataStore, file_store: FileStore, mineru_client: MinerUClient, text_embedding_client: EmbeddingClient, vector_store: VectorStore) -> None:
        self.settings = settings
        self.metadata_store = metadata_store
        self.file_store = file_store
        self.mineru_client = mineru_client
        self.text_embedding_client = text_embedding_client
        self.vector_store = vector_store
        self.chunker = Chunker(chunk_size=settings.chunk_size_chars, chunk_overlap=settings.chunk_overlap_chars)
        self.markdown_cleaner = MarkdownCleaner()

    async def upload_pdf(self, *, filename: str, content_type: str | None, payload: bytes) -> PaperParseResult:
        self.validate_pdf_upload(filename=filename, content_type=content_type, payload=payload)
        logger.info("论文上传开始 文件名%s", filename)

        paper_id = uuid4().hex
        temp_pdf_path = await self.file_store.save_temporary_upload(paper_id=paper_id, filename=filename, payload=payload)
        paper_artifacts_may_exist = False
        vectors_may_exist = False

        try:
            title_result = await self.parse_with_mineru(temp_pdf_path, start_page_id=0, end_page_id=1, stage="title_preparse")
            paper_name = extract_paper_name(title_result)
            if paper_name is None:
                raise MinerUResultInvalidError(context={"stage": "title_preparse", "reason": "paper_name_missing"})

            paper_name_key = normalize_paper_name_key(paper_name)
            if await self.paper_exists(paper_name_key):
                logger.info("论文重复 论文名%s", paper_name)
                raise DuplicatePaperError(paper_name=paper_name)

            logger.info("MinerU标题预解析完成 论文名%s", paper_name)

            full_result = await self.parse_with_mineru(temp_pdf_path, stage="full_parse")
            text_blocks = build_text_blocks(full_result)
            if not text_blocks:
                raise MinerUResultInvalidError(context={"stage": "full_parse", "reason": "text_blocks_empty"})

            normalized_text = join_block_text(text_blocks)
            if not normalized_text.strip():
                raise MinerUResultInvalidError(context={"stage": "full_parse", "reason": "normalized_text_empty"})

            logger.info("MinerU全文解析完成 论文名%s paper_id%s 文本块数%s", paper_name, paper_id, len(text_blocks))

            markdown_text = read_markdown(full_result)
            content_list = load_content_list(full_result)
            if not markdown_text:
                raise MinerUResultInvalidError(context={"stage": "full_parse", "reason": "markdown_missing"})
            if not isinstance(content_list, list):
                raise MinerUResultInvalidError(context={"stage": "full_parse", "reason": "content_list_invalid"})
            try:
                text_docs, structured_docs = self.markdown_cleaner.clean(markdown_text, content_list=content_list, paper_id=paper_id, paper_name=paper_name)
                chunk_docs = self.chunker.split_documents(text_docs, structured_docs)
                paper_chunks = self.chunker.build_paper_chunks(paper_id=paper_id, chunk_docs=chunk_docs)
            except ValueError as error:
                raise MinerUResultInvalidError(context={"stage": "chunking", "reason": str(error)}) from error
            except Exception as error:
                raise LangChainUnavailableError(context={"stage": "chunking", "reason": "chunking_failed"}) from error

            if not paper_chunks:
                raise LangChainUnavailableError(context={"stage": "chunking", "reason": "paper_chunks_empty"})

            logger.info("论文切分完成 论文名%s 文本块数%s 切分块数%s", paper_name, len(text_blocks), len(paper_chunks))

            try:
                texts = [self.build_embedding_text(chunk) for chunk in paper_chunks]
                vectors = await self.text_embedding_client.embed_documents(texts)
            except Exception as error:
                raise TextEmbeddingError(context={"stage": "embedding", "reason": "embedding_failed"}) from error

            logger.info("文本向量生成完成 论文名%s 向量数量%s 向量维度%s", paper_name, len(vectors), len(vectors[0]) if vectors else 0)

            try:
                await self.vector_store.upsert_vectors(paper_chunks=paper_chunks, vectors=vectors)
                vectors_may_exist = True
            except Exception as error:
                raise QdrantUnavailableError(context={"stage": "vector_store", "reason": "upsert_text_chunks_failed"}) from error

            document_metadata = extract_document_metadata(full_result, paper_name=paper_name)
            paper_artifacts_may_exist = True
            parsed_files = await self.file_store.save_mineru_parse_files(paper_id=paper_id, files=full_result.files, normalized_text=normalized_text)
            await self.file_store.promote_uploaded_pdf(source_path=temp_pdf_path, paper_id=paper_id, filename=filename)

            page_count = self.count_pages(text_blocks)
            try:
                await self.metadata_store.create_paper(
                    paper_id=paper_id,
                    paper_name=paper_name,
                    paper_name_key=paper_name_key,
                    filename=filename,
                    file_size_bytes=len(payload),
                    status="parsed",
                    authors=document_metadata.authors,
                    affiliations=document_metadata.affiliations,
                    journal=document_metadata.journal,
                    publisher=document_metadata.publisher,
                    doi=document_metadata.doi,
                    publication_year=document_metadata.publication_year,
                    source=document_metadata.source,
                    abstract=document_metadata.abstract,
                    parsed_file_paths=parsed_files,
                    paper_chunks=paper_chunks
                )
            except sqlite3.IntegrityError as error:
                raise DuplicatePaperError(paper_name=paper_name) from error
            except Exception as error:
                raise SQLiteUnavailableError(context={"operation": "create_paper"}) from error
        except Exception:
            await self.file_store.discard_temporary_upload(temp_pdf_path)
            if vectors_may_exist:
                try:
                    await self.vector_store.delete_vectors(paper_id=paper_id)
                except Exception as cleanup_error:
                    logger.error("上传失败清理向量失败 paper_id=%s error=%s", paper_id, cleanup_error, exc_info=True)
            if paper_artifacts_may_exist:
                try:
                    await self.file_store.remove_paper_artifacts(paper_id)
                except Exception as cleanup_error:
                    logger.error("上传失败清理文件失败 paper_id=%s error=%s", paper_id, cleanup_error, exc_info=True)
            raise
        finally:
            await self.file_store.discard_temporary_upload(temp_pdf_path)

        logger.info("数据已存入数据库 论文上传完成 论文名%s 页数%s", paper_name, page_count)

        return PaperParseResult(
            paper_id=paper_id,
            paper_name=paper_name,
            filename=filename,
            file_size_bytes=len(payload),
            text_block_count=len(text_blocks),
            page_count=page_count,
            status="parsed",
            parsed_files=parsed_files,
            metadata=document_metadata,
        )

    async def delete_paper(self, paper_id: str) -> PaperDeleteResult:
        try:
            paper_record = await self.metadata_store.get_paper_by_id(paper_id)
        except Exception as error:
            raise SQLiteUnavailableError(context={"operation": "delete_paper"}) from error
        if paper_record is None:
            raise AppError(CommonCode.NOT_FOUND, context={"paper_id": paper_id, "reason": "paper_not_found"})

        try:
            await self.vector_store.delete_vectors(paper_id=paper_id)
        except Exception as error:
            raise QdrantUnavailableError(context={"operation": "delete_vectors"}) from error

        try:
            await self.file_store.remove_paper_artifacts(paper_id)
        except Exception as error:
            raise FileStorageUnavailableError(context={"operation": "remove_paper_artifacts"}) from error

        try:
            await self.metadata_store.delete_paper(paper_id)
        except Exception as error:
            raise SQLiteUnavailableError(context={"operation": "delete_paper"}) from error

        return PaperDeleteResult(
            paper_id=paper_record.paper_id,
            paper_name=paper_record.paper_name,
            filename=paper_record.filename,
            file_size_bytes=paper_record.file_size_bytes,
            text_block_count=0,
            page_count=None,
            status="deleted",
        )

    def validate_pdf_upload(self, *, filename: str, content_type: str | None, payload: bytes) -> None:
        if not filename.lower().endswith(".pdf"):
            raise PaperFormatUnsupportedError(filename=filename, content_type=content_type)
        if content_type and content_type.lower() not in PDF_CONTENT_TYPES:
            raise PaperFormatUnsupportedError(filename=filename, content_type=content_type)
        if not payload.startswith(b"%PDF-"):
            raise PaperFormatUnsupportedError(filename=filename, content_type=content_type)

        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if len(payload) > max_bytes:
            raise AppError(CommonCode.PAYLOAD_TOO_LARGE, context={"filename": filename, "max_upload_mb": self.settings.max_upload_mb})

    @staticmethod
    def build_embedding_text(chunk: PaperChunk) -> str:
        metadata = chunk.metadata
        paper_name = metadata.get("paper_name")
        parent_title = metadata.get("parent_title")
        section_title = metadata.get("section_title")
        section_level = metadata.get("section_level")

        parts = [
            f"Paper title: {paper_name}" if paper_name else "",
            f"Parent section: {parent_title}" if parent_title else "",
            f"Section title: {section_title}" if section_title else "",
            f"Section level: {section_level}" if section_level is not None else "",
            "Content:",
            chunk.text,
        ]
        return "\n".join(part for part in parts if part)

    async def paper_exists(self, paper_name_key: str) -> bool:
        try:
            return await self.metadata_store.paper_name_exists(paper_name_key)
        except Exception as error:
            raise SQLiteUnavailableError(context={"operation": "paper_name_exists"}) from error

    async def parse_with_mineru(self, file_path: Path, *, stage: str, start_page_id: int | None = None, end_page_id: int | None = None):
        try:
            return await self.mineru_client.parse_pdf(file_path, start_page_id=start_page_id, end_page_id=end_page_id)
        except MinerUServiceError as error:
            context: dict[str, object] = {
                "stage": stage,
                "backend": self.mineru_client.backend,
                "target": self.mineru_client.parse_url,
            }
            if error.status_code is not None:
                context["downstream_status_code"] = error.status_code
            if error.response_body:
                context["downstream_response"] = error.response_body
            raise MinerUUnavailableError(context=context) from error
        except MinerUProtocolError as error:
            raise MinerUResultInvalidError(
                context={
                    "stage": stage,
                    "backend": self.mineru_client.backend,
                    "target": self.mineru_client.parse_url,
                }
            ) from error

    @staticmethod
    def count_pages(text_blocks) -> int | None:
        pages = [page for block in text_blocks for page in (block.metadata.get("page_start"), block.metadata.get("page_end")) if isinstance(page, int)]
        if not pages:
            return None
        return max(pages)
