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
class PaperParseResult:
    paper_id: str
    paper_name: str
    page_count: int | None


@dataclass(frozen=True, slots=True)
class PaperRecordResult:
    paper_id: str
    paper_name: str
    paper_name_key: str
    filename: str
    file_size_bytes: int
    status: str
    parsed_file_paths: dict[str, str]
    created_at: str
    updated_at: str
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


