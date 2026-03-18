"""
RAG API router.

Provides endpoints for document ingestion and context retrieval.
All operations require a valid X-Tenant-ID header.
"""

from fastapi import APIRouter, Header, HTTPException

from aml.api.models.rag import (
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    QueryResult,
)
from aml.core.config import get_settings
from aml.services.embedding.factory import get_embedding_provider
from aml.services.rag.service import RAGService
from aml.services.vector_db.factory import get_vector_store

router = APIRouter(prefix="/rag", tags=["RAG"])

# Lazily initialised singleton (created on first request)
_rag_service: RAGService | None = None


async def _get_rag_service() -> RAGService:
    """Get or create the RAG service singleton."""
    global _rag_service
    if _rag_service is None:
        settings = get_settings()
        embedding = get_embedding_provider(settings)
        vector_store = get_vector_store(settings)
        _rag_service = RAGService(embedding_provider=embedding, vector_store=vector_store)
        await _rag_service.initialise()
    return _rag_service


def _require_tenant(x_tenant_id: str | None) -> str:
    """Validate that X-Tenant-ID header is present."""
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    body: IngestRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> IngestResponse:
    """Ingest a document: chunk → embed → store."""
    tenant_id = _require_tenant(x_tenant_id)
    svc = await _get_rag_service()

    count = await svc.ingest(text=body.text, tenant_id=tenant_id, source=body.source)
    return IngestResponse(chunks_stored=count, source=body.source)


@router.post("/query", response_model=QueryResponse)
async def query_context(
    body: QueryRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
) -> QueryResponse:
    """Retrieve context chunks relevant to a question."""
    tenant_id = _require_tenant(x_tenant_id)
    svc = await _get_rag_service()

    results = await svc.query(question=body.question, tenant_id=tenant_id, limit=body.limit)
    formatted = svc.format_context(results)

    return QueryResponse(
        results=[
            QueryResult(
                text=str(r.get("text", "")),
                source=str(r.get("source", "")),
                score=float(r.get("score", 0.0)),
                chunk_index=int(r.get("chunk_index", 0)),
            )
            for r in results
        ],
        context=formatted,
    )
