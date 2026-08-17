from __future__ import annotations

from pydantic import BaseModel, Field


class PaperParsedFilesData(BaseModel):
    markdown: str | None = None
    content_list: str | None = None
    middle: str | None = None
    normalized_text: str
    layout_pdf: str | None = None
    span_pdf: str | None = None


class PaperDocumentMetadataData(BaseModel):
    paper_name: str
    authors: list[str] = Field(default_factory=list)
    affiliations: list[str] = Field(default_factory=list)
    journal: str | None = None
    publisher: str | None = None
    doi: str | None = None
    publication_year: int | None = Field(default=None, ge=0)
    source: str | None = None
    abstract: str | None = None


class PaperUploadData(BaseModel):
    paper_id: str
    paper_name: str
    filename: str
    file_size_bytes: int = Field(ge=0)
    text_block_count: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=0)
    status: str
    parsed_files: PaperParsedFilesData
    metadata: PaperDocumentMetadataData


class PaperDeleteData(BaseModel):
    paper_id: str
    paper_name: str
    filename: str
    file_size_bytes: int = Field(ge=0)
    status: str