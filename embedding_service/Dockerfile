FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service
COPY main.py .

# Pre-download default model during build (optional, speeds up startup)
# RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-base-en-v1.5')"

ENV EMBED_SERVICE_PORT=8100
EXPOSE 8100

CMD ["python", "main.py"]

