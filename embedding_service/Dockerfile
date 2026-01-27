FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.5.27 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/app/models \
    HF_HOME=/app/models

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY main.py .

ENV PATH="/app/.venv/bin:$PATH"

ARG EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5-Q
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}')"

ENV EMBED_SERVICE_PORT=8100
EXPOSE 8100

CMD ["python", "main.py"]
