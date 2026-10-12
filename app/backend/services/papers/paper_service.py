from __future__ import annotations

import asyncio
import logging
import re
from uuid import uuid4

from app.backend.config import Settings
from http import HTTPStatus
from app.backend.core.exceptions import AppError

from app.backend.infrastructure.clients.mineru_client import MinerUClient
from app.backend.infrastructure.clients.embedding_client import BM25Encoder, EmbeddingClient
from app.backend.infrastructure.stores.file_store import FileStore
from app.backend.infrastructure.stores.metadata_store import MetadataStore
from app.backend.infrastructure.stores.vector_store import VectorStore
from app.backend.services.papers.ingestion.chunker import Chunker
from app.backend.services.papers.ingestion.document_builder import MinerUDocumentBuilder
from app.backend.services.papers.ingestion.normalizer import (
    require_content_list,
    require_text_blocks,
    extract_document_metadata,
    require_paper_name,
    require_normalized_text,
    normalize_paper_name_key,
)
from app.backend.services.papers.models import PaperChunk, PaperParseResult


logger = logging.getLogger(__name__)
PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


def _collapse_ws(text: str) -> str:
    """合并空白并去除首尾空格，用于判断两段文本是否实质相同。"""
    return re.sub(r"\s+", " ", text or "").strip()


class PaperService:
    def __init__(self, *, settings: Settings, metadata_store: MetadataStore, file_store: FileStore, mineru_client: MinerUClient, text_embedding_client: EmbeddingClient, vector_store: VectorStore, bm25_encoder: BM25Encoder) -> None:
        self.settings = settings
        self.metadata_store = metadata_store
        self.file_store = file_store
        self.mineru_client = mineru_client
        self.text_embedding_client = text_embedding_client
        self.bm25_encoder = bm25_encoder
        self.vector_store = vector_store
        self.chunker = Chunker(chunk_size=settings.chunk_size_chars, chunk_overlap=settings.chunk_overlap_chars)
        self.document_builder = MinerUDocumentBuilder()

    async def upload_pdf(self, *, filename: str, content_type: str | None, payload: bytes) -> PaperParseResult:
        self.validate_pdf_upload(filename=filename, content_type=content_type, payload=payload, max_upload_mb=self.settings.max_upload_mb)
        logger.info("论文上传开始 文件名%s", filename)

        paper_id = uuid4().hex
        temp_pdf_path = await self.file_store.save_temporary_upload(paper_id=paper_id, filename=filename, payload=payload)
        paper_artifacts_may_exist = False
        vectors_may_exist = False

        try:
            title_result = await self.mineru_client.parse_pdf(temp_pdf_path, start_page_id=0, end_page_id=1)
            paper_name = require_paper_name(title_result)

            paper_name_key = normalize_paper_name_key(paper_name)
            if await self.metadata_store.paper_name_exists(paper_name_key):
                raise AppError(HTTPStatus.CONFLICT, message="论文已存在", context={"paper_name": paper_name})

            logger.info("MinerU标题预解析完成 论文名%s", paper_name)

            full_result = await self.mineru_client.parse_pdf(temp_pdf_path, return_images=True)
            text_blocks = require_text_blocks(full_result)

            normalized_text = require_normalized_text(text_blocks)

            logger.info("MinerU全文解析完成 论文名%s paper_id%s 文本块数%s", paper_name, paper_id, len(text_blocks))

            content_list = require_content_list(full_result)
            text_docs, structured_docs = self.document_builder.build(content_list=content_list, paper_id=paper_id, paper_name=paper_name)
            chunk_docs = self.chunker.split_documents(text_docs, structured_docs)
            paper_chunks = self.chunker.build_paper_chunks(paper_id=paper_id, chunk_docs=chunk_docs)

            logger.info("论文切分完成 论文名%s 文本块数%s 切分块数%s", paper_name, len(text_blocks), len(paper_chunks))

            dense_texts: list[str] = []
            sparse_texts: list[str] = []
            for chunk in paper_chunks:
                dense_texts.append(self.build_embedding_text(chunk))
                sparse_texts.append(chunk.text)
            dense_vectors = await self.text_embedding_client.embed_documents(dense_texts)
            sparse_vectors = await asyncio.to_thread(
                self.bm25_encoder.encode_documents,
                sparse_texts,
            )

            logger.info("文本向量生成完成 论文名%s 向量数量%s 向量维度%s", paper_name, len(dense_vectors), len(dense_vectors[0]) if dense_vectors else 0)
            logger.info("稀疏向量生成完成 论文名%s 向量数量%s", paper_name, len(sparse_vectors))

            vectors_may_exist = True
            await self.vector_store.upsert_vectors(paper_chunks=paper_chunks, dense_vectors=dense_vectors, sparse_vectors=sparse_vectors)

            document_metadata = extract_document_metadata(full_result, paper_name=paper_name)
            paper_artifacts_may_exist = True
            parsed_files = await self.file_store.save_mineru_parse_files(paper_id=paper_id, files=full_result.files, normalized_text=normalized_text)
            await self.file_store.promote_uploaded_pdf(source_path=temp_pdf_path, paper_id=paper_id, filename=filename)

            page_count = self.count_pages(text_blocks)
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
        except Exception:
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
            try:
                await self.file_store.discard_temporary_upload(temp_pdf_path)
            except Exception:
                logger.error("临时上传文件清理失败 paper_id=%s", paper_id, exc_info=True)

        logger.info("数据已存入数据库 论文上传完成 论文名%s 页数%s", paper_name, page_count)

        return PaperParseResult(paper_id=paper_id, paper_name=paper_name, page_count=page_count)

    async def delete_paper(self, paper_id: str) -> None:
        if await self.metadata_store.get_paper_by_id(paper_id) is None:
            raise AppError(HTTPStatus.NOT_FOUND, message="论文不存在", context={"paper_id": paper_id})
        await self.vector_store.delete_vectors(paper_id=paper_id)
        await self.file_store.remove_paper_artifacts(paper_id)
        await self.metadata_store.delete_paper(paper_id)

    @staticmethod
    def validate_pdf_upload( *, filename: str, content_type: str | None, payload: bytes, max_upload_mb: int) -> None:
        if not filename.lower().endswith(".pdf"):
            raise AppError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        if content_type and content_type.lower() not in PDF_CONTENT_TYPES:
            raise AppError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        if not payload.startswith(b"%PDF-"):
            raise AppError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)

        max_bytes = max_upload_mb * 1024 * 1024
        if len(payload) > max_bytes:
            raise AppError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, context={"filename": filename, "max_upload_mb": max_upload_mb})

    @staticmethod
    def build_embedding_text(chunk: PaperChunk) -> str:
        metadata = chunk.metadata
        section_title = metadata.get("section_title")
        caption = metadata.get("caption")

        # 图片/图表去重，表格仍然保留 caption 作为语义来源。
        if caption and _collapse_ws(caption) == _collapse_ws(chunk.text):
            caption = None

        parts = [
            f"Section title: {section_title}" if section_title else "",
            f"Caption: {caption}" if caption else "",
            "Content:",
            chunk.text,
        ]
        return "\n".join(part for part in parts if part)

    @staticmethod
    def count_pages(text_blocks) -> int | None:
        pages = [page for block in text_blocks for page in block.metadata.get("page_numbers", []) if isinstance(page, int) and not isinstance(page, bool)]
        if not pages:
            return None
        return max(pages)
