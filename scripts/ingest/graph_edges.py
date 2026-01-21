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
import time
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

__all__ = [
    # Constants
    "GRAPH_COLLECTION_SUFFIX",
    "EDGE_TYPE_CALLS",
    "EDGE_TYPE_IMPORTS",
    "EDGE_TYPE_INHERITS_FROM",
    "GRAPH_INDEX_FIELDS",
    # Utility functions
    "normalize_path",
    "edge_id",
    "get_graph_collection_name",
    # Collection management
    "ensure_graph_collection",
    # Edge extraction
    "extract_call_edges",
    "extract_import_edges",
    "extract_inheritance_edges",
    # Edge operations
    "upsert_edges",
    "delete_edges_by_path",
    # Query functions
    "get_callers",
    "get_callees",
    "get_importers",
]


def normalize_path(path: str) -> str:
    """Normalize path for consistent edge matching.

    Ensures paths are comparable across different call sites.
    """
    if not path:
        return ""
    # Normalize the path (resolve .., remove double slashes)
    normalized = os.path.normpath(path)
    # Ensure consistent forward slashes on all platforms
    return normalized.replace("\\", "/")


# Backward compatibility alias
_normalize_path = normalize_path

# Graph collection suffix
GRAPH_COLLECTION_SUFFIX = "_graph"

# Edge types - use string values for backward compatibility
# (EdgeType enum defined in scripts.graph_backends.base for type-safe usage)
EDGE_TYPE_CALLS = "calls"
EDGE_TYPE_IMPORTS = "imports"
EDGE_TYPE_INHERITS_FROM = "inherits_from"

# Payload index fields for fast lookups
GRAPH_INDEX_FIELDS = (
    "caller_symbol",
    "callee_symbol",
    "caller_path",
    "callee_path",  # For "find by target file" queries
    "edge_type",
    "repo",
)

# Track ensured graph collections
_ENSURED_GRAPH_COLLECTIONS: set[str] = set()
_GRAPH_VECTOR_MODE: dict[str, str] = {}

# Track collections known to not exist (avoid repeated 404s in benchmarks)
# Now uses TTL-based expiry to handle transient 404s
_MISSING_COLLECTIONS_TTL_SECONDS = int(os.environ.get("GRAPH_MISSING_TTL", "300"))  # 5 minutes default
_MISSING_GRAPH_COLLECTIONS: Dict[str, float] = {}  # collection_name -> expiry_timestamp


def _is_collection_missing(collection: str) -> bool:
    """Check if a collection is cached as missing (with TTL expiry)."""
    expiry = _MISSING_GRAPH_COLLECTIONS.get(collection)
    if expiry is None:
        return False
    if time.time() > expiry:
        # Entry expired, remove it
        _MISSING_GRAPH_COLLECTIONS.pop(collection, None)
        return False
    return True


def _mark_collection_missing(collection: str) -> None:
    """Mark a collection as missing with TTL expiry."""
    _MISSING_GRAPH_COLLECTIONS[collection] = time.time() + _MISSING_COLLECTIONS_TTL_SECONDS


def _clear_collection_missing(collection: str) -> None:
    """Remove a collection from the missing cache."""
    _MISSING_GRAPH_COLLECTIONS.pop(collection, None)


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
        # Clear from missing cache if it was previously marked missing
        _clear_collection_missing(graph_coll)
        return graph_coll
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")  # Collection doesn't exist, create it

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
        # Clear from missing cache now that it's confirmed to exist
        _clear_collection_missing(graph_coll)
        return graph_coll

    except Exception as e:
        if "already exists" in str(e).lower():
            _ENSURED_GRAPH_COLLECTIONS.add(graph_coll)
            _clear_collection_missing(graph_coll)
            return graph_coll
        else:
            logger.error(f"Failed to create graph collection {graph_coll}: {e}")
            return None  # Explicit failure


def edge_id(
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
    norm_path = normalize_path(caller_path)
    key = f"{edge_type}:{repo}:{caller_symbol}:{callee_symbol}:{norm_path}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


# Backward compatibility alias
_edge_id = edge_id


def _resolve_callee_path(callee: str, repo: str, language: Optional[str] = None) -> str:
    """Resolve a callee symbol to its definition file path.

    Resolution order:
    1. Check if builtin for the given language (via tree-sitter based detection)
    2. Try symbol resolver cache (cross-file resolution via indexed symbols)
    3. Fallback to <external>

    Args:
        callee: The callee symbol name
        repo: Repository name
        language: Programming language for builtin detection (None = skip language-specific checks)
    """
    # Use tree-sitter based builtin detection (supports 16+ languages)
    if language:
        try:
            from scripts.ast_analyzer import is_builtin

            # Extract base name for detection (handles qualified names)
            base_name = callee.split(".")[-1] if "." in callee else callee
            base_name = base_name.split("::")[-1] if "::" in base_name else base_name

            if is_builtin(base_name, language):
                return f"<builtin>/{base_name}"
        except ImportError:
            pass  # Fallback if AST analyzer unavailable

    # Try cross-file resolution via symbol resolver (language-agnostic)
    try:
        from scripts.graph_backends.symbol_resolver import get_symbol_resolver
        collection = os.environ.get("COLLECTION_NAME") or os.environ.get("CURRENT_COLLECTION")
        if collection:
            resolver = get_symbol_resolver(collection)
            resolved = resolver.resolve_symbol(callee, repo)
            if resolved:
                return resolved
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Unresolved = external (no hardcoded stdlib lists)
    return f"<external>/{callee}"


def _resolve_import_path(imported: str, repo: str) -> str:
    """Resolve an import to its source file path.

    Resolution order:
    1. Try symbol resolver cache (cross-file resolution)
    2. Fallback to <external>

    Args:
        imported: The imported module/symbol name
        repo: Repository name
    """
    # Try cross-file resolution via symbol resolver
    try:
        from scripts.graph_backends.symbol_resolver import get_symbol_resolver
        collection = os.environ.get("COLLECTION_NAME") or os.environ.get("CURRENT_COLLECTION")
        if collection:
            resolver = get_symbol_resolver(collection)
            resolved = resolver.resolve_import(imported, repo)
            if resolved:
                return resolved
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Unresolved = external (no hardcoded stdlib lists)
    return f"<external>/{imported}"


def extract_call_edges(
    symbol_path: str,
    calls: List[str],
    path: str,
    repo: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    language: Optional[str] = None,
    caller_point_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Extract call edge documents from a chunk's calls list.

    Args:
        symbol_path: The caller symbol (e.g., "MyClass.my_method")
        calls: List of called symbols
        path: File path of the caller
        repo: Repository name
        start_line: Optional start line of caller function
        end_line: Optional end line of caller function
        language: Programming language of the caller
        caller_point_id: ID of the source chunk in the main collection

    Returns:
        List of edge documents ready for upsert
    """
    if not symbol_path or not calls:
        return []

    norm_path = _normalize_path(path)
    edges = []

    for callee in calls:
        if not callee:
            continue

        # Resolve callee to its definition file path (language-aware for stdlib/builtin detection)
        callee_path = _resolve_callee_path(callee, repo, language=language)

        edge_id = _edge_id(symbol_path, callee, norm_path, EDGE_TYPE_CALLS, repo)
        payload = {
            "caller_symbol": symbol_path,
            "callee_symbol": callee,
            "caller_path": norm_path,
            "callee_path": callee_path,
            "edge_type": EDGE_TYPE_CALLS,
            "repo": repo,
        }
        if start_line is not None:
            payload["start_line"] = start_line
        if end_line is not None:
            payload["end_line"] = end_line
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

    norm_path = _normalize_path(path)
    caller = symbol_path or norm_path
    edges = []

    for imported in imports:
        if not imported:
            continue

        # Resolve import to its source file path
        callee_path = _resolve_import_path(imported, repo)

        edge_id = _edge_id(caller, imported, norm_path, EDGE_TYPE_IMPORTS, repo)
        payload = {
            "caller_symbol": caller,
            "callee_symbol": imported,
            "caller_path": norm_path,
            "callee_path": callee_path,
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


def extract_inheritance_edges(
    class_name: str,
    base_classes: List[str],
    path: str,
    repo: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    language: Optional[str] = None,
    caller_point_id: Optional[str] = None,
    import_paths: Optional[Dict[str, str]] = None,
    collection: Optional[str] = None,
    qdrant_client: Optional["QdrantClient"] = None,
) -> List[Dict[str, Any]]:
    """Extract inheritance edge documents from class definition.

    Args:
        class_name: The class name
        base_classes: List of base class names
        path: File path of the class definition
        repo: Repository name
        start_line: Starting line of the class definition
        end_line: Ending line of the class definition
        language: Programming language
        caller_point_id: ID of the source chunk in the main collection
        import_paths: Mapping of local names to fully qualified paths
        collection: Collection name (for cross-file resolution)
        qdrant_client: Qdrant client (for cross-file resolution)

    Returns:
        List of edge documents ready for upsert
    """
    if not base_classes:
        return []

    norm_path = _normalize_path(path)
    import_paths = import_paths or {}
    edges = []

    for base in base_classes:
        if not base:
            continue

        # Resolve base class name through import_paths if available
        resolved_base = import_paths.get(base, base)
        # For inheritance, callee_path is typically unresolved unless we find the definition
        callee_path = f"<unresolved>/{resolved_base}"

        eid = _edge_id(class_name, resolved_base, norm_path, EDGE_TYPE_INHERITS_FROM, repo)
        payload = {
            "caller_symbol": class_name,
            "callee_symbol": resolved_base,
            "caller_path": norm_path,
            "callee_path": callee_path,
            "edge_type": EDGE_TYPE_INHERITS_FROM,
            "repo": repo,
        }
        if start_line is not None:
            payload["start_line"] = start_line
        if end_line is not None:
            payload["end_line"] = end_line
        if language:
            payload["language"] = language
        if caller_point_id:
            payload["caller_point_id"] = caller_point_id
        edges.append({
            "id": eid,
            "payload": payload,
        })
    return edges


def upsert_edges(
    client: "QdrantClient",
    graph_collection: str,
    edges: List[Dict[str, Any]],
    batch_size: int = 100,
    max_retries: int = 3,
) -> int:
    """Upsert edge documents to the graph collection.

    Args:
        client: Qdrant client
        graph_collection: Graph collection name
        edges: List of edge documents with 'id' and 'payload' keys
        batch_size: Batch size for upserts
        max_retries: Maximum retries per batch on transient failures

    Returns:
        Number of edges upserted
    """
    import time
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

        # Retry loop with exponential backoff for transient failures
        for attempt in range(max_retries):
            try:
                client.upsert(collection_name=graph_collection, points=points, wait=True)
                total += len(points)
                break  # Success - exit retry loop
            except Exception as e:
                is_last_attempt = attempt == max_retries - 1
                error_str = str(e).lower()

                # Check if error is retryable (timeout, connection, etc.)
                is_retryable = any(err in error_str for err in [
                    "timeout", "connection", "unavailable", "reset", "broken pipe"
                ])

                if is_retryable and not is_last_attempt:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(f"Retrying edge upsert (attempt {attempt + 1}/{max_retries}) after {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to upsert edges batch after {attempt + 1} attempts: {e}")
                    break  # Non-retryable error or max retries reached

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

    # Skip if we already know this collection doesn't exist (with TTL expiry)
    if _is_collection_missing(graph_collection):
        return []

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
        # Silently return empty for "collection doesn't exist" errors (common in benchmarks)
        err_str = str(e).lower()
        if "404" in err_str or "doesn't exist" in err_str or "not found" in err_str:
            _mark_collection_missing(graph_collection)
            return []
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

    # Skip if we already know this collection doesn't exist (with TTL expiry)
    if _is_collection_missing(graph_collection):
        return []

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
        # Silently return empty for "collection doesn't exist" errors (common in benchmarks)
        err_str = str(e).lower()
        if "404" in err_str or "doesn't exist" in err_str or "not found" in err_str:
            _mark_collection_missing(graph_collection)
            return []
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

    # Skip if we already know this collection doesn't exist (with TTL expiry)
    if _is_collection_missing(graph_collection):
        return []

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
        # Silently return empty for "collection doesn't exist" errors (common in benchmarks)
        err_str = str(e).lower()
        if "404" in err_str or "doesn't exist" in err_str or "not found" in err_str:
            _mark_collection_missing(graph_collection)
            return []
        logger.error(f"Failed to get importers for {module}: {e}")
        return []
