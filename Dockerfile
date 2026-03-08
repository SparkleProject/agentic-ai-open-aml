# ==============================================================================
# Dockerfile — Production multi-stage build
# ==============================================================================
# Stage 1: Build dependencies
# Stage 2: Slim runtime image
# ==============================================================================

# --- Build stage ---
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir --upgrade pip

# Copy dependency files first (Docker layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install ".[ai]"

# --- Runtime stage ---
FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY src/ src/

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

EXPOSE 8000

CMD ["uvicorn", "aml.main:app", "--host", "0.0.0.0", "--port", "8000"]
