#!/usr/bin/env python3
import os
import argparse
import sys
import asyncio
import logging
import time
from pathlib import Path
from qdrant_client import QdrantClient, models

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.utils import sanitize_vector_name

logger = logging.getLogger(__name__)

# Warm start: load embedding model and warm Qdrant HNSW search path with a small query
# Useful to reduce first-query latency and set a higher runtime ef for quality

# Module-level warmup state
_WARMUP_STATE = {
    "status": "cold",  # "cold", "warming", "warm", or "failed"
    "latency_ms": None,
    "embedding_ms": None,
    "reranker_ms": None,
    "total_ms": None,
    "error": None,
}


def derive_vector_name(model_name: str) -> str:
    return sanitize_vector_name(model_name)


def get_embedding_model(model_name: str):
    """Get embedding model with Qwen3 support via embedder factory."""
    try:
        from scripts.embedder import get_embedding_model as _get_model
        return _get_model(model_name)
    except ImportError:
        pass
    # Fallback to direct fastembed
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=model_name)


def get_warmup_status() -> dict:
    """Get current warmup status for health endpoints."""
    return dict(_WARMUP_STATE)


async def warmup_reranker() -> float:
    """Warm up ONNX reranker model if enabled.

    Returns:
        Latency in milliseconds, or 0 if disabled/failed
    """
    reranker_enabled = os.environ.get("RERANKER_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
    if not reranker_enabled:
        return 0.0

    try:
        start = time.perf_counter()

        # Import and initialize reranker using centralized factory
        from scripts.reranker import get_reranker_model, rerank_pairs, is_reranker_available

        if not is_reranker_available():
            logger.info("Reranker not configured, skipping warmup")
            return 0.0

        reranker = get_reranker_model()
        if reranker is None:
            return 0.0

        # Run dummy inference with 3 candidates
        dummy_query = "warmup probe"
        dummy_candidates = [
            "first candidate text",
            "second candidate text",
            "third candidate text",
        ]

        # Reranker expects list of (query, document) tuples
        dummy_pairs = [(dummy_query, c) for c in dummy_candidates]

        # Run inference to cache model
        await asyncio.to_thread(rerank_pairs, dummy_pairs, reranker)

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(f"Reranker warmup: {elapsed:.1f}ms")
        return elapsed

    except Exception as e:
        logger.warning(f"Reranker warmup failed: {e}")
        return 0.0


async def warmup_embedding_model(model_name: str) -> float:
    """Warm up embedding model by loading and running dummy inference.

    Returns:
        Latency in milliseconds
    """
    try:
        start = time.perf_counter()
        model = await asyncio.to_thread(get_embedding_model, model_name)

        # Run dummy embedding to cache model
        dummy_text = ["warmup probe text"]
        vec = next(model.embed(dummy_text)).tolist()

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(f"Embedding model warmup ({model_name}): {elapsed:.1f}ms")
        return elapsed

    except Exception as e:
        logger.warning(f"Embedding warmup failed: {e}")
        raise


async def warmup_all_models() -> dict:
    """Orchestrate parallel warmup of embedding + reranker models.

    Updates global _WARMUP_STATE with results.

    Returns:
        dict with embedding_ms, reranker_ms, total_ms
    """
    global _WARMUP_STATE

    _WARMUP_STATE["status"] = "warming"

    try:
        start_total = time.perf_counter()

        model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")

        # Run warmup in parallel
        embedding_task = warmup_embedding_model(model_name)
        reranker_task = warmup_reranker()

        embedding_ms, reranker_ms = await asyncio.gather(embedding_task, reranker_task)

        total_ms = (time.perf_counter() - start_total) * 1000

        _WARMUP_STATE.update({
            "status": "warm",
            "embedding_ms": round(embedding_ms, 1),
            "reranker_ms": round(reranker_ms, 1),
            "total_ms": round(total_ms, 1),
            "latency_ms": round(total_ms, 1),
            "error": None,
        })

        return {
            "embedding_ms": round(embedding_ms, 1),
            "reranker_ms": round(reranker_ms, 1),
            "total_ms": round(total_ms, 1),
        }

    except Exception as e:
        _WARMUP_STATE.update({
            "status": "failed",
            "error": str(e),
        })
        logger.error(f"Warmup failed: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Warm start embeddings + Qdrant HNSW")
    parser.add_argument(
        "--query",
        "-q",
        default="warm start probe",
        help="Probe text to embed and search",
    )
    parser.add_argument(
        "--ef", type=int, default=256, help="HNSW ef (search) to warm caches"
    )
    parser.add_argument(
        "--limit", type=int, default=3, help="Number of points to request"
    )
    args = parser.parse_args()

    QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
    COLLECTION = os.environ.get("COLLECTION_NAME", "codebase")
    MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")

    print(
        f"Warm start: qdrant={QDRANT_URL} collection={COLLECTION} model={MODEL} ef={args.ef}"
    )

    client = QdrantClient(url=QDRANT_URL)
    model = get_embedding_model(MODEL)
    vec_name = derive_vector_name(MODEL)

    # Trigger model download/init
    vec = next(model.embed([args.query])).tolist()

    # Attempt new query_points API first
    try:
        qp = client.query_points(
            collection_name=COLLECTION,
            query=vec,
            using=vec_name,
            search_params=models.SearchParams(hnsw_ef=args.ef),
            limit=args.limit,
            with_payload=False,
        )
        _ = qp
        print("Warm start via query_points: OK")
        return
    except Exception:
        pass

    # Fallback to search API
    try:
        _ = client.search(
            collection_name=COLLECTION,
            query_vector={"name": vec_name, "vector": vec},
            limit=args.limit,
            with_payload=False,
        )
        print("Warm start via search: OK")
    except Exception as e:
        print(f"Warm start failed: {e}")


if __name__ == "__main__":
    main()
