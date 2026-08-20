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
)
from app.backend.infrastructure.clients.mineru_client import MinerUProtocolError, MinerUServiceError, MinerUClient
from app.backend.infrastructure.stores.file_store import FileStore
from app.backend.infrastructure.stores.metadata_store import MetadataStore
from app.backend.services.papers.ingestion.chunker import Chunker
from app.backend.services.papers.ingestion.normalizer import (
    build_metadata_documents,
    build_text_blocks,
    can_merge_by_index,
    extract_document_metadata,
    extract_paper_name,
    join_block_text,
    normalize_paper_name_key,
    read_markdown,
)
from app.backend.services.papers.models import PaperParseResult, PaperDeleteResult


logger = logging.getLogger(__name__)

PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


class PaperService:
    def __init__(self, *, settings: Settings, metadata_store: MetadataStore, file_store: FileStore, mineru_client: MinerUClient) -> None:
        self.settings = settings
        self.metadata_store = metadata_store
        self.file_store = file_store
        self.mineru_client = mineru_client
        self.chunker = Chunker(chunk_size=settings.chunk_size_chars, chunk_overlap=settings.chunk_overlap_chars)

    async def upload_and_chunker_pdf(self, *, filename: str, content_type: str | None, payload: bytes) -> PaperParseResult:
        self.validate_pdf_upload(filename=filename, content_type=content_type, payload=payload)
        logger.info("论文上传开始 文件名%s", filename)

        paper_id = uuid4().hex
        temp_pdf_path = await self.file_store.save_temporary_upload(paper_id=paper_id, filename=filename, payload=payload)
        paper_artifacts_may_exist = False

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
            if not markdown_text:
                raise MinerUResultInvalidError(context={"stage": "full_parse", "reason": "markdown_missing"})
            markdown_docs = self.chunker.split_md_document(markdown_text)
            metadata_docs = build_metadata_documents(paper_id=paper_id, paper_name=paper_name, textblocks=text_blocks)
            section_docs = self.chunker.build_section_documents(paper_id=paper_id, paper_name=paper_name, metadata_docs=metadata_docs, md_docs=markdown_docs)

            chunk_docs = self.chunker.split_section_document(section_docs=section_docs)
            paper_chunks = self.chunker.build_paper_chunks(paper_id=paper_id, chunk_docs=chunk_docs)
            if not paper_chunks:
                raise LangChainUnavailableError(context={"stage": "chunking", "reason": "paper_chunks_empty"})

            logger.info("论文切分完成 论文名%s 文本块数%s 切分块数%s", paper_name, len(text_blocks), len(paper_chunks))

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
            if paper_artifacts_may_exist:
                await self.file_store.remove_paper_artifacts(paper_id)
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
