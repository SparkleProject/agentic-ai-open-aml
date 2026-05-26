"""
Milvus vector store implementation with hybrid search support.

Uses pymilvus for tenant-isolated vector operations.
Tenant isolation is achieved via a ``tenant_id`` field on every row
and filtered on every query.

Supports both dense-only and hybrid (dense + sparse) search modes.
When sparse vectors are provided during upsert, the collection is
created with both a FLOAT_VECTOR and a SPARSE_FLOAT_VECTOR field.
Hybrid search uses Reciprocal Rank Fusion (RRF) to merge results.
"""

from typing import Any

import structlog
from pymilvus import (
    AnnSearchRequest,
    CollectionSchema,
    DataType,
    FieldSchema,
    MilvusClient,
    RRFRanker,
)

logger = structlog.get_logger()

# Default collection used by RAG
DEFAULT_COLLECTION = "rag_documents"


class MilvusVectorStore:
    """Milvus-backed vector store with per-tenant isolation and hybrid search."""

    def __init__(self, *, host: str = "localhost", port: int = 19530) -> None:
        self._uri = f"http://{host}:{port}"
        self._client = MilvusClient(uri=self._uri)
        # Track which collections have a sparse field so we know whether
        # to run hybrid search or dense-only search at query time.
        self._sparse_enabled: dict[str, bool] = {}
        logger.info("milvus_vector_store_init", uri=self._uri)

    async def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        """Create the collection if it doesn't already exist.

        The collection is created with both dense and sparse vector fields
        to support hybrid search out of the box.
        """
        if self._client.has_collection(collection_name):
            logger.debug("milvus_collection_exists", collection=collection_name)
            # Assume existing collections may have sparse support
            self._sparse_enabled[collection_name] = True
            return

        schema = CollectionSchema(
            fields=[
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
                FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dimensions),
                FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
                FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=1024),
                FieldSchema(name="chunk_index", dtype=DataType.INT64),
            ],
            description=f"RAG document store ({dimensions}d, hybrid)",
        )

        self._client.create_collection(
            collection_name=collection_name,
            schema=schema,
        )

        # Dense vector index — cosine similarity
        self._client.create_index(
            collection_name=collection_name,
            field_name="vector",
            index_params={"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}},
        )

        # Sparse vector index — inverted index with inner product
        self._client.create_index(
            collection_name=collection_name,
            field_name="sparse_vector",
            index_params={"index_type": "SPARSE_INVERTED_INDEX", "metric_type": "IP"},
        )

        self._sparse_enabled[collection_name] = True
        logger.info(
            "milvus_collection_created",
            collection=collection_name,
            dimensions=dimensions,
            hybrid=True,
        )

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
        """Insert vectors with tenant isolation.

        When ``sparse_vectors`` is provided, each row stores both the
        dense and sparse representations for hybrid retrieval.
        """
        rows = []
        for i, (vid, vec, meta) in enumerate(zip(ids, vectors, metadata, strict=True)):
            row: dict[str, Any] = {
                "id": vid,
                "tenant_id": tenant_id,
                "vector": vec,
                "text": meta.get("text", ""),
                "source": meta.get("source", ""),
                "chunk_index": meta.get("chunk_index", i),
            }
            # Attach sparse vector if available
            if sparse_vectors is not None:
                row["sparse_vector"] = sparse_vectors[i]
            else:
                # Provide an empty sparse vector so the field is populated
                row["sparse_vector"] = {}
            rows.append(row)

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
        query_sparse_vector: dict[int, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Search with mandatory tenant_id filter.

        When ``query_sparse_vector`` is provided and the collection
        supports sparse vectors, performs a hybrid search using
        Reciprocal Rank Fusion (RRF) to merge dense and sparse results.
        Otherwise falls back to dense-only search.
        """
        tenant_filter = f'tenant_id == "{tenant_id}"'
        output_fields = ["text", "source", "chunk_index", "tenant_id"]

        use_hybrid = query_sparse_vector is not None and self._sparse_enabled.get(collection_name, False)

        if use_hybrid:
            return self._hybrid_search(
                collection_name,
                query_vector=query_vector,
                query_sparse_vector=query_sparse_vector,
                tenant_filter=tenant_filter,
                output_fields=output_fields,
                limit=limit,
            )

        return self._dense_search(
            collection_name,
            query_vector=query_vector,
            tenant_filter=tenant_filter,
            output_fields=output_fields,
            limit=limit,
        )

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

    # ------------------------------------------------------------------
    # Private search helpers
    # ------------------------------------------------------------------

    def _dense_search(
        self,
        collection_name: str,
        *,
        query_vector: list[float],
        tenant_filter: str,
        output_fields: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Standard dense-only vector search."""
        results = self._client.search(
            collection_name=collection_name,
            data=[query_vector],
            filter=tenant_filter,
            limit=limit,
            output_fields=output_fields,
        )

        return self._parse_search_results(results, collection_name, "dense")

    def _hybrid_search(
        self,
        collection_name: str,
        *,
        query_vector: list[float],
        query_sparse_vector: dict[int, float],
        tenant_filter: str,
        output_fields: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Hybrid search combining dense + sparse via RRF reranking."""
        # Dense ANN request
        dense_req = AnnSearchRequest(
            data=[query_vector],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"nprobe": 16}},
            limit=limit,
            expr=tenant_filter,
        )

        # Sparse ANN request
        sparse_req = AnnSearchRequest(
            data=[query_sparse_vector],
            anns_field="sparse_vector",
            param={"metric_type": "IP"},
            limit=limit,
            expr=tenant_filter,
        )

        results = self._client.hybrid_search(
            collection_name=collection_name,
            reqs=[dense_req, sparse_req],
            ranker=RRFRanker(),
            limit=limit,
            output_fields=output_fields,
        )

        return self._parse_search_results(results, collection_name, "hybrid")

    def _parse_search_results(
        self,
        results: Any,
        collection_name: str,
        mode: str,
    ) -> list[dict[str, Any]]:
        """Parse pymilvus search results into a uniform list of dicts."""
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

        logger.debug(
            "milvus_search",
            collection=collection_name,
            mode=mode,
            hits=len(hits),
        )
        return hits
