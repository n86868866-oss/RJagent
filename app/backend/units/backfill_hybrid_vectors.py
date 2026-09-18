"""Explicit offline migration; never loads Settings or dotenv.

Pause uploads/deletes during migration. Keep the source collection unchanged.
The target must be new, or an empty compatible collection created by the app.
"""
import argparse
import asyncio
import sys
from getpass import getpass
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from qdrant_client import AsyncQdrantClient, models

from app.backend.infrastructure.clients.embedding_client import BM25Encoder


async def backfill(client, encoder, source: str, target: str, batch_size: int = 64):
    if source == target or batch_size < 1:
        raise ValueError("Use different collection names and a positive batch size.")
    source_info = await client.get_collection(source)
    dense_params = source_info.config.params.vectors
    if isinstance(dense_params, dict):
        raise ValueError("This migration expects the original unnamed Dense collection.")
    source_count = (await client.count(source, exact=True)).count
    if source_count == 0:
        raise ValueError("Source collection is empty.")

    if await client.collection_exists(target):
        info = await client.get_collection(target)
        vectors = info.config.params.vectors
        sparse = info.config.params.sparse_vectors or {}
        if not (
            isinstance(vectors, dict) and "dense" in vectors
            and vectors["dense"].size == dense_params.size
            and vectors["dense"].distance == dense_params.distance
            and "sparse" in sparse and sparse["sparse"].modifier == models.Modifier.IDF
        ):
            raise ValueError("Target schema is incompatible; use a new collection.")
        if (await client.count(target, exact=True)).count:
            raise ValueError("Target must be empty; refusing to overwrite existing points.")
    else:
        await client.create_collection(
            collection_name=target,
            vectors_config={"dense": models.VectorParams(size=dense_params.size, distance=dense_params.distance)},
            sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
    await client.create_payload_index(
        collection_name=target, field_name="paper_id",
        field_schema=models.PayloadSchemaType.KEYWORD, wait=True,
    )

    offset = None
    copied = 0
    while True:
        records, offset = await client.scroll(
            collection_name=source, offset=offset, limit=batch_size,
            with_payload=True, with_vectors=True,
        )
        texts = []
        for record in records:
            payload = record.payload or {}
            if not isinstance(record.vector, list) or len(record.vector) != dense_params.size:
                raise ValueError(f"Point {record.id} has an invalid Dense vector.")
            if not payload.get("chunk_id") or not payload.get("paper_id"):
                raise ValueError(f"Point {record.id} is missing chunk/paper IDs.")
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"Point {record.id} has no usable body text.")
            texts.append(text)
        if records:
            sparse = await asyncio.to_thread(encoder.encode_documents, texts)
            points = [models.PointStruct(
                id=record.id, payload=record.payload,
                vector={"dense": record.vector, "sparse": models.SparseVector(indices=s.indices, values=s.values)},
            ) for record, s in zip(records, sparse, strict=True)]
            await client.upsert(collection_name=target, points=points, wait=True)
            copied += len(points)
        if offset is None:
            break

    target_count = (await client.count(target, exact=True)).count
    final_source_count = (await client.count(source, exact=True)).count
    if not (copied == target_count == source_count == final_source_count):
        raise RuntimeError("Migration counts differ; keep using the source and inspect the target.")
    return copied


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--url", help="Qdrant server URL")
    location.add_argument("--path", help="Local Qdrant storage path")
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--prompt-api-key", action="store_true")
    args = parser.parse_args()
    key = getpass("Qdrant API key: ") if args.prompt_api_key else None
    encoder = await asyncio.to_thread(BM25Encoder)
    client = AsyncQdrantClient(path=args.path) if args.path else AsyncQdrantClient(url=args.url, api_key=key)
    try:
        copied = await backfill(client, encoder, args.source, args.target, args.batch_size)
        print(f"Copied {copied} points. Source untouched; verify retrieval before switching collections.")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
