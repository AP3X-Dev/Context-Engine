#!/usr/bin/env python3
import os
import hashlib
from pathlib import Path
from typing import Tuple

from qdrant_client import QdrantClient, models

COLLECTION = os.environ.get("COLLECTION_NAME", "codebase")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
API_KEY = os.environ.get("QDRANT_API_KEY")
ROOT = Path(os.environ.get("PRUNE_ROOT", ".")).resolve()
GRAPH_COLLECTION_SUFFIX = "_graph"
_NEO4J_GRAPH_ENABLED = os.environ.get("NEO4J_GRAPH", "").strip().lower() in {
    "1", "true", "yes", "on"
}


def sha1_file(path: Path) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    return hashlib.sha1(data).hexdigest()


def delete_by_path(client: QdrantClient, path_str: str) -> int:
    flt = models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.path", match=models.MatchValue(value=path_str)
            )
        ]
    )
    try:
        res = client.delete(
            collection_name=COLLECTION,
            points_selector=models.FilterSelector(filter=flt),
        )
        return 1
    except Exception:
        return 0


def delete_graph_edges_by_path(client: QdrantClient, path_str: str, repo: str | None = None) -> int:
    """Delete graph edges for a specific file path.

    Deletes edges where the file appears as caller_path.
    Note: Graph edges only store caller_path (not callee_path) since callees
    are identified by symbol name, not file path.
    Returns the actual number of deleted points, or 0 if collection doesn't exist.
    """
    import logging
    logger = logging.getLogger(__name__)

    if _NEO4J_GRAPH_ENABLED:
        try:
            from scripts.graph_backends import get_graph_backend
            backend = get_graph_backend()
            if backend.backend_type == "neo4j":
                return backend.delete_edges_by_path(COLLECTION, path_str, repo=repo)
        except Exception:
            pass

    graph_coll = COLLECTION + GRAPH_COLLECTION_SUFFIX

    # Check if graph collection exists
    try:
        collections = client.get_collections()
        coll_names = {c.name for c in collections.collections}
        if graph_coll not in coll_names:
            return 0
    except Exception as e:
        # Log the error but return 0 (collection truly doesn't exist)
        logger.debug(f"Failed to check graph collection existence: {e}")
        return 0

    # Filter for edges where path appears as caller
    # Note: edges only have caller_path field (callee is identified by symbol, not path)
    flt = models.Filter(
        must=[
            models.FieldCondition(
                key="caller_path", match=models.MatchValue(value=path_str)
            ),
        ]
    )

    try:
        response = client.delete(
            collection_name=graph_coll,
            points_selector=models.FilterSelector(filter=flt),
        )
        # Extract actual deleted count from response
        deleted_count = None

        result_attr = getattr(response, "result", None)
        if isinstance(result_attr, dict):
            deleted_value = result_attr.get("deleted")
            if isinstance(deleted_value, int):
                deleted_count = deleted_value

        if deleted_count is None:
            deleted_attr = getattr(response, "deleted", None)
            if isinstance(deleted_attr, int):
                deleted_count = deleted_attr

        if deleted_count is None:
            points_attr = getattr(response, "points", None)
            try:
                if points_attr is not None:
                    deleted_count = len(points_attr)
            except TypeError:
                pass

        if deleted_count is None:
            deleted_count = 1

        return deleted_count
    except Exception as e:
        # Check if this is a "collection not found" error
        error_msg = str(e).lower()
        if "not found" in error_msg or "collection" in error_msg:
            logger.debug(f"Graph collection not found: {e}")
            return 0
        # For other errors, log and re-raise
        logger.error(f"Failed to delete graph edges for path {path_str}: {e}")
        raise


def main():
    client = QdrantClient(url=QDRANT_URL, api_key=API_KEY or None)

    seen = set()
    removed_missing = 0
    removed_mismatch = 0
    removed_graph_edges = 0

    next_page = None
    while True:
        points, next_page = client.scroll(
            collection_name=COLLECTION,
            with_payload=True,
            limit=256,
            offset=next_page,
            scroll_filter=None,
        )
        if not points:
            break
        for p in points:
            md = (p.payload or {}).get("metadata") or {}
            path_str = md.get("path")
            file_hash = md.get("file_hash")
            if not path_str or path_str in seen:
                continue
            seen.add(path_str)
            abs_path = (
                ROOT / Path(path_str).relative_to("/work")
                if path_str.startswith("/work/")
                else ROOT / path_str
            )
            if not abs_path.exists():
                removed_missing += delete_by_path(client, path_str)
                removed_graph_edges += delete_graph_edges_by_path(client, path_str, repo=md.get("repo"))
                print(f"[prune] removed missing file points: {path_str}")
                continue
            current_hash = sha1_file(abs_path)
            if file_hash and current_hash and current_hash != file_hash:
                removed_mismatch += delete_by_path(client, path_str)
                removed_graph_edges += delete_graph_edges_by_path(client, path_str, repo=md.get("repo"))
                print(f"[prune] removed outdated points (hash mismatch): {path_str}")

        if next_page is None:
            break

    print(
        f"Prune complete. removed_missing={removed_missing}, removed_mismatch={removed_mismatch}, removed_graph_edges={removed_graph_edges}"
    )


if __name__ == "__main__":
    main()
