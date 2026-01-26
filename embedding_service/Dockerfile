FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service
COPY main.py .

# Pre-download embedding model during build for faster startup
# Default: nomic (faster + better quality than BGE)
# Override at build time: --build-arg EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
ARG EMBEDDING_MODEL=nomic-ai/nomic-embed-text-v1.5
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}')"

ENV EMBED_SERVICE_PORT=8100
EXPOSE 8100

CMD ["python", "main.py"]

