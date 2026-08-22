import re

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter, TextSplitter

from app.backend.services.papers.models import PaperChunk


class SectionMetadataMatchError(ValueError):
    def __init__(self, *, section_title: str | None, reason: str) -> None:
        self.section_title = section_title
        self.reason = reason
        super().__init__(f"{reason}: {section_title or ''}")


class Chunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.text_splitter: TextSplitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", ".", ";", ",", " ", ""],
            keep_separator="end",
            length_function=len,
        )
        self.md_splitter: MarkdownHeaderTextSplitter = MarkdownHeaderTextSplitter(  
            headers_to_split_on=[
                ("#", "h1"),
                ("##", "h2"),
                ("###", "h3"),
            ],
            strip_headers=True,
        )

    def split_section_document(self, section_docs: list[Document]) -> list[Document]:
        return self.text_splitter.split_documents(section_docs)

    def split_md_document(self, markdown_text: str) -> list[Document]:
        return self.md_splitter.split_text(markdown_text)

    def build_section_documents(self, paper_id: str, paper_name: str, metadata_docs: list[Document], md_docs: list[Document]) -> list[Document]:
        final_section_docs: list[Document] = []
        self.attach_parent_section_titles(metadata_docs)
        metadata_by_title = self.build_metadata_by_title(metadata_docs)

        for index, md_doc in enumerate(md_docs):
            markdown_title = self.markdown_doc_title(md_doc)
            matched_metadata_doc = self.match_metadata_doc(metadata_by_title, markdown_title)

            metadata = {
                "paper_id": paper_id,
                "paper_name": paper_name,
                "section_index": index,
                "section_title": markdown_title or "未识别章节",
                "parent_title": matched_metadata_doc.metadata.get("parent_title"),
                "section_level": matched_metadata_doc.metadata.get("section_level"),
                "page_start": matched_metadata_doc.metadata.get("page_start"),
                "page_end": matched_metadata_doc.metadata.get("page_end"),
            }

            final_section_docs.append(
                Document(
                    page_content=md_doc.page_content,
                    metadata=metadata,
                )
            )
        return final_section_docs

    @staticmethod
    def markdown_doc_title(doc: Document) -> str | None:
        for key in ("h3", "h2", "h1"):
            value = doc.metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    @classmethod
    def build_metadata_by_title(cls, metadata_docs: list[Document]) -> dict[str, Document]:
        metadata_by_title: dict[str, Document] = {}
        for doc in metadata_docs:
            title = doc.metadata.get("section_title")
            normalized = cls.normalize_title(title)
            if not normalized:
                continue
            if normalized in metadata_by_title:
                raise SectionMetadataMatchError(section_title=str(title), reason="duplicate_metadata_title")
            metadata_by_title[normalized] = doc
        return metadata_by_title

    @classmethod
    def match_metadata_doc(cls, metadata_by_title: dict[str, Document], markdown_title: str | None) -> Document:
        normalized = cls.normalize_title(markdown_title)
        if not normalized:
            raise SectionMetadataMatchError(section_title=markdown_title, reason="empty_markdown_title")

        metadata_doc = metadata_by_title.get(normalized)
        if metadata_doc is None:
            raise SectionMetadataMatchError(section_title=markdown_title, reason="metadata_title_not_found")
        return metadata_doc

    @classmethod
    def attach_parent_section_titles(cls, metadata_docs: list[Document]) -> None:
        current_titles: dict[int, str] = {}

        for index, doc in enumerate(metadata_docs):
            title = doc.metadata.get("section_title")
            level = cls.infer_heading_level(title, current_titles, is_first=index == 0)
            doc.metadata["parent_title"] = current_titles.get(level - 1)
            doc.metadata["section_level"] = level

            current_titles[level] = str(title).strip() if title is not None else ""
            for stale_level in list(current_titles):
                if stale_level > level:
                    del current_titles[stale_level]

    @classmethod
    def infer_heading_level(cls, title: object, current_titles: dict[int, str], *, is_first: bool) -> int:
        if is_first:
            return 1
        if not isinstance(title, str) or not title.strip():
            return 2

        value = title.strip()
        if cls.is_common_top_level_title(value):
            return 2

        alpha_numeric = re.match(r"^([A-Z])\.(\d+(?:\.\d+)*)(?:[.)])?\s+", value)
        if alpha_numeric is not None:
            return 3

        numeric = re.match(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+", value)
        if numeric is not None:
            numeric_level = len(numeric.group(1).split("."))
            if numeric_level == 1 and cls.current_level2_is_alpha_appendix(current_titles):
                return 3
            if numeric_level == 1 and cls.current_level2_is_letter_subheading(current_titles):
                return 3
            return min(numeric_level + 1, 3)

        roman = re.match(r"^([IVXLCDM]+)\.?\s+", value)
        if roman is not None and cls.is_roman_numeral(roman.group(1)):
            return 2

        letter_dot = re.match(r"^([A-Z])\.\s+", value)
        if letter_dot is not None:
            return 3 if cls.current_level2_is_roman(current_titles) else 2

        letter_space = re.match(r"^([A-Z])\s+", value)
        if letter_space is not None:
            return 3 if cls.current_level2_is_roman(current_titles) else 2

        return 2

    @staticmethod
    def is_common_top_level_title(title: str) -> bool:
        normalized = title.strip().strip(":").lower()
        return normalized in {"abstract", "keywords", "references", "acknowledgments", "acknowledgements", "checklist", "appendix"}

    @classmethod
    def current_level2_is_alpha_appendix(cls, current_titles: dict[int, str]) -> bool:
        title = current_titles.get(2, "")
        return bool(re.match(r"^[A-Z](?:\s|\.)(?!\d)", title)) and not cls.current_level2_is_roman(current_titles)

    @classmethod
    def current_level2_is_roman(cls, current_titles: dict[int, str]) -> bool:
        title = current_titles.get(2, "")
        match = re.match(r"^([IVXLCDM]+)\.?\s+", title)
        return match is not None and cls.is_roman_numeral(match.group(1))

    @staticmethod
    def current_level2_is_letter_subheading(current_titles: dict[int, str]) -> bool:
        title = current_titles.get(2, "")
        return bool(re.match(r"^[A-Z]\.\s+", title))

    @staticmethod
    def is_roman_numeral(value: str) -> bool:
        return value in {
            "I",
            "II",
            "III",
            "IV",
            "V",
            "VI",
            "VII",
            "VIII",
            "IX",
            "X",
            "XI",
            "XII",
            "XIII",
            "XIV",
            "XV",
            "XVI",
            "XVII",
            "XVIII",
            "XIX",
            "XX",
        }

    @staticmethod
    def normalize_title(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            return ""
        value = value.strip().lstrip("#").strip().lower()
        return re.sub(r"\s+", " ", value)

    def build_paper_chunks(self, paper_id: str, chunk_docs: list[Document]) -> list[PaperChunk]:
        paper_chunks: list[PaperChunk] = []
        for index, chunk in enumerate(chunk_docs):
            paper_chunks.append(
                PaperChunk(
                    chunk_id=f"{paper_id}_{index}",
                    paper_id=paper_id,
                    chunk_index=index,
                    text=chunk.page_content,
                    metadata={
                        **chunk.metadata,
                        "chunk_index": index,
                    },
                )
            )
        return paper_chunks
    
