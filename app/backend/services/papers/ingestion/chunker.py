from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter, TextSplitter

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
        for index, md_doc in enumerate(md_docs):
            metadata = {
                "paper_id": paper_id,
                "paper_name": paper_name,
                "markdown_section_index": index,
                "markdown_h1": md_doc.metadata.get("h1"),
                "markdown_h2": md_doc.metadata.get("h2"),
                "markdown_h3": md_doc.metadata.get("h3"),
            }

            if index < len(metadata_docs):
                metadata.update(metadata_docs[index].metadata)

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
    
