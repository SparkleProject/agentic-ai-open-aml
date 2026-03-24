"""
Async database session management.

Provides:
- ``engine``: the async SQLAlchemy engine (created once at startup)
- ``async_session_factory``: creates new ``AsyncSession`` instances
- ``get_db()``: FastAPI dependency that yields a session per request
- ``init_db()`` / ``close_db()``: lifespan hooks
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from aml.core.config import Settings

# Module-level singletons — populated by init_db()
_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(settings: Settings) -> None:
    """Initialise the async engine and session factory (called at startup)."""
    global _engine, _session_factory

    _engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=5,
        max_overflow=10,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def close_db() -> None:
    """Dispose engine connections (called at shutdown)."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a session and ensures cleanup."""
    if _session_factory is None:
        msg = "Database not initialised. Call init_db() first."
        raise RuntimeError(msg)

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
