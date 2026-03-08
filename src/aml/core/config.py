"""
Application configuration.

Uses pydantic-settings to load from environment variables and .env files.
All settings are centralised here — no magic strings scattered across the codebase.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AML_",
        case_sensitive=False,
    )

    # --- Application ---
    app_name: str = "Agentic AI Open AML"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = Field(default="development", description="development | staging | production")

    # --- Server ---
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8000
    workers: int = 1

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://aml:aml@localhost:5432/aml",
        description="Async SQLAlchemy database URL",
    )

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- AI / LLM ---
    llm_provider: str = Field(default="bedrock", description="bedrock | ollama | mock")
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # --- Vector Database ---
    vector_db_provider: str = Field(default="milvus", description="milvus | mock")
    milvus_host: str = "localhost"
    milvus_port: int = 19530

    # --- Logging ---
    log_level: str = "INFO"
    log_format: str = Field(default="json", description="json | console")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
