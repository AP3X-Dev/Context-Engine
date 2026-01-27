# Unified Context-Engine image for Kubernetes deployment
# Supports multiple roles: memory, indexer, watcher, llamacpp
FROM python:3.11-slim

# Install uv for 10-100x faster dependency installation
COPY --from=ghcr.io/astral-sh/uv:0.5.27 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORK_ROOTS="/work,/app" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install OS dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock /app/

# Install dependencies using uv (cached layer)
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

# Copy scripts and templates for all services
COPY scripts /app/scripts
COPY templates /app/templates

# Activate the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Create directories
WORKDIR /work

# Expose all necessary ports
EXPOSE 8000 8001 8002 8003 18000 18001 18002 18003

# Default to memory server
CMD ["python", "/app/scripts/mcp_memory_server.py"]
