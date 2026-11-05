# ==============================================================================
# Multi-stage Dockerfile for BYKERS Backend
# ==============================================================================

# Stage 1: Build stage
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools if necessary
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies into a separate prefix directory
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Stage 2: Final runtime image
FROM python:3.12-slim AS runner

WORKDIR /app

# Ensure security: run as a non-privileged user
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /bin/bash -m appuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/install/bin:$PATH" \
    PYTHONPATH="/install/lib/python3.12/site-packages:/app"

# Copy installed Python packages from builder stage
COPY --from=builder /install /install

# Copy application source code
COPY --chown=appuser:appgroup app /app/app
COPY --chown=appuser:appgroup migrations /app/migrations
COPY --chown=appuser:appgroup scripts /app/scripts
COPY --chown=appuser:appgroup docs /app/docs
COPY --chown=appuser:appgroup alembic.ini /app/alembic.ini
COPY --chown=appuser:appgroup pyproject.toml /app/pyproject.toml

# Switch to non-root user
USER appuser

# Healthcheck hitting the unauthenticated /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

EXPOSE 8000

# Run uvicorn on all network interfaces
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

