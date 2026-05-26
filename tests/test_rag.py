"""Unit tests for RAG pipeline: chunker, mock vector store, RAG service, and tenant isolation.

Tests cover both dense-only and hybrid (dense + sparse) search modes.
"""

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
# Mock Vector Store — Dense only
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
# Mock Vector Store — Hybrid search
# ---------------------------------------------------------------------------


class TestMockVectorStoreHybrid:
    async def test_hybrid_upsert_and_search(self):
        """Hybrid search should return results combining dense and sparse scores."""
        store = MockVectorStore()
        await store.ensure_collection("test", 3)

        await store.upsert(
            "test",
            ids=["v1", "v2"],
            vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            metadata=[{"text": "doc A about sanctions"}, {"text": "doc B about transactions"}],
            tenant_id="t1",
            sparse_vectors=[{100: 1.0, 200: 0.5}, {300: 1.0, 400: 0.5}],
        )

        # Hybrid query: dense vector matches v1, sparse vector also matches v1's token 100
        results = await store.search(
            "test",
            query_vector=[1.0, 0.0, 0.0],
            tenant_id="t1",
            limit=2,
            query_sparse_vector={100: 1.0},
        )
        assert len(results) == 2
        # v1 should be top because it matches on BOTH dense and sparse
        assert results[0]["text"] == "doc A about sanctions"

    async def test_sparse_keyword_boost(self):
        """A doc with equal dense similarity but strong sparse match should rank higher in hybrid."""
        store = MockVectorStore()
        await store.ensure_collection("test", 3)

        # v1 and v2 have nearly identical dense similarity to the query
        # but v2 has much stronger sparse overlap
        await store.upsert(
            "test",
            ids=["v1", "v2"],
            vectors=[[0.7, 0.7, 0.1], [0.7, 0.7, 0.0]],
            metadata=[{"text": "general compliance"}, {"text": "Section 43B specific"}],
            tenant_id="t1",
            sparse_vectors=[{999: 0.1}, {42: 5.0, 43: 5.0}],
        )

        # Query: dense is ~equal for both, sparse heavily favours v2
        results = await store.search(
            "test",
            query_vector=[0.7, 0.7, 0.05],
            tenant_id="t1",
            limit=2,
            query_sparse_vector={42: 5.0, 43: 5.0},
        )
        assert len(results) == 2
        # v2 should be boosted because sparse keyword match is very strong
        assert results[0]["text"] == "Section 43B specific"

    async def test_hybrid_tenant_isolation(self):
        """Hybrid search must still enforce tenant isolation."""
        store = MockVectorStore()
        await store.ensure_collection("test", 3)

        await store.upsert(
            "test",
            ids=["v1"],
            vectors=[[1.0, 0.0, 0.0]],
            metadata=[{"text": "tenant A doc"}],
            tenant_id="tenant-A",
            sparse_vectors=[{100: 1.0}],
        )

        results = await store.search(
            "test",
            query_vector=[1.0, 0.0, 0.0],
            tenant_id="tenant-B",
            query_sparse_vector={100: 1.0},
        )
        assert len(results) == 0, "Tenant B must not see Tenant A's data even in hybrid mode"

    async def test_fallback_to_dense_when_no_sparse_query(self):
        """When no sparse query vector is provided, search should still work (dense only)."""
        store = MockVectorStore()
        await store.ensure_collection("test", 3)

        await store.upsert(
            "test",
            ids=["v1"],
            vectors=[[1.0, 0.0, 0.0]],
            metadata=[{"text": "doc A"}],
            tenant_id="t1",
            sparse_vectors=[{100: 1.0}],
        )

        # No sparse query vector → falls back to dense-only
        results = await store.search(
            "test",
            query_vector=[1.0, 0.0, 0.0],
            tenant_id="t1",
        )
        assert len(results) == 1
        assert results[0]["text"] == "doc A"


# ---------------------------------------------------------------------------
# RAG Service (end-to-end with mocks) — Dense only
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


# ---------------------------------------------------------------------------
# RAG Service (end-to-end with mocks) — Hybrid search
# ---------------------------------------------------------------------------


class TestRAGServiceHybrid:
    async def test_hybrid_ingest_and_query(self):
        """RAG service with sparse provider should perform hybrid search."""
        embedder = MockEmbeddingProvider(dims=1024)
        store = MockVectorStore()
        # MockEmbeddingProvider now implements both dense and sparse
        svc = RAGService(
            embedding_provider=embedder,
            vector_store=store,
            sparse_embedding_provider=embedder,
        )
        await svc.initialise()
        assert svc.hybrid_enabled is True

        count = await svc.ingest(
            text="AUSTRAC requires reporting under Section 43B for suspicious matter reports.",
            tenant_id="t1",
            source="austrac-guide",
        )
        assert count > 0

        results = await svc.query(
            question="Section 43B suspicious matter",
            tenant_id="t1",
            limit=3,
        )
        assert len(results) > 0
        assert "text" in results[0]

    async def test_hybrid_disabled_without_sparse_provider(self):
        """Without a sparse provider, hybrid should be off."""
        embedder = MockEmbeddingProvider(dims=1024)
        store = MockVectorStore()
        svc = RAGService(embedding_provider=embedder, vector_store=store)
        assert svc.hybrid_enabled is False

    async def test_hybrid_tenant_isolation_e2e(self):
        """Hybrid pipeline must maintain tenant isolation."""
        embedder = MockEmbeddingProvider(dims=1024)
        store = MockVectorStore()
        svc = RAGService(
            embedding_provider=embedder,
            vector_store=store,
            sparse_embedding_provider=embedder,
        )
        await svc.initialise()

        await svc.ingest(
            text="Confidential AML policy for tenant A.",
            tenant_id="tenant-A",
            source="policy.pdf",
        )

        results = await svc.query(
            question="AML policy",
            tenant_id="tenant-B",
            limit=5,
        )
        assert len(results) == 0, "Tenant B must not see Tenant A's documents in hybrid mode"
