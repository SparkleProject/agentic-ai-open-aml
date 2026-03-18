"""
RAG service — ingest documents and retrieve context.

Coordinates the embedding provider, vector store, and chunker
to offer a simple ingest/query API.
"""

import structlog

from aml.services.embedding.protocol import EmbeddingProvider
from aml.services.rag.chunker import chunk_text
from aml.services.vector_db.protocol import VectorStore

logger = structlog.get_logger()

# Default Milvus collection for RAG documents
DEFAULT_COLLECTION = "rag_documents"


class RAGService:
    """Retrieval-Augmented Generation pipeline."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        collection_name: str = DEFAULT_COLLECTION,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> None:
        self._embedder = embedding_provider
        self._store = vector_store
        self._collection = collection_name
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

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
        Ingest a document: chunk → embed → store.

        Returns the number of chunks stored.
        """
        chunks = chunk_text(text, chunk_size=self._chunk_size, chunk_overlap=self._chunk_overlap)
        if not chunks:
            return 0

        logger.info("rag_ingest_start", tenant_id=tenant_id, source=source, chunks=len(chunks))

        # Embed all chunks in one batch call
        vectors = await self._embedder.embed_batch(chunks)

        # Generate deterministic-ish IDs so re-ingesting the same doc updates rather than duplicates
        ids = [f"{tenant_id}:{source}:{i}" for i in range(len(chunks))]
        metadata = [{"text": chunk, "source": source, "chunk_index": i} for i, chunk in enumerate(chunks)]

        count = await self._store.upsert(
            self._collection,
            ids=ids,
            vectors=vectors,
            metadata=metadata,
            tenant_id=tenant_id,
        )

        logger.info("rag_ingest_complete", tenant_id=tenant_id, source=source, stored=count)
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

        Returns a list of dicts: {text, source, score, chunk_index}.
        """
        query_vector = await self._embedder.embed_text(question)

        results = await self._store.search(
            self._collection,
            query_vector=query_vector,
            tenant_id=tenant_id,
            limit=limit,
        )

        logger.info("rag_query", tenant_id=tenant_id, question_len=len(question), hits=len(results))
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
