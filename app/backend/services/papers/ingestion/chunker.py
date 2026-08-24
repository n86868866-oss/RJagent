from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter, TextSplitter

from app.backend.services.papers.models import PaperChunk


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
            add_start_index=True,
        )
    def split_documents(self, text_docs: list[Document], structured_documents: list[Document]) -> list[Document]:
        chunks: list[Document] = []

        chunks.extend(self.text_splitter.split_documents(text_docs))

        for document in structured_documents:
            content_type = document.metadata.get("content_type")
            if content_type == "table":
                chunks.extend(self.split_table(document, self.chunk_size))
            elif content_type in {"image", "chart"}:
                if document.page_content.strip():
                    chunks.append(document)
            else:
                raise ValueError(f"unsupported_content_type:{content_type}")

        content_type_order = {"text": 0, "table": 1, "image": 2, "chart": 2}
        return sorted(chunks, key=lambda document: (
            self.sortable_int(document.metadata.get("section_index")),
            content_type_order.get(str(document.metadata.get("content_type")), 99),
            self.sortable_int(document.metadata.get("source_order")),
            self.sortable_int(document.metadata.get("start_index")),
        ))

    def split_table(self, document: Document, max_chars: int) -> list[Document]:
        lines = document.page_content.splitlines()
        if len(lines) <= 2:
            return [document] if document.page_content.strip() else []

        header, rows = lines[:2], lines[2:]
        chunks: list[Document] = []
        current_rows: list[str] = []

        for row in rows:
            candidate = "\n".join([*header, *current_rows, row])
            if current_rows and len(candidate) > max_chars:
                chunks.append(Document(
                    page_content="\n".join([*header, *current_rows]),
                    metadata=dict(document.metadata),
                ))
                current_rows = [row]
            else:
                current_rows.append(row)

        if current_rows:
            chunks.append(Document(
                page_content="\n".join([*header, *current_rows]),
                metadata=dict(document.metadata),
            ))
        return chunks

    @staticmethod
    def sortable_int(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 2**31 - 1

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
    
