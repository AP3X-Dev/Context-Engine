#!/usr/bin/env python3
"""
Shared Embedding Service - One model instance serves all indexers.

Endpoints:
    POST /embed - Embed texts, returns vectors
    GET /health - Health check for k8s probes

Memory: ~3-4 GB (single ONNX model + inference overhead)
Concurrency: Controlled via EMBED_MAX_CONCURRENT semaphore

ONNX CPU Optimizations:
    ONNX_THREADS: Number of threads for intra-op parallelism (default: 4)
    ONNX_DISABLE_SPINNING: Set to 1 to disable thread spinning (saves CPU cycles)
    EMBED_OPTIMAL_BATCH: Internal batch size for chunking large requests (default: 16)

Memory Optimizations:
    EMBED_MAX_CONCURRENT: Max parallel inferences (default: 1 for memory safety)
    EMBED_GC_INTERVAL: Force GC every N batches (default: 1 = every batch)
    ONNX_ARENA_EXTEND_STRATEGY: Memory arena growth strategy (default: kSameAsRequested)

Model Options (via EMBEDDING_MODEL env var):
    BAAI/bge-base-en-v1.5          - Default, solid quality (768 dim, 0.21 GB)
    nomic-ai/nomic-embed-text-v1.5 - Faster, outperforms BGE on MTEB (768 dim, ~0.5 GB)
    BAAI/bge-large-en-v1.5         - Higher quality, slower (1024 dim, 0.67 GB)
"""
import asyncio
import gc
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Memory optimization: limit numpy/MKL thread spawning
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

# ONNX Runtime memory optimization - prevent arena from growing unbounded
os.environ.setdefault("ORT_ARENA_EXTEND_STRATEGY", "kSameAsRequested")

# Apply ONNX_DISABLE_SPINNING via OMP_WAIT_POLICY
# PASSIVE = threads sleep when idle (saves CPU), ACTIVE = threads spin (faster but burns CPU)
if os.environ.get("ONNX_DISABLE_SPINNING", "1").strip().lower() in {"1", "true", "yes"}:
    os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
else:
    os.environ.setdefault("OMP_WAIT_POLICY", "ACTIVE")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Memory-Optimized Configuration (target: <6GB per replica, FAST)
# ---------------------------------------------------------------------------
# Use quantized model by default - 4x smaller (0.13GB vs 0.52GB), same quality
MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5-Q")
# Allow 2 concurrent for speed - quantized model uses less memory per inference
MAX_CONCURRENT = max(1, int(os.environ.get("EMBED_MAX_CONCURRENT", "2") or 2))
MAX_BATCH_SIZE = int(os.environ.get("EMBED_MAX_BATCH", "128") or 128)

# ONNX runtime optimizations
ONNX_THREADS = int(os.environ.get("ONNX_THREADS", "4") or 4)
ONNX_DISABLE_SPINNING = os.environ.get("ONNX_DISABLE_SPINNING", "1").strip().lower() in {"1", "true", "yes"}
# Batch size 32 is fine with quantized model
EMBED_OPTIMAL_BATCH = int(os.environ.get("EMBED_OPTIMAL_BATCH", "32") or 32)
# GC after every batch to prevent memory creep
GC_INTERVAL = int(os.environ.get("EMBED_GC_INTERVAL", "1") or 1)
_gc_counter = 0

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
    """Synchronous embedding with semaphore, batching, and aggressive GC.

    Memory optimizations:
    - Chunks into small batches (16) to reduce peak memory
    - Forces GC after each batch to free tokenizer buffers immediately
    - Single semaphore prevents concurrent memory spikes
    """
    global _gc_counter
    with _semaphore:
        # Small batch for memory efficiency
        if len(texts) <= EMBED_OPTIMAL_BATCH:
            result = [vec.tolist() for vec in _model.embed(texts)]
            # Aggressive GC to free tokenizer/intermediate buffers
            _gc_counter += 1
            if GC_INTERVAL > 0 and _gc_counter >= GC_INTERVAL:
                gc.collect()
                _gc_counter = 0
            return result

        # Process in small chunks with GC between
        all_vectors = []
        for i in range(0, len(texts), EMBED_OPTIMAL_BATCH):
            chunk = texts[i:i + EMBED_OPTIMAL_BATCH]
            chunk_vectors = [vec.tolist() for vec in _model.embed(chunk)]
            all_vectors.extend(chunk_vectors)
            # GC after each chunk to prevent memory buildup
            _gc_counter += 1
            if GC_INTERVAL > 0 and _gc_counter >= GC_INTERVAL:
                gc.collect()
                _gc_counter = 0
        return all_vectors


def _get_memory_mb() -> float:
    """Get current process memory usage in MB."""
    try:
        import resource
        # RSS in bytes on macOS/Linux
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS returns bytes, Linux returns KB
        import sys
        if sys.platform == "darwin":
            return rss / (1024 * 1024)
        return rss / 1024
    except Exception:
        return -1


@app.get("/health")
async def health():
    """Health check for k8s probes. Returns full model config + memory."""
    return {
        "status": "ok",
        "memory_mb": round(_get_memory_mb(), 1),
        **_model_info,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("EMBED_SERVICE_PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port)

