from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PaperDocumentMetadata:
    paper_name: str
    authors: list[str]
    affiliations: list[str]
    journal: str | None
    publisher: str | None
    doi: str | None
    publication_year: int | None
    source: str | None
    abstract: str | None


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PaperChunk:
    chunk_id: str
    paper_id: str
    chunk_index: int
    text: str
    metadata: dict[str, Any]
