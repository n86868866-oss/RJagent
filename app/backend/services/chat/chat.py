import json
import re

from app.backend.config import Settings
from app.backend.infrastructure.clients.llm_client import LLMClient
from app.backend.services.chat.retriver import Retriever, RerankedCandidate
from app.backend.services.chat.model import AnswerSource, ChatAnswerResult
from app.backend.services.chat.tools import RetrievePaperTool, ToolRegistry, parse_action

import logging
logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
你是一个具备推理和行动能力的论文问答助手。你可以通过思考分析问题，然后调用合适的工具来获取信息，最终给出准确的答案。

## 可用工具
{tools}

## 工作流程
请严格使用以下格式回应，每次只能执行一个步骤，即只有一组输出：

Thought: 分析当前问题，思考需要什么信息或采取什么行动。
Action: 选择一个行动，格式必须是以下之一:
- `{tool_name}[{tool_input}]` - 调用指定工具
- `Finish[最终答案]` - 当你有足够信息给出最终答案时

## 重要提醒
1. 每次回应必须包含Thought和Action两部分。
2. 工具调用的格式必须严格遵循:工具名[参数]，例如：retrieve_paper[{"query":"..."}]。
3. 只有当你确信有足够信息能够正确回答问题时，才使用Finish
4. 如果工具返回的信息不够，继续使用其他工具或相同工具的不同参数，例如：收到 Observation 后，先检查它是否直接支持所问结论。若不足且仍有合理的新检索方向，换一个针对缺失信息的英文检索词继续检索。第一次结果不匹配，不等于论文没有答案。
5. 请用中文回答
6. 具体事实回答中的每个结论必须引用 Observation 中出现的证据编号，例如：[证据2][证据7]，而且不得自行编造事实或编造不存在的证据编号。

现在开始你的推理和行动:
"""

CITATION_PATTERN = re.compile(r"\[证据(\d+)\]")
INSUFFICIENT_ANSWER = "根据当前检索到的论文内容无法确定。"
INVALID_CITATION_ANSWER = "回答中的证据引用无效，无法确认结论。"
AGENT_FAILED_ANSWER = "Agent 达到最大动作步数，未能完成有效的检索与回答，请重试。"
MAX_AGENT_STEPS = 5


class ChatService:
    def __init__(self, *, retriever: Retriever, llm_client: LLMClient, settings: Settings) -> None:
        self.retriever = retriever
        self.llm_client = llm_client
        self.temperature = settings.llm_temperature

    async def answer(self, *, query: str) -> ChatAnswerResult:
        registry = ToolRegistry()
        paper_tool = RetrievePaperTool(retriever=self.retriever)
        registry.register_tool(paper_tool)
        messages = [{"role": "system", "content": SYSTEM_PROMPT.replace("{tools}", registry.get_tools_description())}]
        messages.append({"role": "user", "content": f"问题：{query}"})

        for step in range(MAX_AGENT_STEPS):
            reply, _ = await self.llm_client.complete(messages=list(messages), max_tokens=1024, temperature=self.temperature)
            raw_action = reply.content or ""
            try:
                action = parse_action(raw_action)
            except ValueError:
                logger.warning("Agent 第 %s 步动作格式错误，原始输出：%r", step + 1, raw_action)
                messages.append({"role": "user", "content": "刚才的输出格式无效，未被执行，也不是检索证据。请只输出一组 Thought: ... 和 Action: retrieve_paper[{\"query\":\"英文检索词\"}] 或 Action: Finish[最终答案]。"})
                continue
            if action["action"] == "finish":
                citation_error = self.citation_error(answer=action["content"], evidence_by_id=paper_tool.evidence_by_id)
                if citation_error:
                    logger.warning("Agent 第 %s 步 Finish 未被采纳，原因:%s 已检索次数:%s 可用证据编号:%s 原始答案:%r", step + 1, citation_error, len(paper_tool.queries), sorted(paper_tool.evidence_by_id), action["content"])
                    messages.append({"role": "user", "content": "刚才的 Finish 未被采纳：答案缺少真实证据编号，或引用了不存在的编号。请依据实际 Observation 修正；若证据不足，请换英文检索词继续调用 retrieve_paper。"})
                    continue
                if action["content"].strip() == INSUFFICIENT_ANSWER:
                    logger.info("Agent 第 %s 步主动拒答，已检索次数:%s", step + 1, len(paper_tool.queries))
                return self.build_result(answer=action["content"], evidence_by_id=paper_tool.evidence_by_id)

            messages.append({"role": "assistant", "content": raw_action})
            logger.info("Agent 第 %s 步工具调用：%s[%s]", step + 1, action["name"],json.dumps(action["arguments"], ensure_ascii=False, separators=(",", ":")))
            tool_content = await registry.execute_tool(action["name"], action["arguments"])
            messages.append({"role": "user", "content": f"Observation（{action['name']} 的结果）：\n{tool_content}"})

        logger.warning("Agent 达到最大动作步数，未完成有效回答；已检索次数:%s", len(paper_tool.queries))
        return ChatAnswerResult(answer=AGENT_FAILED_ANSWER, sources=[])

    @staticmethod
    def citation_error(*, answer: str, evidence_by_id: dict[int, RerankedCandidate]) -> str | None:
        answer = answer.strip()
        if answer == INSUFFICIENT_ANSWER:
            return None
        used_ids = {int(value) for value in CITATION_PATTERN.findall(answer)}
        unknown_ids = sorted(used_ids - evidence_by_id.keys())
        if unknown_ids:
            return f"引用了不存在的证据编号 {unknown_ids}"
        # if not used_ids:
        #     return "答案缺少证据编号，且不是固定格式的拒答"
        return None

    @staticmethod
    def build_result(*, answer: str, evidence_by_id: dict[int, RerankedCandidate]) -> ChatAnswerResult:
        answer = answer.strip()
        used_ids = list(dict.fromkeys(int(value) for value in CITATION_PATTERN.findall(answer)))
        if ChatService.citation_error(answer=answer, evidence_by_id=evidence_by_id):
            return ChatAnswerResult(answer=INVALID_CITATION_ANSWER, sources=[])

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
