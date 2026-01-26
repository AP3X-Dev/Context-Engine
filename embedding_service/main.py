#!/usr/bin/env python3
"""
Shared Embedding Service - One model instance serves all indexers.

Endpoints:
    POST /embed - Embed texts, returns vectors
    GET /health - Health check for k8s probes

Memory: ~1-2 GB (single ONNX model)
Concurrency: Controlled via EMBED_MAX_CONCURRENT semaphore
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

# Config
MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
MAX_CONCURRENT = int(os.environ.get("EMBED_MAX_CONCURRENT", "2") or 2)
MAX_BATCH_SIZE = int(os.environ.get("EMBED_MAX_BATCH", "256") or 256)

# Global model and semaphore
_model = None
_semaphore = threading.Semaphore(MAX_CONCURRENT)
_model_dim = None


def _load_model():
    """Load embedding model once at startup."""
    global _model, _model_dim
    from fastembed import TextEmbedding
    
    logger.info(f"Loading model: {MODEL_NAME}")
    _model = TextEmbedding(model_name=MODEL_NAME)
    
    # Warmup and get dimension
    warmup = list(_model.embed(["warmup"]))
    _model_dim = len(warmup[0])
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
    """Synchronous embedding with semaphore."""
    with _semaphore:
        return [vec.tolist() for vec in _model.embed(texts)]


@app.get("/health")
async def health():
    """Health check for k8s probes."""
    return {"status": "ok", "model": MODEL_NAME, "dim": _model_dim}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("EMBED_SERVICE_PORT", "8100"))
    uvicorn.run(app, host="0.0.0.0", port=port)

