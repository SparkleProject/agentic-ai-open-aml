"""
Application entry point for uvicorn.

Run with: uvicorn aml.main:app --reload
Or:       python -m aml.main
"""

from aml.app import create_app
from aml.core.config import get_settings

app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "aml.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=settings.workers,
        log_level=settings.log_level.lower(),
    )
