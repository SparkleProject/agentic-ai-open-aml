"""
In-memory vector store for unit tests.

Stores vectors in a dict, supports cosine similarity search,
and enforces tenant isolation without any external dependencies.

Supports optional sparse vectors for hybrid search simulation.
When both dense and sparse query vectors are provided, results
from each leg are combined using a simplified Reciprocal Rank
Fusion (RRF) score.
"""

import math
from typing import Any

import structlog

logger = structlog.get_logger()


class MockVectorStore:
    """In-memory vector store that mimics tenant-isolated Milvus behaviour."""

    def __init__(self) -> None:
        # {collection_name: [{&quot;id&quot;: ..., &quot;tenant_id&quot;: ..., &quot;vector&quot;: ..., ...}]}
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
        sparse_vectors: list[dict[int, float]] | None = None,
    ) -> int:
        if collection_name not in self._data:
            self._data[collection_name] = []

        existing_ids = {row["id"] for row in self._data[collection_name] if row["tenant_id"] == tenant_id}

        for i, (vid, vec, meta) in enumerate(zip(ids, vectors, metadata, strict=True)):
            row: dict[str, Any] = {
                "id": vid,
                "tenant_id": tenant_id,
                "vector": vec,
                **meta,
            }
            if sparse_vectors is not None:
                row["sparse_vector"] = sparse_vectors[i]
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
        query_sparse_vector: dict[int, float] | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._data.get(collection_name, [])
        tenant_rows = [r for r in rows if r["tenant_id"] == tenant_id]

        if query_sparse_vector is not None:
            return self._hybrid_search(tenant_rows, query_vector, query_sparse_vector, limit)

        return self._dense_search(tenant_rows, query_vector, limit)

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

    # ------------------------------------------------------------------
    # Search implementations
    # ------------------------------------------------------------------

    def _dense_search(
        self,
        rows: list[dict[str, Any]],
        query_vector: list[float],
        limit: int,
    ) -> list[dict[str, Any]]:
        scored = []
        for row in rows:
            score = self._cosine_similarity(query_vector, row["vector"])
            scored.append(self._hit(row, score))
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def _hybrid_search(
        self,
        rows: list[dict[str, Any]],
        query_vector: list[float],
        query_sparse_vector: dict[int, float],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Combine dense and sparse scores using weighted normalised scoring.

        Uses a 50/50 weighted combination of normalised dense (cosine)
        and sparse (inner-product) scores.  This is a simplified mock
        of Milvus' RRF reranking that behaves predictably even with
        very small result sets.
        """
        # Compute raw scores
        entries: list[tuple[dict[str, Any], float, float]] = []
        for row in rows:
            dense = self._cosine_similarity(query_vector, row["vector"])
            sv = row.get("sparse_vector", {})
            sparse = self._sparse_inner_product(query_sparse_vector, sv) if sv else 0.0
            entries.append((row, dense, sparse))

        # Normalise each score stream to [0, 1]
        dense_max = max((e[1] for e in entries), default=1.0) or 1.0
        sparse_max = max((e[2] for e in entries), default=1.0) or 1.0

        combined: list[tuple[dict[str, Any], float]] = []
        for row, dense, sparse in entries:
            norm_dense = dense / dense_max
            norm_sparse = sparse / sparse_max
            score = 0.5 * norm_dense + 0.5 * norm_sparse
            combined.append((row, score))

        combined.sort(key=lambda x: x[1], reverse=True)

        results = []
        for row, score in combined[:limit]:
            results.append(self._hit(row, score))
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hit(row: dict[str, Any], score: float) -> dict[str, Any]:
        return {
            "id": row["id"],
            "score": score,
            "text": row.get("text", ""),
            "source": row.get("source", ""),
            "chunk_index": row.get("chunk_index", 0),
        }

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    @staticmethod
    def _sparse_inner_product(a: dict[int, float], b: dict[int, float]) -> float:
        """Inner product between two sparse vectors."""
        score = 0.0
        for token_id, weight in a.items():
            if token_id in b:
                score += weight * b[token_id]
        return score
