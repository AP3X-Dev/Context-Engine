#!/usr/bin/env python3
"""
ingest/graph_edges.py - Pre-computed graph edges for fast symbol graph queries.

This module manages a dedicated graph collection with edge documents:
- {caller_symbol, callee_symbol, caller_path, edge_type, repo}

Benefits:
- Fast indexed lookups (no MatchAny on large arrays)
- Bidirectional queries: "who calls X" and "what does X call"
- Cross-repo dependency analysis for multi-repo users
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)


def _normalize_path(path: str) -> str:
    """Normalize path for consistent edge matching.

    Ensures paths are comparable across different call sites.
    """
    if not path:
        return ""
    # Normalize the path (resolve .., remove double slashes)
    normalized = os.path.normpath(path)
    # Ensure consistent forward slashes on all platforms
    return normalized.replace("\\", "/")

# Graph collection suffix
GRAPH_COLLECTION_SUFFIX = "_graph"

# Edge types
EDGE_TYPE_CALLS = "calls"
EDGE_TYPE_IMPORTS = "imports"

# Payload index fields for fast lookups
GRAPH_INDEX_FIELDS = (
    "caller_symbol",
    "callee_symbol", 
    "caller_path",
    "edge_type",
    "repo",
)

# Track ensured graph collections
_ENSURED_GRAPH_COLLECTIONS: set[str] = set()
_GRAPH_VECTOR_MODE: dict[str, str] = {}

# Fallback vector schema for Qdrant deployments that don't support vector-less collections.
_EDGE_VECTOR_NAME = "_edge"
_EDGE_VECTOR_VALUE = [0.0]


def _edge_vector_for_upsert(graph_collection: str) -> dict:
    mode = _GRAPH_VECTOR_MODE.get(graph_collection)
    if mode == "named":
        return {_EDGE_VECTOR_NAME: _EDGE_VECTOR_VALUE}
    return {}


def get_graph_collection_name(base_collection: str) -> str:
    """Get the graph collection name for a base collection."""
    return f"{base_collection}{GRAPH_COLLECTION_SUFFIX}"


def ensure_graph_collection(client: "QdrantClient", base_collection: str) -> Optional[str]:
    """Create the graph collection if it doesn't exist (payload-only, no vectors).

    Returns the graph collection name, or None on failure.
    """
    from qdrant_client import models as qmodels

    graph_coll = get_graph_collection_name(base_collection)

    if graph_coll in _ENSURED_GRAPH_COLLECTIONS:
        return graph_coll

    def _detect_vector_mode(info: Any) -> str:
        try:
            vectors = getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None)
            if isinstance(vectors, dict):
                return "none" if not vectors else "named"
            return "none" if vectors is None else "named"
        except Exception:
            return "named"

    try:
        # Check if collection exists
        info = client.get_collection(graph_coll)
        _GRAPH_VECTOR_MODE[graph_coll] = _detect_vector_mode(info)
        _ENSURED_GRAPH_COLLECTIONS.add(graph_coll)
        return graph_coll
    except Exception:
        pass  # Collection doesn't exist, create it

    try:
        # Prefer a vector-less collection if supported; fallback to a tiny dummy vector schema.
        try:
            client.create_collection(
                collection_name=graph_coll,
                vectors_config={},  # No vectors (server permitting)
                on_disk_payload=True,
            )
            _GRAPH_VECTOR_MODE[graph_coll] = "none"
        except Exception:
            client.create_collection(
                collection_name=graph_coll,
                vectors_config={
                    _EDGE_VECTOR_NAME: qmodels.VectorParams(
                        size=1,
                        distance=qmodels.Distance.COSINE,
                    )
                },
                on_disk_payload=True,
            )
            _GRAPH_VECTOR_MODE[graph_coll] = "named"
        logger.info(f"Created graph collection: {graph_coll}")

        # Create payload indexes for fast lookups (including language)
        index_fields = list(GRAPH_INDEX_FIELDS) + ["language"]
        for field in index_fields:
            try:
                client.create_payload_index(
                    collection_name=graph_coll,
                    field_name=field,
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.warning(f"Failed to create index on {field}: {e}")

        _ENSURED_GRAPH_COLLECTIONS.add(graph_coll)
        return graph_coll

    except Exception as e:
        if "already exists" in str(e).lower():
            _ENSURED_GRAPH_COLLECTIONS.add(graph_coll)
            return graph_coll
        else:
            logger.error(f"Failed to create graph collection {graph_coll}: {e}")
            return None  # Explicit failure


def _edge_id(
    caller_symbol: str,
    callee_symbol: str,
    caller_path: str,
    edge_type: str,
    repo: str,
) -> str:
    """Generate deterministic edge ID from edge components.

    Uses full 32-char hex (128 bits) to avoid collision risk at scale.
    Path is normalized before hashing for consistency.
    """
    # Normalize path and include repo to avoid cross-repo collisions
    norm_path = _normalize_path(caller_path)
    key = f"{edge_type}:{repo}:{caller_symbol}:{callee_symbol}:{norm_path}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]  # 128-bit, not 64-bit


def extract_call_edges(
    symbol_path: str,
    calls: List[str],
    path: str,
    repo: str,
    start_line: Optional[int] = None,
    language: Optional[str] = None,
    caller_point_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract call edge documents from a chunk's calls list.

    Args:
        symbol_path: The caller symbol (e.g., "MyClass.my_method")
        calls: List of called symbols
        path: File path of the caller
        repo: Repository name
        start_line: Optional line number
        language: Programming language of the caller
        caller_point_id: ID of the source chunk in the main collection

    Returns:
        List of edge documents ready for upsert
    """
    if not symbol_path or not calls:
        return []

    # Normalize path for consistent matching
    norm_path = _normalize_path(path)

    edges = []
    for callee in calls:
        if not callee:
            continue
        edge_id = _edge_id(symbol_path, callee, norm_path, EDGE_TYPE_CALLS, repo)
        payload = {
            "caller_symbol": symbol_path,
            "callee_symbol": callee,
            "caller_path": norm_path,
            "edge_type": EDGE_TYPE_CALLS,
            "repo": repo,
        }
        # Only include start_line if it has a value
        if start_line is not None:
            payload["start_line"] = start_line
        if language:
            payload["language"] = language
        if caller_point_id:
            payload["caller_point_id"] = caller_point_id
        edges.append({
            "id": edge_id,
            "payload": payload,
        })
    return edges


def extract_import_edges(
    symbol_path: str,
    imports: List[str],
    path: str,
    repo: str,
    language: Optional[str] = None,
    caller_point_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract import edge documents from a chunk's imports list.

    Args:
        symbol_path: The importer symbol (can be file-level)
        imports: List of imported modules/symbols
        path: File path of the importer
        repo: Repository name
        language: Programming language of the importer
        caller_point_id: ID of the source chunk in the main collection

    Returns:
        List of edge documents ready for upsert
    """
    if not imports:
        return []

    # Normalize path for consistent matching
    norm_path = _normalize_path(path)

    # For imports, use file path as caller if no symbol
    caller = symbol_path or norm_path

    edges = []
    for imported in imports:
        if not imported:
            continue
        edge_id = _edge_id(caller, imported, norm_path, EDGE_TYPE_IMPORTS, repo)
        payload = {
            "caller_symbol": caller,
            "callee_symbol": imported,
            "caller_path": norm_path,
            "edge_type": EDGE_TYPE_IMPORTS,
            "repo": repo,
        }
        if language:
            payload["language"] = language
        if caller_point_id:
            payload["caller_point_id"] = caller_point_id
        edges.append({
            "id": edge_id,
            "payload": payload,
        })
    return edges


def upsert_edges(
    client: "QdrantClient",
    graph_collection: str,
    edges: List[Dict[str, Any]],
    batch_size: int = 100,
) -> int:
    """Upsert edge documents to the graph collection.

    Args:
        client: Qdrant client
        graph_collection: Graph collection name
        edges: List of edge documents with 'id' and 'payload' keys
        batch_size: Batch size for upserts

    Returns:
        Number of edges upserted
    """
    from qdrant_client import models as qmodels

    if not edges:
        return 0

    total = 0
    for i in range(0, len(edges), batch_size):
        batch = edges[i:i + batch_size]
        points = [
            qmodels.PointStruct(
                id=edge["id"],
                vector=_edge_vector_for_upsert(graph_collection),
                payload=edge["payload"],
            )
            for edge in batch
        ]
        try:
            client.upsert(collection_name=graph_collection, points=points, wait=True)
            total += len(points)
        except Exception as e:
            logger.error(f"Failed to upsert edges batch: {e}")

    return total


def delete_edges_by_path(
    client: "QdrantClient",
    graph_collection: str,
    path: str,
    repo: Optional[str] = None,
) -> int:
    """Delete all edges from a specific file path.

    Used when a file is deleted or being re-indexed.

    WARNING: If repo is not specified, edges for this path are deleted across
    ALL repositories in the collection. This is usually not what you want in
    a multi-repo setup.

    Args:
        client: Qdrant client
        graph_collection: Graph collection name
        path: File path to delete edges for
        repo: Repo filter (strongly recommended for multi-repo collections)

    Returns:
        1 if delete succeeded, 0 otherwise
    """
    from qdrant_client import models as qmodels

    # Normalize path to match how edges were stored
    norm_path = _normalize_path(path)

    # Warn if repo not specified (dangerous in multi-repo)
    if not repo:
        logger.warning(
            f"delete_edges_by_path called without repo filter for path={norm_path}. "
            "This will delete edges across ALL repositories."
        )

    must = [
        qmodels.FieldCondition(
            key="caller_path",
            match=qmodels.MatchValue(value=norm_path),
        )
    ]
    if repo:
        must.append(
            qmodels.FieldCondition(
                key="repo",
                match=qmodels.MatchValue(value=repo),
            )
        )

    try:
        result = client.delete(
            collection_name=graph_collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(must=must)
            ),
            wait=True,  # Ensure delete is durable
        )
        # Qdrant delete returns UpdateResult with operation_id, not deleted_count
        # Return 1 if delete succeeded (operation completed), 0 otherwise
        if result:
            status = getattr(result, "status", None)
            if status and str(status).lower() in ("completed", "acknowledged"):
                return 1
        return 0
    except Exception as e:
        logger.error(f"Failed to delete edges for {norm_path}: {e}")
        return 0


def get_callers(
    client: "QdrantClient",
    graph_collection: str,
    symbol: str,
    repo: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Find all callers of a symbol (fast indexed query).

    Args:
        client: Qdrant client
        graph_collection: Graph collection name
        symbol: The callee symbol to find callers for
        repo: Optional repo filter (None = all repos)
        limit: Maximum results

    Returns:
        List of edge payloads
    """
    from qdrant_client import models as qmodels

    must = [
        qmodels.FieldCondition(
            key="callee_symbol",
            match=qmodels.MatchValue(value=symbol),
        ),
        qmodels.FieldCondition(
            key="edge_type",
            match=qmodels.MatchValue(value=EDGE_TYPE_CALLS),
        ),
    ]
    if repo and repo != "*":
        must.append(
            qmodels.FieldCondition(
                key="repo",
                match=qmodels.MatchValue(value=repo),
            )
        )

    try:
        result, _ = client.scroll(
            collection_name=graph_collection,
            scroll_filter=qmodels.Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [p.payload for p in result]
    except Exception as e:
        logger.error(f"Failed to get callers for {symbol}: {e}")
        return []


def get_callees(
    client: "QdrantClient",
    graph_collection: str,
    symbol: str,
    repo: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Find all symbols called by a symbol (fast indexed query).

    Args:
        client: Qdrant client
        graph_collection: Graph collection name
        symbol: The caller symbol to find callees for
        repo: Optional repo filter (None = all repos)
        limit: Maximum results

    Returns:
        List of edge payloads
    """
    from qdrant_client import models as qmodels

    must = [
        qmodels.FieldCondition(
            key="caller_symbol",
            match=qmodels.MatchValue(value=symbol),
        ),
        qmodels.FieldCondition(
            key="edge_type",
            match=qmodels.MatchValue(value=EDGE_TYPE_CALLS),
        ),
    ]
    if repo and repo != "*":
        must.append(
            qmodels.FieldCondition(
                key="repo",
                match=qmodels.MatchValue(value=repo),
            )
        )

    try:
        result, _ = client.scroll(
            collection_name=graph_collection,
            scroll_filter=qmodels.Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [p.payload for p in result]
    except Exception as e:
        logger.error(f"Failed to get callees for {symbol}: {e}")
        return []


def get_importers(
    client: "QdrantClient",
    graph_collection: str,
    module: str,
    repo: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Find all files that import a module (fast indexed query).

    Args:
        client: Qdrant client
        graph_collection: Graph collection name
        module: The module name to find importers for
        repo: Optional repo filter (None = all repos)
        limit: Maximum results

    Returns:
        List of edge payloads
    """
    from qdrant_client import models as qmodels

    must = [
        qmodels.FieldCondition(
            key="callee_symbol",
            match=qmodels.MatchValue(value=module),
        ),
        qmodels.FieldCondition(
            key="edge_type",
            match=qmodels.MatchValue(value=EDGE_TYPE_IMPORTS),
        ),
    ]
    if repo and repo != "*":
        must.append(
            qmodels.FieldCondition(
                key="repo",
                match=qmodels.MatchValue(value=repo),
            )
        )

    try:
        result, _ = client.scroll(
            collection_name=graph_collection,
            scroll_filter=qmodels.Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [p.payload for p in result]
    except Exception as e:
        logger.error(f"Failed to get importers for {module}: {e}")
        return []
