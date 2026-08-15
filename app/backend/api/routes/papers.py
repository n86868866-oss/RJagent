from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.backend.api.dependencies import get_paper_service
from app.backend.api.schemas.papers import PaperDocumentMetadataData, PaperParsedFilesData, PaperUploadData
from app.backend.core.responses import ApiResponse, created
from app.backend.services.papers.paper_service import PaperService

router = APIRouter(prefix="/papers", tags=["papers"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApiResponse[PaperUploadData])
async def upload_paper(request: Request, file: Annotated[UploadFile, File()], service: PaperService = Depends(get_paper_service)) -> ApiResponse[PaperUploadData]:
    payload = await file.read()
    result = await service.upload_and_parse_pdf(filename=file.filename or "upload.pdf", content_type=file.content_type, payload=payload)
    data = PaperUploadData(
        paper_id=result.paper_id,
        paper_name=result.paper_name,
        filename=result.filename,
        file_size_bytes=result.file_size_bytes,
        text_block_count=result.text_block_count,
        page_count=result.page_count,
        status=result.status,
        parsed_files=PaperParsedFilesData(**result.parsed_files),
        metadata=PaperDocumentMetadataData(
            paper_name=result.metadata.paper_name,
            authors=result.metadata.authors,
            affiliations=result.metadata.affiliations,
            journal=result.metadata.journal,
            publisher=result.metadata.publisher,
            doi=result.metadata.doi,
            publication_year=result.metadata.publication_year,
            source=result.metadata.source,
            abstract=result.metadata.abstract,
        ),
    )
    return created(data=data, request=request, message="论文解析成功")
