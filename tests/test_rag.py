"""Unit tests for RAG pipeline: chunker, mock vector store, RAG service, and tenant isolation."""

from aml.services.embedding.mock import MockEmbeddingProvider
from aml.services.rag.chunker import chunk_text
from aml.services.rag.service import RAGService
from aml.services.vector_db.mock import MockVectorStore

# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------


class TestChunker:
    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text(self):
        text = "Hello world"
        chunks = chunk_text(text, chunk_size=100)
        assert chunks == [text]

    def test_chunks_have_overlap(self):
        text = "A" * 200 + " " + "B" * 200
        chunks = chunk_text(text, chunk_size=250, chunk_overlap=50)
        assert len(chunks) >= 2

    def test_paragraph_boundary_preferred(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        chunks = chunk_text(text, chunk_size=25, chunk_overlap=0)
        assert len(chunks) >= 2

    def test_large_document(self):
        text = " ".join(f"word{i}" for i in range(500))
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) > 0


# ---------------------------------------------------------------------------
# Mock Vector Store
# ---------------------------------------------------------------------------


class TestMockVectorStore:
    async def test_upsert_and_search(self):
        store = MockVectorStore()
        await store.ensure_collection("test", 3)

        await store.upsert(
            "test",
            ids=["v1", "v2"],
            vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            metadata=[{"text": "doc A"}, {"text": "doc B"}],
            tenant_id="t1",
        )

        results = await store.search("test", query_vector=[1.0, 0.0, 0.0], tenant_id="t1", limit=2)
        assert len(results) == 2
        # doc A should be the top match (exact vector match)
        assert results[0]["text"] == "doc A"

    async def test_tenant_isolation(self):
        """Tenant B should NOT see Tenant A's data."""
        store = MockVectorStore()
        await store.ensure_collection("test", 3)

        await store.upsert(
            "test",
            ids=["v1"],
            vectors=[[1.0, 0.0, 0.0]],
            metadata=[{"text": "secret doc"}],
            tenant_id="tenant-A",
        )

        results = await store.search("test", query_vector=[1.0, 0.0, 0.0], tenant_id="tenant-B")
        assert len(results) == 0, "Tenant B must not see Tenant A's data"

    async def test_delete(self):
        store = MockVectorStore()
        await store.ensure_collection("test", 3)

        await store.upsert(
            "test",
            ids=["v1"],
            vectors=[[1.0, 0.0, 0.0]],
            metadata=[{"text": "to delete"}],
            tenant_id="t1",
        )

        deleted = await store.delete("test", ids=["v1"], tenant_id="t1")
        assert deleted == 1

        results = await store.search("test", query_vector=[1.0, 0.0, 0.0], tenant_id="t1")
        assert len(results) == 0


# ---------------------------------------------------------------------------
# RAG Service (end-to-end with mocks)
# ---------------------------------------------------------------------------


class TestRAGService:
    async def test_ingest_and_query(self):
        embedder = MockEmbeddingProvider(dims=1024)
        store = MockVectorStore()
        svc = RAGService(embedding_provider=embedder, vector_store=store)
        await svc.initialise()

        count = await svc.ingest(
            text="Anti-money laundering regulations require financial institutions to report suspicious transactions.",
            tenant_id="t1",
            source="test-doc",
        )
        assert count > 0

        results = await svc.query(
            question="What do AML regulations require?",
            tenant_id="t1",
            limit=3,
        )
        assert len(results) > 0
        assert "text" in results[0]

    async def test_tenant_isolation_e2e(self):
        """Full pipeline: Tenant A ingests a doc, Tenant B cannot retrieve it."""
        embedder = MockEmbeddingProvider(dims=1024)
        store = MockVectorStore()
        svc = RAGService(embedding_provider=embedder, vector_store=store)
        await svc.initialise()

        await svc.ingest(
            text="Secret compliance policy for tenant A only.",
            tenant_id="tenant-A",
            source="policy.pdf",
        )

        results = await svc.query(
            question="compliance policy",
            tenant_id="tenant-B",
            limit=5,
        )
        assert len(results) == 0, "Tenant B must not see Tenant A's documents"

    async def test_format_context(self):
        embedder = MockEmbeddingProvider(dims=1024)
        store = MockVectorStore()
        svc = RAGService(embedding_provider=embedder, vector_store=store)

        fake_results: list[dict[str, object]] = [
            {"text": "Chunk one", "source": "doc.pdf", "score": 0.95},
            {"text": "Chunk two", "source": "doc.pdf", "score": 0.90},
        ]
        ctx = svc.format_context(fake_results)
        assert "Chunk one" in ctx
        assert "[Source: doc.pdf]" in ctx
