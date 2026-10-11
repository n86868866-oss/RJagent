"""ChatService business-rule tests without external services."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.backend.services.chat.chat import ChatService
from app.backend.services.chat.retriver import RetrievalCandidate, RerankedCandidate


def evidence(chunk_id: str = "chunk-1") -> RerankedCandidate:
    return RerankedCandidate(
        candidate=RetrievalCandidate(
            point_id="point-1",
            hybrid_score=0.8,
            payload={
                "paper_id": "paper-1",
                "paper_name": "Test Paper",
                "chunk_id": chunk_id,
                "section_title": "Results",
                "page_numbers": [3],
                "text": "Evidence text.",
            },
        ),
        rerank_score=0.9,
    )


def test_answer_retrieves_evidence_and_returns_cited_source():
    async def run():
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="retrieve_paper", arguments='{"query":"placement result"}'),
        )
        first_answer = SimpleNamespace(
            content=None,
            tool_calls=[tool_call],
            model_dump=Mock(return_value={"role": "assistant", "tool_calls": []}),
        )
        final_answer = SimpleNamespace(content="回答。[证据1]", tool_calls=[])
        llm = SimpleNamespace(complete=AsyncMock(side_effect=[first_answer, final_answer]))
        retriever = SimpleNamespace(retrieve=AsyncMock(return_value=[evidence()]))
        service = ChatService(
            retriever=retriever,
            llm_client=llm,
            settings=SimpleNamespace(llm_temperature=0.1),
        )

        result = await service.answer(query="论文结论是什么？")

        assert result.answer == "回答。[证据1]"
        assert result.sources[0].chunk_id == "chunk-1"
        retriever.retrieve.assert_awaited_once_with(query="placement result")
        assert llm.complete.await_count == 2

    asyncio.run(run())


def test_build_result_rejects_unknown_citation():
    with pytest.raises(ValueError, match="不存在的证据"):
        ChatService.build_result(answer="回答。[证据2]", evidence_by_id={1: evidence()})


def test_build_result_allows_standard_insufficient_answer_without_citation():
    result = ChatService.build_result(
        answer="根据当前检索到的论文内容无法确定。",
        evidence_by_id={},
    )
    assert result.sources == []