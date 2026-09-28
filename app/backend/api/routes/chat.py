from fastapi import APIRouter, Depends

from app.backend.services.chat.retriver import Retriever
from app.backend.services.chat.chat import ChatService
from app.backend.api.dependencies import get_retriever_service, get_chat_service
from app.backend.core.responses import ApiResponse, ok
from app.backend.services.chat.model import ChatAnswerResult, AnswerSource, Candidate, ChatQueryRequest

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/query", response_model=ApiResponse[list[Candidate]])
async def query(request: ChatQueryRequest, servicer: Retriever = Depends(get_retriever_service)):
    results = await servicer.retrieve(query=request.query)
    data = [
        Candidate(
        paper_id=result.candidate.payload.get("paper_id"),
        paper_name=result.candidate.payload.get("paper_name"),
        section_title=result.candidate.payload.get("section_title"),
        chunk_id=result.candidate.payload.get("chunk_id"),
        text=result.candidate.payload.get("text"),
        page_numbers=result.candidate.payload.get("page_numbers") or [],
        hybrid_score=result.candidate.hybrid_score,
        rerank_score=result.rerank_score,
    ) for result in results
    ]
    return ok(data=data, message="检索重排成功")

@router.post("/chat_query", response_model=ApiResponse[ChatAnswerResult])
async def chat_query(request: ChatQueryRequest, servicer: ChatService = Depends(get_chat_service)):
    results = await servicer.answer(query=request.query)
    data = ChatAnswerResult(
        answer=results.answer,
        sources=[
            AnswerSource(
                citation_id=source.citation_id,
                paper_id=source.paper_id,
                paper_name=source.paper_name,
                section_title=source.section_title,
                chunk_id=source.chunk_id,
                page_numbers=source.page_numbers
            ) for source in results.sources
        ]
    )
    return ok(data=data, message="回答生成成功")
