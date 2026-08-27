from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class AnswerSource:
    citation_id: int
    paper_id: str
    paper_name: str
    chunk_id: str
    section_title: str
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True, slots=True)
class ChatAnswerResult:
    answer: str
    sources: list[AnswerSource]