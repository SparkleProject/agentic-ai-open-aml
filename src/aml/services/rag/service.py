"""
RAG service — ingest documents and retrieve context.

Coordinates the embedding provider, vector store, and chunker
to offer a simple ingest/query API.

Supports hybrid search when a sparse embedding provider is
configured.  Falls back gracefully to dense-only search when
no sparse provider is available.
"""

import structlog

from aml.services.embedding.protocol import EmbeddingProvider, SparseEmbeddingProvider
from aml.services.rag.chunker import chunk_text
from aml.services.vector_db.protocol import VectorStore

logger = structlog.get_logger()

# Default Milvus collection for RAG documents
DEFAULT_COLLECTION = "rag_documents"


class RAGService:
    """Retrieval-Augmented Generation pipeline with hybrid search support."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        sparse_embedding_provider: SparseEmbeddingProvider | None = None,
        collection_name: str = DEFAULT_COLLECTION,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> None:
        self._embedder = embedding_provider
        self._sparse_embedder = sparse_embedding_provider
        self._store = vector_store
        self._collection = collection_name
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    @property
    def hybrid_enabled(self) -> bool:
        """Whether hybrid search is active (sparse provider configured)."""
        return self._sparse_embedder is not None

    async def initialise(self) -> None:
        """Create the vector collection if it doesn't exist."""
        await self._store.ensure_collection(self._collection, self._embedder.dimensions)

    async def ingest(
        self,
        *,
        text: str,
        tenant_id: str,
        source: str = "unknown",
    ) -> int:
        """
        Ingest a document: chunk → embed (dense + sparse) → store.

        Returns the number of chunks stored.
        """
        chunks = chunk_text(text, chunk_size=self._chunk_size, chunk_overlap=self._chunk_overlap)
        if not chunks:
            return 0

        logger.info("rag_ingest_start", tenant_id=tenant_id, source=source, chunks=len(chunks))

        # Dense embeddings (always required)
        vectors = await self._embedder.embed_batch(chunks)

        # Sparse embeddings (optional — enables hybrid search)
        sparse_vectors: list[dict[int, float]] | None = None
        if self._sparse_embedder is not None:
            sparse_vectors = await self._sparse_embedder.embed_sparse_batch(chunks)
            logger.debug("rag_sparse_embeddings_generated", count=len(sparse_vectors))

        # Generate deterministic-ish IDs so re-ingesting the same doc updates rather than duplicates
        ids = [f"{tenant_id}:{source}:{i}" for i in range(len(chunks))]
        metadata = [{"text": chunk, "source": source, "chunk_index": i} for i, chunk in enumerate(chunks)]

        count = await self._store.upsert(
            self._collection,
            ids=ids,
            vectors=vectors,
            metadata=metadata,
            tenant_id=tenant_id,
            sparse_vectors=sparse_vectors,
        )

        logger.info(
            "rag_ingest_complete",
            tenant_id=tenant_id,
            source=source,
            stored=count,
            hybrid=self.hybrid_enabled,
        )
        return count

    async def query(
        self,
        *,
        question: str,
        tenant_id: str,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        """
        Retrieve context chunks relevant to a question.

        Performs hybrid search when a sparse embedding provider is
        configured; otherwise falls back to dense-only search.

        Returns a list of dicts: {text, source, score, chunk_index}.
        """
        # Dense query vector (always required)
        query_vector = await self._embedder.embed_text(question)

        # Sparse query vector (optional — enables hybrid search)
        query_sparse_vector: dict[int, float] | None = None
        if self._sparse_embedder is not None:
            query_sparse_vector = await self._sparse_embedder.embed_sparse(question)

        results = await self._store.search(
            self._collection,
            query_vector=query_vector,
            tenant_id=tenant_id,
            limit=limit,
            query_sparse_vector=query_sparse_vector,
        )

        logger.info(
            "rag_query",
            tenant_id=tenant_id,
            question_len=len(question),
            hits=len(results),
            hybrid=self.hybrid_enabled,
        )
        return results

    def format_context(self, results: list[dict[str, object]], *, max_chars: int = 4000) -> str:
        """Format retrieved chunks into a context string for the LLM prompt."""
        parts: list[str] = []
        total = 0
        for r in results:
            text = str(r.get("text", ""))
            source = str(r.get("source", ""))
            block = f"[Source: {source}]\n{text}"
            if total + len(block) > max_chars:
                break
            parts.append(block)
            total += len(block)

        return "\n\n---\n\n".join(parts)
