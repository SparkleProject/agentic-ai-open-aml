"""Factory for creating the configured vector store."""

import structlog

from aml.core.config import Settings
from aml.services.vector_db.mock import MockVectorStore
from aml.services.vector_db.protocol import VectorStore

logger = structlog.get_logger()


def get_vector_store(settings: Settings) -> VectorStore:
    """Instantiate the vector store specified by ``settings.vector_db_provider``."""
    name = settings.vector_db_provider.lower()

    if name == "milvus":
        from aml.services.vector_db.milvus import MilvusVectorStore

        return MilvusVectorStore(host=settings.milvus_host, port=settings.milvus_port)

    if name == "mock":
        return MockVectorStore()

    msg = f"Unknown vector DB provider: {name}"
    raise ValueError(msg)
