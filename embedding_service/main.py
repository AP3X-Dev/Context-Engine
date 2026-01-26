#!/usr/bin/env python3
"""
Shared Embedding Service - One model instance serves all indexers.

Endpoints:
    POST /embed - Embed texts, returns vectors
    GET /health - Health check for k8s probes

Memory: ~1-2 GB (single ONNX model)
Concurrency: Controlled via EMBED_MAX_CONCURRENT semaphore

ONNX CPU Optimizations:
    ONNX_THREADS: Number of threads for intra-op parallelism (default: 0 = auto)
    ONNX_DISABLE_SPINNING: Set to 1 to disable thread spinning (saves CPU cycles)
    EMBED_OPTIMAL_BATCH: Internal batch size for chunking large requests (default: 32)

Model Options (via EMBEDDING_MODEL env var):
    BAAI/bge-base-en-v1.5          - Default, solid quality (768 dim, 0.21 GB)
    nomic-ai/nomic-embed-text-v1.5-Q - Quantized, faster, outperforms BGE on MTEB (768 dim, 0.13 GB)
    BAAI/bge-large-en-v1.5         - Higher quality, slower (1024 dim, 0.67 GB)
"""
import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
MAX_CONCURRENT = max(1, int(os.environ.get("EMBED_MAX_CONCURRENT", "2") or 2))
MAX_BATCH_SIZE = int(os.environ.get("EMBED_MAX_BATCH", "256") or 256)

# ONNX runtime optimizations
ONNX_THREADS = int(os.environ.get("ONNX_THREADS", "0") or 0)  # 0 = auto (1 per physical core)
ONNX_DISABLE_SPINNING = os.environ.get("ONNX_DISABLE_SPINNING", "0").strip().lower() in {"1", "true", "yes"}
EMBED_OPTIMAL_BATCH = int(os.environ.get("EMBED_OPTIMAL_BATCH", "32") or 32)  # Sweet spot for CPU

# Global model and semaphore
_model = None
_semaphore = threading.Semaphore(MAX_CONCURRENT)
_model_dim = None
_model_info = {}


def _load_model():
    """Load embedding model with ONNX optimizations."""
    global _model, _model_dim, _model_info
    from fastembed import TextEmbedding

    logger.info(f"Loading model: {MODEL_NAME}")
    logger.info(f"ONNX config: threads={ONNX_THREADS or 'auto'}, disable_spinning={ONNX_DISABLE_SPINNING}, optimal_batch={EMBED_OPTIMAL_BATCH}")

    # Build kwargs for TextEmbedding
    # FastEmbed accepts 'threads' parameter for ONNX session
    model_kwargs = {}
    if ONNX_THREADS > 0:
        model_kwargs["threads"] = ONNX_THREADS

    _model = TextEmbedding(model_name=MODEL_NAME, **model_kwargs)

    # Apply additional ONNX session options if we can access the session
    # Note: FastEmbed may not expose all session options, but threads is the main one

    # Warmup and get dimension (also warms up ONNX runtime)
    logger.info("Warming up model...")
    warmup = list(_model.embed(["warmup query for initialization"]))
    _model_dim = len(warmup[0])

    # Store model info for health endpoint
    _model_info = {
        "model": MODEL_NAME,
        "dim": _model_dim,
        "threads": ONNX_THREADS or "auto",
        "disable_spinning": ONNX_DISABLE_SPINNING,
        "optimal_batch": EMBED_OPTIMAL_BATCH,
        "max_concurrent": MAX_CONCURRENT,
    }

    logger.info(f"Model loaded: dim={_model_dim}, max_concurrent={MAX_CONCURRENT}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model on startup."""
    _load_model()
    yield


app = FastAPI(title="Embedding Service", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: List[str]
    model: Optional[str] = None  # Ignored for now, single model


class EmbedResponse(BaseModel):
    vectors: List[List[float]]
    dim: int
    count: int


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    """Embed texts with concurrency control."""
    if not request.texts:
        return EmbedResponse(vectors=[], dim=_model_dim or 768, count=0)
    
    if len(request.texts) > MAX_BATCH_SIZE:
        raise HTTPException(400, f"Batch too large: {len(request.texts)} > {MAX_BATCH_SIZE}")
    
    # Run embedding in thread pool with semaphore
    loop = asyncio.get_event_loop()
    vectors = await loop.run_in_executor(None, _embed_sync, request.texts)
    
    return EmbedResponse(vectors=vectors, dim=_model_dim, count=len(vectors))


def _embed_sync(texts: List[str]) -> List[List[float]]:
    """Synchronous embedding with semaphore and optimal batching.

    Chunks large requests into EMBED_OPTIMAL_BATCH sized pieces for better
    CPU cache utilization and memory efficiency.
    """
    with _semaphore:
        # Chunk into optimal batch sizes for CPU efficiency
        if len(texts) <= EMBED_OPTIMAL_BATCH:
            return [vec.tolist() for vec in _model.embed(texts)]

        # Process in chunks
        all_vectors = []
        for i in range(0, len(texts), EMBED_OPTIMAL_BATCH):
            chunk = texts[i:i + EMBED_OPTIMAL_BATCH]
            chunk_vectors = [vec.tolist() for vec in _model.embed(chunk)]
            all_vectors.extend(chunk_vectors)
        return all_vectors


@app.get("/health")
async def health():
    """Health check for k8s probes. Returns full model config."""
    return {
        "status": "ok",
        **_model_info,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("EMBED_SERVICE_PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port)

