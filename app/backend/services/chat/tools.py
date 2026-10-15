import json
import re
from abc import ABC, abstractmethod
from typing import Any

from app.backend.services.chat.retriver import Retriever, RerankedCandidate


def parse_action(content: str) -> dict[str, Any]:
    match = re.fullmatch(r"\s*Thought:\s*.+?\s*Action:\s*([A-Za-z_][A-Za-z_0-9]*)\[(.*)\]\s*", content, re.DOTALL)
    if match is None:
        raise ValueError("LLM 动作格式错误，应输出 Thought 和 Action。")
    name, value = match.group(1), match.group(2).strip()
    if re.search(r"(?m)^\s*Action\s*:", value):
        raise ValueError("LLM 一次只能选择一个 Action。")
    if name == "Finish":
        return {"action": "finish", "content": value}
    return {"action": "tool", "name": name, "arguments": json.loads(value)}


class Tool(ABC):
    """An action that the agent can request."""

    name: str
    description: str

    @abstractmethod
    async def run(self, parameters: dict[str, Any]) -> str:
        raise NotImplementedError


class ToolRegistry:
    """Discover and execute only the tools registered for this answer."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get_tools_description(self) -> str:
        return "\n".join(f"- {tool.name}: {tool.description}" for tool in self._tools.values())

    async def execute_tool(self, name: str, parameters: dict[str, Any]) -> str:
        return await self._tools[name].run(parameters)


class RetrievePaperTool(Tool):
    def __init__(self, *, retriever: Retriever) -> None:
        self.name = "retrieve_paper"
        self.description = "检索已上传论文的正文和图表。query 是必填字符串，应聚焦论文名和需要核对的事实，内容应具体详实，且以英文形式提供。"
        self.retriever = retriever
        self.queries: set[str] = set()
        self.evidence_by_id: dict[int, RerankedCandidate] = {}
        self.seen_chunk_ids: set[str] = set()

    async def run(self, parameters: dict[str, Any]) -> str:
        query = parameters["query"].strip()
        if not query:
            return "检索词为空，请提供具体的检索词。"
        normalized = " ".join(query.casefold().split())
        if normalized in self.queries:
            return "该检索词已经执行过。请换一个不同且更具体的英文检索词。"

        self.queries.add(normalized)
        candidates = await self.retriever.retrieve(query=query)
        evidence = self._register_evidence(candidates)
        return f"{evidence}"

    def _register_evidence(self, candidates: list[RerankedCandidate]) -> str:
        blocks: list[str] = []
        for candidate in candidates:
            payload = candidate.candidate.payload
            chunk_id = str(payload["chunk_id"])
            if chunk_id in self.seen_chunk_ids:
                continue

            evidence_id = len(self.evidence_by_id) + 1
            self.evidence_by_id[evidence_id] = candidate
            self.seen_chunk_ids.add(chunk_id)
            blocks.append("\n".join([
                f"[证据{evidence_id}]",
                f"论文：{payload.get('paper_name')}",
                f"章节：{payload.get('section_title')}",
                f"页码：{payload.get('page_numbers') or '未知'}",
                f"内容：{payload.get('text')}",
            ]))

        if not blocks:
            return (
                "本次检索没有发现新的论文证据。"
                "如仍有检索次数和未尝试的角度，可换一个更具体或更短的英文检索词。"
            )
        return "\n\n".join(blocks)
