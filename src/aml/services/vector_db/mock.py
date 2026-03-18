"""
In-memory vector store for unit tests.

Stores vectors in a dict, supports cosine similarity search,
and enforces tenant isolation without any external dependencies.
"""

import math
from typing import Any

import structlog

logger = structlog.get_logger()


class MockVectorStore:
    """In-memory vector store that mimics tenant-isolated Milvus behaviour."""

    def __init__(self) -> None:
        # {collection_name: [{"id": ..., "tenant_id": ..., "vector": ..., ...}]}
        self._data: dict[str, list[dict[str, Any]]] = {}
        self._collections: dict[str, int] = {}  # collection_name -> dimensions

    async def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        if collection_name not in self._data:
            self._data[collection_name] = []
            self._collections[collection_name] = dimensions

    async def upsert(
        self,
        collection_name: str,
        *,
        ids: list[str],
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
        tenant_id: str,
    ) -> int:
        if collection_name not in self._data:
            self._data[collection_name] = []

        existing_ids = {row["id"] for row in self._data[collection_name] if row["tenant_id"] == tenant_id}

        for vid, vec, meta in zip(ids, vectors, metadata, strict=True):
            row = {
                "id": vid,
                "tenant_id": tenant_id,
                "vector": vec,
                **meta,
            }
            if vid in existing_ids:
                self._data[collection_name] = [r for r in self._data[collection_name] if r["id"] != vid]
            self._data[collection_name].append(row)

        return len(ids)

    async def search(
        self,
        collection_name: str,
        *,
        query_vector: list[float],
        tenant_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        rows = self._data.get(collection_name, [])
        tenant_rows = [r for r in rows if r["tenant_id"] == tenant_id]

        scored = []
        for row in tenant_rows:
            score = self._cosine_similarity(query_vector, row["vector"])
            scored.append(
                {
                    "id": row["id"],
                    "score": score,
                    "text": row.get("text", ""),
                    "source": row.get("source", ""),
                    "chunk_index": row.get("chunk_index", 0),
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    async def delete(
        self,
        collection_name: str,
        *,
        ids: list[str],
        tenant_id: str,
    ) -> int:
        before = len(self._data.get(collection_name, []))
        self._data[collection_name] = [
            r for r in self._data.get(collection_name, []) if not (r["id"] in ids and r["tenant_id"] == tenant_id)
        ]
        return before - len(self._data[collection_name])

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
