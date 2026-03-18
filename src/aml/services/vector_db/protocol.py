"""
Protocol for vector store providers.

Any vector store (Milvus, Pinecone, in-memory) must implement this
interface. All operations are tenant-scoped — callers never need to
filter by tenant_id manually.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    """Interface for tenant-isolated vector storage."""

    async def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        """Create a collection if it doesn't exist."""
        ...

    async def upsert(
        self,
        collection_name: str,
        *,
        ids: list[str],
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
        tenant_id: str,
    ) -> int:
        """
        Insert or update vectors with metadata, scoped to a tenant.

        Returns the number of vectors upserted.
        """
        ...

    async def search(
        self,
        collection_name: str,
        *,
        query_vector: list[float],
        tenant_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search for the nearest vectors belonging to a specific tenant.

        Returns a list of dicts with keys: id, score, metadata.
        """
        ...

    async def delete(
        self,
        collection_name: str,
        *,
        ids: list[str],
        tenant_id: str,
    ) -> int:
        """Delete vectors by ID for a given tenant. Returns count deleted."""
        ...
