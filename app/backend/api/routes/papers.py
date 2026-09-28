from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status
from app.backend.api.dependencies import get_paper_service
from app.backend.core.responses import ApiResponse, created
from app.backend.services.papers.models import PaperParseResult
from app.backend.services.papers.paper_service import PaperService

router = APIRouter(prefix="/papers", tags=["papers"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApiResponse[PaperParseResult])
async def upload_paper(request: Request, file: Annotated[UploadFile, File()], service: PaperService = Depends(get_paper_service)) -> ApiResponse[PaperParseResult]:
    payload = await file.read()
    result = await service.upload_pdf(filename=file.filename or "upload.pdf", content_type=file.content_type, payload=payload)
    data = PaperParseResult(
        paper_id=result.paper_id,
        paper_name=result.paper_name,
        page_count=result.page_count,
    )
    return created(data=data, request=request, message="论文解析成功")


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper(paper_id: str, service: PaperService = Depends(get_paper_service)) -> Response:
    await service.delete_paper(paper_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
