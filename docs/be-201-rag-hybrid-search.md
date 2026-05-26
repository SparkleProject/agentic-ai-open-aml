# BE-201: RAG Pipeline & Context Optimiser (Hybrid Search) — Architecture Plan

**Date:** 2026-05-20
**Status:** DRAFT
**Author:** AI Architect

## 1. Context & Objective

Based on Phase 2 requirements, the RAG Pipeline (BE-201) must support **Hybrid Search (Vector + BM25)**. The objective is to combine conceptual semantic matching (Dense Vectors) with exact keyword/token matching (Sparse Vectors / BM25). This ensures that searches for conceptual ideas like "suspicious structuring" return semantically similar results, while exact entities like "Section 43B" or "SWIFT123" return precise keyword matches.

Currently, the implementation in `src/aml/services/vector_db/milvus.py` and `src/aml/services/rag/service.py` only utilizes standard Dense Vector search (Cosine Similarity).

This document outlines the step-by-step implementation plan to upgrade the existing RAG pipeline to support Hybrid Search using Milvus.

## 2. Architecture Approach: Dual-Stream Embedding & Hybrid Retrieval

To achieve Hybrid Search in Milvus, we must augment our data pipeline to handle two types of embeddings simultaneously:
1. **Dense Embeddings:** (Existing) Float vectors capturing semantic meaning.
2. **Sparse Embeddings:** New dictionary/JSON representations of term frequencies (BM25 or SPLADE) capturing exact keywords.

Milvus supports this natively via `DataType.SPARSE_FLOAT_VECTOR`, allowing us to store both representations in the same collection, perform dual searches, and rerank the combined results using Reciprocal Rank Fusion (RRF) or Weighted Ranker.

## 3. Step-by-Step Implementation Roadmap

### Step 1: Implement a Sparse Embedding Model
**Context:** We need a way to generate sparse vectors (term frequencies) from text chunks.
**Implementation Details:**
- Update `src/aml/services/embedding/protocol.py` to support a new method: `embed_sparse(text: str) -> dict[int, float]` and `embed_sparse_batch(texts: list[str])`.
- Create a new Sparse Embedder implementation (e.g., using `milvus_model.sparse.BM25EmbeddingFunction` or a local SPLADE model via the `transformers` library).
- **Explain:** Sparse embeddings output a dictionary mapping token IDs to their importance weights (frequencies). This gives us the "BM25" component of the search, allowing us to capture specific terminology and jargon without losing semantic meaning.

### Step 2: Update Milvus Schema in `vector_db/milvus.py`
**Context:** The vector database must be able to store the new sparse vectors.
**Implementation Details:**
- In `MilvusVectorStore.ensure_collection`, add a new field to the schema: `FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR)`.
- Create a new index specifically for the sparse field using the `SPARSE_INVERTED_INDEX` index type and the `IP` (Inner Product) metric type.
- **Explain:** Milvus requires separate indexes for dense and sparse vectors. The inverted index allows for extremely fast exact-match lookups across the sparse token dictionaries, functioning similarly to Elasticsearch's keyword lookup.

### Step 3: Update Vector Store `upsert` and `search` Methods
**Context:** The data access layer needs to write and read both vector types.
**Implementation Details:**
- **Upsert:** Modify `upsert` to accept `sparse_vectors` alongside `vectors` (dense). Map these into the rows being inserted.
- **Search (Hybrid):**
  - Update `search` to accept `query_dense_vector` and `query_sparse_vector`.
  - Import `AnnSearchRequest` and `RRFRanker` from `pymilvus`.
  - Construct two `AnnSearchRequest` objects: one targeting the `vector` field (dense) and one targeting the `sparse_vector` field.
  - Execute `self._client.hybrid_search(..., reqs=[req_dense, req_sparse], ranker=RRFRanker())`.
- **Explain:** `hybrid_search` executes both queries concurrently. The `RRFRanker` (Reciprocal Rank Fusion) mathematically merges the result sets, boosting documents that score high in *both* semantic meaning and exact keyword matching.

### Step 4: Update the RAG Service Pipeline (`rag/service.py`)
**Context:** The RAG ingestion and retrieval workflows must orchestrate both embedding types.
**Implementation Details:**
- **Ingest (`ingest`):** When text is chunked, pass the chunks to both the Dense Embedder and Sparse Embedder. Combine the results and pass them to the `vector_store.upsert` method.
- **Query (`query`):** When an agent queries the RAG system, embed the question into both a dense vector and a sparse vector. Pass both to the `vector_store.search` method.
- **Explain:** This bridges the application logic with the updated database logic, ensuring that every document ingested and every question asked leverages the full power of Hybrid Search seamlessly.

### Step 5: Backfill / Re-ingest Existing Data
**Context:** Existing data in the `rag_documents` collection only has dense vectors.
**Implementation Details:**
- Write a migration script or CLI command to drop the existing Milvus collection and re-ingest all regulatory documents using the new Hybrid pipeline.
- **Explain:** Because schema changes (adding a sparse vector field) are structurally significant and cannot be easily retrofitted to old data, it is safer and cleaner to rebuild the index for existing documents using the updated `ingest` logic.
