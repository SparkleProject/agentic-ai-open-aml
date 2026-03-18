"""Pydantic models for RAG API requests and responses."""

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    """Request body for document ingestion."""

    text: str = Field(..., min_length=1, description="Document text to ingest")
    source: str = Field(default="manual", description="Source identifier (e.g. filename, URL)")


class IngestResponse(BaseModel):
    """Response after ingestion."""

    chunks_stored: int
    source: str


class QueryRequest(BaseModel):
    """Request body for RAG context retrieval."""

    question: str = Field(..., min_length=1, description="Natural language question")
    limit: int = Field(default=5, ge=1, le=20, description="Max number of chunks to return")


class QueryResult(BaseModel):
    """A single search result."""

    text: str
    source: str
    score: float
    chunk_index: int = 0


class QueryResponse(BaseModel):
    """Response with retrieved context chunks."""

    results: list[QueryResult]
    context: str = Field(description="Formatted context string ready for LLM prompt")
