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

        text_chunks = self.text_splitter.split_documents(text_docs)
        for chunk in text_chunks:
            self.attach_page_numbers(chunk)
        chunks.extend(text_chunks)

        for document in structured_documents:
            content_type = document.metadata.get("content_type")
            if content_type == "table":
                chunks.extend(self.split_table(document, self.chunk_size))
            elif content_type in {"image", "chart", "footnote"}:
                if document.page_content.strip():
                    chunks.append(document)
            else:
                raise ValueError(f"文档内容类型不受支持：{content_type}")

        content_type_order = {"text": 0, "table": 1, "image": 2, "chart": 2, "footnote": 3}
        return sorted(chunks, key=lambda document: (
            self.sortable_int(document.metadata.get("section_index")),
            self.sortable_int(document.metadata.get("start_index")),
            content_type_order.get(str(document.metadata.get("content_type")), 99),
        ))

    @staticmethod
    def attach_page_numbers(document: Document) -> None:
        segments = document.metadata.pop("_page_segments", [])
        start = document.metadata.get("start_index")
        chunk_start = start if isinstance(start, int) and not isinstance(start, bool) else 0
        chunk_end = chunk_start + len(document.page_content)
        matching_segments = [segment for segment in segments if isinstance(segment, dict) and isinstance(segment.get("start"), int) and isinstance(segment.get("end"), int) and max(chunk_start, segment["start"]) < min(chunk_end, segment["end"])]
        page_numbers = sorted({segment["page_number"] for segment in matching_segments if isinstance(segment.get("page_number"), int) and not isinstance(segment.get("page_number"), bool)})

        if not page_numbers:
            page_numbers = [page for page in document.metadata.get("page_numbers", []) if isinstance(page, int) and not isinstance(page, bool)]

        document.metadata["page_numbers"] = page_numbers

    def split_table(self, document: Document, max_chars: int) -> list[Document]:
        lines = document.page_content.splitlines()
        metadata = dict(document.metadata)
        footnote = str(metadata.pop("_table_footnote", "") or "").strip()
        if len(lines) <= 2:
            content = document.page_content.strip()
            if footnote:
                content = "\n\n".join(value for value in (content, footnote) if value)
            return [Document(page_content=content, metadata=metadata)] if content else []

        header, rows = lines[:2], lines[2:]
        chunks: list[Document] = []
        current_rows: list[str] = []

        for row in rows:
            candidate = "\n".join([*header, *current_rows, row])
            if current_rows and len(candidate) > max_chars:
                chunks.append(Document(
                    page_content="\n".join([*header, *current_rows]),
                    metadata=dict(metadata),
                ))
                current_rows = [row]
            else:
                current_rows.append(row)

        if current_rows:
            chunks.append(Document(
                page_content="\n".join([*header, *current_rows]),
                metadata=dict(metadata),
            ))
        if chunks and footnote:
            chunks[-1].page_content = f"{chunks[-1].page_content}\n\n{footnote}"
        return chunks

    @staticmethod
    def sortable_int(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 2**31 - 1

    def build_paper_chunks(self, paper_id: str, chunk_docs: list[Document]) -> list[PaperChunk]:
        paper_chunks: list[PaperChunk] = []
        for index, chunk in enumerate(chunk_docs):
            metadata = dict(chunk.metadata)
            metadata.pop("_page_segments", None)
            paper_chunks.append(
                PaperChunk(
                    chunk_id=f"{paper_id}_{index}",
                    paper_id=paper_id,
                    chunk_index=index,
                    text=chunk.page_content,
                    metadata={
                        **metadata,
                        "chunk_index": index,
                    },
                )
            )
        if not paper_chunks:
            raise ValueError("文档切分后没有可用的论文片段。")
        return paper_chunks
    
