"""PaperService business-rule tests without external services."""

import asyncio
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.backend.core.exceptions import AppError
from app.backend.infrastructure.clients.embedding_client import SparseEmbedding
from app.backend.services.papers.models import PaperChunk
from app.backend.services.papers.paper_service import PaperService


def test_validate_pdf_upload_rejects_invalid_input_and_oversized_file():
    with pytest.raises(AppError) as extension_error:
        PaperService.validate_pdf_upload(
            filename="note.txt", content_type="text/plain", payload=b"text", max_upload_mb=1
        )
    assert extension_error.value.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    with pytest.raises(AppError) as size_error:
        PaperService.validate_pdf_upload(
            filename="paper.pdf",
            content_type="application/pdf",
            payload=b"%PDF-" + b"x" * (1024 * 1024),
            max_upload_mb=0,
        )
    assert size_error.value.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE


def test_delete_missing_paper_returns_404():
    async def run():
        service = PaperService.__new__(PaperService)
        service.metadata_store = SimpleNamespace(get_paper_by_id=AsyncMock(return_value=None))
        service.vector_store = SimpleNamespace(delete_vectors=AsyncMock())
        service.file_store = SimpleNamespace(remove_paper_artifacts=AsyncMock())

        with pytest.raises(AppError) as raised:
            await service.delete_paper("missing")

        assert raised.value.status_code == HTTPStatus.NOT_FOUND
        service.vector_store.delete_vectors.assert_not_awaited()

    asyncio.run(run())


def test_upload_uses_body_for_sparse_vector_and_cleans_uncertain_write(monkeypatch):
    from app.backend.services.papers import paper_service as module

    async def run():
        chunk = PaperChunk(
            "chunk-1",
            "paper-1",
            0,
            "original body",
            {"paper_name": "Paper", "section_title": "Experiments", "page_numbers": [1]},
        )
        service = PaperService.__new__(PaperService)
        service.settings = SimpleNamespace(max_upload_mb=20)
        service.metadata_store = SimpleNamespace(paper_name_exists=AsyncMock(return_value=False))
        service.mineru_client = SimpleNamespace(parse_pdf=AsyncMock(return_value=object()))
        service.file_store = SimpleNamespace(
            save_temporary_upload=AsyncMock(return_value="temporary.pdf"),
            discard_temporary_upload=AsyncMock(),
        )
        service.document_builder = SimpleNamespace(build=Mock(return_value=([], [])))
        service.chunker = SimpleNamespace(
            split_documents=Mock(return_value=[]),
            build_paper_chunks=Mock(return_value=[chunk]),
        )
        service.text_embedding_client = SimpleNamespace(
            embed_documents=AsyncMock(return_value=[[1.0, 0.0]])
        )
        service.bm25_encoder = SimpleNamespace(
            encode_documents=Mock(return_value=[SparseEmbedding([1], [1.0])])
        )
        service.vector_store = SimpleNamespace(
            upsert_vectors=AsyncMock(side_effect=TimeoutError("write uncertain")),
            delete_vectors=AsyncMock(),
        )
        monkeypatch.setattr(module, "require_paper_name", lambda value: "Paper")
        monkeypatch.setattr(module, "require_text_blocks", lambda value: [object()])
        monkeypatch.setattr(module, "require_normalized_text", lambda value: "body")
        monkeypatch.setattr(module, "require_content_list", lambda value: [])

        with pytest.raises(TimeoutError):
            await service.upload_pdf(
                filename="test.pdf",
                content_type="application/pdf",
                payload=b"%PDF-test",
            )

        service.bm25_encoder.encode_documents.assert_called_once_with(["original body"])
        dense_text = service.text_embedding_client.embed_documents.call_args.args[0][0]
        assert "Paper title:" in dense_text
        service.vector_store.delete_vectors.assert_awaited_once()
        service.file_store.discard_temporary_upload.assert_awaited_once_with("temporary.pdf")

    asyncio.run(run())