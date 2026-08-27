from pydantic import BaseModel, Field


class ChatQueryRequest(BaseModel):
    query: str = Field(min_length=1)

class Candidate(BaseModel):
    paper_id: str
    paper_name: str
    parent_title: str | None
    section_title: str
    chunk_id: str
    text: str
    page_start: int | None
    page_end: int | None
    dense_score: float
    rerank_score: float

class ChatQueryResponse(BaseModel):
    candidates: list[Candidate]

class AnswerCandidate(BaseModel):
    citation_id: int
    paper_id: str
    paper_name: str
    section_title: str
    chunk_id: str
    page_start: int | None
    page_end: int | None

class ChatAnswerResponse(BaseModel):
    answer: str
    sources: list[AnswerCandidate]
