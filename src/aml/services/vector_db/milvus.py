"""
Milvus vector store implementation.

Uses pymilvus for tenant-isolated vector operations.
Tenant isolation is achieved via a ``tenant_id`` field on every row
and filtered on every query.
"""

from typing import Any

import structlog
from pymilvus import (
    CollectionSchema,
    DataType,
    FieldSchema,
    MilvusClient,
)

logger = structlog.get_logger()

# Default collection used by RAG
DEFAULT_COLLECTION = "rag_documents"


class MilvusVectorStore:
    """Milvus-backed vector store with per-tenant isolation."""

    def __init__(self, *, host: str = "localhost", port: int = 19530) -> None:
        self._uri = f"http://{host}:{port}"
        self._client = MilvusClient(uri=self._uri)
        logger.info("milvus_vector_store_init", uri=self._uri)

    async def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        """Create the collection if it doesn't already exist."""
        if self._client.has_collection(collection_name):
            logger.debug("milvus_collection_exists", collection=collection_name)
            return

        schema = CollectionSchema(
            fields=[
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
                FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dimensions),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=1024),
                FieldSchema(name="chunk_index", dtype=DataType.INT64),
            ],
            description=f"RAG document store ({dimensions}d)",
        )

        self._client.create_collection(
            collection_name=collection_name,
            schema=schema,
        )

        # Create index for vector similarity search
        self._client.create_index(
            collection_name=collection_name,
            field_name="vector",
            index_params={"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}},
        )

        logger.info("milvus_collection_created", collection=collection_name, dimensions=dimensions)

    async def upsert(
        self,
        collection_name: str,
        *,
        ids: list[str],
        vectors: list[list[float]],
        metadata: list[dict[str, Any]],
        tenant_id: str,
    ) -> int:
        """Insert vectors with tenant isolation."""
        rows = []
        for i, (vid, vec, meta) in enumerate(zip(ids, vectors, metadata, strict=True)):
            rows.append(
                {
                    "id": vid,
                    "tenant_id": tenant_id,
                    "vector": vec,
                    "text": meta.get("text", ""),
                    "source": meta.get("source", ""),
                    "chunk_index": meta.get("chunk_index", i),
                }
            )

        result = self._client.upsert(collection_name=collection_name, data=rows)
        logger.info("milvus_upsert", collection=collection_name, tenant_id=tenant_id, count=len(rows))
        return result.get("upsert_count", len(rows)) if isinstance(result, dict) else len(rows)

    async def search(
        self,
        collection_name: str,
        *,
        query_vector: list[float],
        tenant_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Search with mandatory tenant_id filter."""
        results = self._client.search(
            collection_name=collection_name,
            data=[query_vector],
            filter=f'tenant_id == "{tenant_id}"',
            limit=limit,
            output_fields=["text", "source", "chunk_index", "tenant_id"],
        )

        hits: list[dict[str, Any]] = []
        if results:
            for hit in results[0]:
                hits.append(
                    {
                        "id": hit["id"],
                        "score": hit["distance"],
                        "text": hit["entity"].get("text", ""),
                        "source": hit["entity"].get("source", ""),
                        "chunk_index": hit["entity"].get("chunk_index", 0),
                    }
                )

        logger.debug("milvus_search", collection=collection_name, tenant_id=tenant_id, hits=len(hits))
        return hits

    async def delete(
        self,
        collection_name: str,
        *,
        ids: list[str],
        tenant_id: str,
    ) -> int:
        """Delete by IDs with tenant filter for safety."""
        filter_expr = f'tenant_id == "{tenant_id}" and id in {ids}'
        result = self._client.delete(collection_name=collection_name, filter=filter_expr)
        count = result.get("delete_count", 0) if isinstance(result, dict) else 0
        logger.info("milvus_delete", collection=collection_name, tenant_id=tenant_id, count=count)
        return count
