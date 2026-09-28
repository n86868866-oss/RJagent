from dataclasses import dataclass
from pydantic import BaseModel, Field

class ChatQueryRequest(BaseModel):
    query: str = Field(min_length=1)

class Candidate(BaseModel):
    paper_id: str
    paper_name: str
    section_title: str
    chunk_id: str
    text: str
    page_numbers: list[int] = Field(default_factory=list)
    hybrid_score: float
    rerank_score: float

@dataclass(frozen=True, slots=True)
class AnswerSource:
    citation_id: int
    paper_id: str
    paper_name: str
    chunk_id: str
    section_title: str
    page_numbers: list[int]


@dataclass(frozen=True, slots=True)
class ChatAnswerResult:
    answer: str
    sources: list[AnswerSource]
