from dataclasses import dataclass
from collections.abc import Sequence

import httpx

from app.backend.config import Settings


@dataclass(frozen=True, slots=True)
class RerankScore:
    index: int
    score: float


class RerankerClient:
    def __init__(self, *, settings: Settings) -> None:
        self.base_url = settings.reranker_base_url
        self.timeout_seconds = settings.reranker_timeout_seconds
        self.max_retries = settings.reranker_max_retries
        self.top_k = settings.retriever_final_top_k
        self.http_client = httpx.AsyncClient(
            base_url=self.base_url.rstrip("/") + "/",
            timeout=self.timeout_seconds,
            trust_env=False,
        )

    async def rerank(self, *, query: str, texts: Sequence[str]) -> list[RerankScore]:
        if not texts:
            return []
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.http_client.post(
                    "rerank",
                    json={
                        "query": query,
                        "texts": list(texts),
                        "truncate": True,
                        "raw_scores": False,
                        "return_text": False,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                if attempt < self.max_retries:
                    continue
                raise
            break

        try:
            results = [RerankScore(index=int(item["index"]), score=float(item["score"])) for item in response.json()]
            if any(item.index < 0 or item.index >= len(texts) for item in results):
                raise ValueError("重排结果的索引超出输入文本范围。")
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError("重排服务返回的分数格式不正确。") from error
        return sorted(results, key=lambda item: item.score, reverse=True)[:self.top_k]

    async def probe(self) -> None:
        results = await self.rerank(
            query="健康检查",
            texts=["健康检查文本", "完全无关的内容"],
        )
        if not results:
            raise ValueError("重排服务未返回结果。")

    async def close(self) -> None:
        await self.http_client.aclose()
