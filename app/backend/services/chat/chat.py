import json
import re

from app.backend.config import Settings
from app.backend.infrastructure.clients.llm_client import LLMClient, LLMProtocolError
from app.backend.services.chat.retriver import Retriever, RerankedCandidate
from app.backend.services.chat.model import AnswerSource, ChatAnswerResult

import logging

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
你是论文问答助手。
请始终使用中文回答，英文专业术语首次出现时保留英文原词。
只能根据提供的论文证据回答，不得自行补充证据中没有的信息，数字、公式和单位必须保持原样。
首次检索时，将用户问题改写为适合英文论文检索的查询。

如果已有证据不足以回答问题，应先判断缺失的具体信息，然后根据缺失信息生成新的检索词。
新检索词应聚焦缺失信息，例如具体指标、实验名称、表格、方法名称、英文术语或数值。
新检索词应区分类型，例如“语义改写”、“补充指标”、“补充实验”、“补充方法”、“补充数值”等。

每个结论必须使用 [证据编号] 标注来源，只能引用工具返回的证据编号，不得自行编造证据编号。
每个引用必须使用独立格式，例如：[证据2][证据7]。

证据不足时回答：根据当前检索到的论文内容无法确定。
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_paper",
            "description": "根据用户问题检索相关论文段落",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用于检索论文内容的问题",
                        "minLength": 1,
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }
]

CITATION_PATTERN = re.compile(r"\[证据(\d+)\]")
INSUFFICIENT_ANSWER = "根据当前检索到的论文内容无法确定。"
MAX_RETRIEVALS = 3

class ChatService:
    def __init__(self, *, retriever: Retriever, llm_client: LLMClient, settings: Settings) -> None:
        self.retriever = retriever
        self.llm_client = llm_client
        self.temperature = settings.llm_temperature

    async def answer(self, *, query: str) -> ChatAnswerResult:
        message = [{"role": "system", "content": SYSTEM_PROMPT}]
        message.append({"role": "user", "content": f"问题：{query}"})

        retrieval_queries: set[str] = set()
        evidence_by_id: dict[int, RerankedCandidate] = {}
        evidence_id_by_chunk: dict[str, int] = {}

        for turn in range(MAX_RETRIEVALS + 1):
            can_retrieve = turn < MAX_RETRIEVALS
            answer = await self.llm_client.complete(
                messages=message,
                tools=TOOLS,
                tool_choice="required" if turn == 0 else "auto" if can_retrieve else "none",
                max_tokens=1024,
            )
            tool_calls = answer.tool_calls or []
            if not tool_calls:
                return self.build_result(
                    answer=answer.content or INSUFFICIENT_ANSWER,
                    evidence_by_id=evidence_by_id,
                )

            if not can_retrieve:
                raise LLMProtocolError("Agent 超过最大检索次数后仍在调用工具。")

            message.append(answer.model_dump(exclude_none=True))

            for tool_call in tool_calls:
                name = tool_call.function.name
                if name != "retrieve_paper":
                    raise LLMProtocolError(f"未知工具：{name}")

                try:
                    arguments = json.loads(tool_call.function.arguments)
                    raw_query = arguments["query"]
                except (json.JSONDecodeError, KeyError, TypeError) as error:
                    raise LLMProtocolError("LLM 返回的检索工具参数不合法。") from error

                if not isinstance(raw_query, str) or not raw_query.strip():
                    raise LLMProtocolError("LLM 返回的检索词为空。")

                retrieval_query = raw_query.strip()
                normalized_query = " ".join(retrieval_query.casefold().split())

                if normalized_query in retrieval_queries:
                    tool_content = (
                        "该检索词已经执行过。请根据当前缺失的信息，"
                        "改用不同且更具体的英文检索词。"
                    )
                else:
                    retrieval_queries.add(normalized_query)
                    candidates = await self.retriever.retrieve(query=retrieval_query)
                    tool_content = self.register_evidence(
                        candidates=candidates,
                        evidence_by_id=evidence_by_id,
                        evidence_id_by_chunk=evidence_id_by_chunk,
                    )
                message.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_content})

            logger.debug(message)
                
        raise LLMProtocolError("Agent 未生成最终回答。")

    @staticmethod
    def register_evidence(*, candidates: list[RerankedCandidate], evidence_by_id: dict[int, RerankedCandidate], evidence_id_by_chunk: dict[str, int]) -> str:
        blocks: list[str] = []

        for candidate in candidates:
            payload = candidate.candidate.payload
            chunk_id = str(payload["chunk_id"])

            if chunk_id in evidence_id_by_chunk:
                continue

            evidence_id = len(evidence_by_id) + 1
            evidence_by_id[evidence_id] = candidate
            evidence_id_by_chunk[chunk_id] = evidence_id

            blocks.append("\n".join([
                f"[证据{evidence_id}]",
                f"论文：{payload.get('paper_name')}",
                f"章节：{payload.get('section_title')}",
                f"页码：{payload.get('page_numbers') or '未知'}",
                f"内容：{payload.get('text')}",
            ]))

        return "\n\n".join(blocks) or ("本次检索没有发现新的论文证据，请改写检索词。")

    @staticmethod
    def build_result(*, answer: str, evidence_by_id: dict[int, RerankedCandidate]) -> ChatAnswerResult:
        answer = answer.strip()
        used_ids = list(dict.fromkeys(int(value) for value in CITATION_PATTERN.findall(answer)))
        invalid_ids = [evidence_id for evidence_id in used_ids if evidence_id not in evidence_by_id]

        if invalid_ids:
            raise LLMProtocolError(f"LLM 引用了不存在的证据：{invalid_ids}")

        if not used_ids and answer != INSUFFICIENT_ANSWER:
            raise LLMProtocolError("LLM 生成了回答但没有引用证据。")

        sources = []
        for evidence_id in used_ids:
            item = evidence_by_id[evidence_id]
            payload = item.candidate.payload
            sources.append(AnswerSource(
                citation_id=evidence_id,
                paper_name=str(payload.get("paper_name")),
                paper_id=str(payload.get("paper_id")),
                chunk_id=str(payload.get("chunk_id")),
                section_title=str(payload.get("section_title") or "未识别章节"),
                page_numbers=payload.get("page_numbers") or []
            ))

        return ChatAnswerResult(answer=answer, sources=sources)
    