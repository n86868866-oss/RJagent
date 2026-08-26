from fastapi import APIRouter, Depends

from app.backend.services.chat.retriver import Retriever
from app.backend.api.dependencies import get_retriever_service
from app.backend.core.responses import ApiResponse, ok
from app.backend.api.schemas.chat import Candidate, ChatQueryRequest

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/query", response_model=ApiResponse[list[Candidate]])
async def query_chat(request: ChatQueryRequest, servicer: Retriever = Depends(get_retriever_service)):
    results = await servicer.retrieve(query=request.query)
    data = [
        Candidate(
        paper_id=result.candidate.payload.get("paper_id"),
        paper_name=result.candidate.payload.get("paper_name"),
        section_title=result.candidate.payload.get("section_title"),
        parent_title=result.candidate.payload.get("parent_title"),
        chunk_id=result.candidate.payload.get("chunk_id"),
        text=result.candidate.payload.get("text"),
        page_start=result.candidate.payload.get("page_start"),
        page_end=result.candidate.payload.get("page_end"),
        dense_score=result.candidate.dense_score,
        rerank_score=result.rerank_score,
    ) for result in results
    ]
    return ok(data=data, message="检索重排成功")
