from __future__ import annotations

import asyncio
import math

from app.backend.clients.text_embedding_client import (
    TextEmbeddingClient,
)
from app.backend.config import get_settings


def cosine_similarity(
    left: list[float],
    right: list[float],
) -> float:
    dot_product = sum(
        left_value * right_value
        for left_value, right_value in zip(left, right)
    )
    left_norm = math.sqrt(
        sum(value * value for value in left)
    )
    right_norm = math.sqrt(
        sum(value * value for value in right)
    )
    return dot_product / (left_norm * right_norm)


async def main() -> None:
    settings = get_settings()
    client = TextEmbeddingClient(settings)

    query = "How does RAG reduce unsupported answers?"
    documents = [
        (
            "RAG retrieves evidence before generation and can "
            "attach source citations to the answer."
        ),
        (
            "Convolutional neural networks are used for image "
            "classification."
        ),
        (
            "SQLite stores relational data in a local file."
        ),
    ]

    try:
        query_vector = await client.embed_query(query)
        document_vectors = await client.embed_documents(documents)
    finally:
        await client.close()

    results = [
        (
            cosine_similarity(query_vector, vector),
            document,
        )
        for document, vector in zip(
            documents,
            document_vectors,
        )
    ]
    results.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    print("Provider:", settings.text_embedding_provider)
    print("Model:", settings.text_embedding_model)
    print("Dimension:", len(query_vector))
    print("Document count:", len(document_vectors))
    print()

    for rank, (score, document) in enumerate(results, start=1):
        print(f"{rank}. score={score:.6f}")
        print(f"   {document}")


if __name__ == "__main__":
    asyncio.run(main())
