# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
# ---------------------------------------------------------------------------
# CRITICAL: OpenLit must be initialized BEFORE any qdrant_client imports
# to properly instrument vector DB calls.
# ---------------------------------------------------------------------------
import logging
import os
import sys as _sys

# Ensure repo roots are importable so 'scripts' resolves inside container

logger = logging.getLogger(__name__)
_roots_env = os.environ.get("WORK_ROOTS", "")
_roots = [p.strip() for p in _roots_env.split(",") if p.strip()] or ["/work", "/app"]
for _root in _roots:
    if _root and _root not in _sys.path:
        _sys.path.insert(0, _root)

# Now import OpenLit init (before any other scripts imports that may use qdrant)
try:
    from scripts import openlit_init  # noqa: F401 - triggers early instrumentation
except ImportError:
    pass  # OpenLit not available

import json
import threading
from datetime import datetime
from typing import Any, Dict, Optional, List, Union
from weakref import WeakKeyDictionary


# FastMCP server and request Context (ctx) for per-connection state
try:
    from mcp.server.fastmcp import FastMCP, Context  # type: ignore
    from mcp.server.transport_security import TransportSecuritySettings  # type: ignore
except Exception:
    from mcp.server.fastmcp import FastMCP  # type: ignore
    Context = Any  # type: ignore
    TransportSecuritySettings = None  # type: ignore

from scripts.mcp_auth import (
    require_auth_session as _require_auth_session,
    require_collection_access as _require_collection_access,
    AUTH_HEADER_TOKEN as _AUTH_HEADER_TOKEN,
)

from qdrant_client import QdrantClient, models

# Import connection pooling for proper resource management
try:
    from scripts.qdrant_client_manager import (
        get_qdrant_client,
        return_qdrant_client,
        pooled_qdrant_client,
    )
    _POOL_AVAILABLE = True
except ImportError:
    _POOL_AVAILABLE = False

# Env
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
DEFAULT_COLLECTION = (
    os.environ.get("DEFAULT_COLLECTION")
    or os.environ.get("COLLECTION_NAME")
    or "codebase"
)
LEX_VECTOR_NAME = os.environ.get("LEX_VECTOR_NAME", "lex")
LEX_VECTOR_DIM = int(os.environ.get("LEX_VECTOR_DIM", "4096") or 4096)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")
MEMORY_FIND_LIMIT_DEFAULT = int(os.environ.get("MEMORY_FIND_LIMIT_DEFAULT", "10") or 10)

# Minimal embedding via fastembed (CPU)

# Single-process embedding model cache (avoid re-initializing fastembed on each call)

# Use shared utils for consistent vector naming and lexical hashing
from scripts.utils import sanitize_vector_name as _sanitize_vector_name
from scripts.utils import lex_hash_vector_text as _lex_hash_vector_text

# Remote embedding support
try:
    from scripts.embedder import RemoteEmbeddingStub
    from scripts.ingest.qdrant import embed_batch as _embed_batch_remote
    _REMOTE_EMBED_AVAILABLE = True
except ImportError:
    RemoteEmbeddingStub = None  # type: ignore
    _embed_batch_remote = None  # type: ignore
    _REMOTE_EMBED_AVAILABLE = False


def _embed_text(model, text: str) -> list:
    """Embed text using either local model or remote service."""
    is_remote_stub = (
        RemoteEmbeddingStub is not None 
        and isinstance(model, RemoteEmbeddingStub)
    )
    
    if is_remote_stub and _REMOTE_EMBED_AVAILABLE and _embed_batch_remote is not None:
        vecs = _embed_batch_remote(model, [text])
        return vecs[0] if isinstance(vecs[0], list) else vecs[0].tolist()
    else:
        return next(model.embed([text])).tolist()


VECTOR_NAME = _sanitize_vector_name(EMBEDDING_MODEL)

# I/O-safety knobs for memory server behavior
# These env vars allow tuning startup latency vs. first-call latency, especially important
# on slow storage backends (e.g., Ceph + HDD). See comments below for rationale.
MEMORY_ENSURE_ON_START = str(os.environ.get("MEMORY_ENSURE_ON_START", "1")).strip().lower() in {"1", "true", "yes", "on"}
MEMORY_COLD_SKIP_DENSE = str(os.environ.get("MEMORY_COLD_SKIP_DENSE", "0")).strip().lower() in {"1", "true", "yes", "on"}
MEMORY_PROBE_EMBED_DIM = str(os.environ.get("MEMORY_PROBE_EMBED_DIM", "1")).strip().lower() in {"1", "true", "yes", "on"}
try:
    MEMORY_VECTOR_DIM = int(os.environ.get("MEMORY_VECTOR_DIM") or os.environ.get("EMBED_DIM") or "768")
except Exception:
    MEMORY_VECTOR_DIM = 768

# ---------------------------------------------------------------------------
# Embedding Model Management
# ---------------------------------------------------------------------------
# Use the centralized embedder from scripts.embedder for consistent caching.
# This eliminates duplicate model loading and ensures consistent behavior.

# Reference to the centralized embedder for cold-skip detection
try:
    from scripts.embedder import get_embedding_model as _centralized_get_embedding_model
    from scripts.embedder import is_model_cached as _is_model_cached
    _EMBEDDER_AVAILABLE = True
except ImportError:
    _EMBEDDER_AVAILABLE = False
    def _is_model_cached(model_name: str = "") -> bool:  # type: ignore[misc]
        return False  # Fallback: assume not cached

def _get_embedding_model():
    """Get the embedding model using the centralized embedder.

    Uses scripts.embedder.get_embedding_model() which provides:
    - Thread-safe lazy loading with double-checked locking
    - Qwen3 model support with feature flags
    - Automatic cache invalidation on corrupted downloads
    """
    if _EMBEDDER_AVAILABLE:
        return _centralized_get_embedding_model(EMBEDDING_MODEL)

    # Fallback for environments without centralized embedder (rare)
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=EMBEDDING_MODEL)

# Track ensured collections to reduce redundant ensure calls.
# RATIONALE: Avoid repeated Qdrant network calls for the same collection.
_ENSURED = set()

def _ensure_once(name: str) -> bool:
    """Ensure collection exists, but only once per process (cached result)."""
    if name in _ENSURED:
        return True
    try:
        _ensure_collection(name)
        _ENSURED.add(name)
        return True
    except Exception:
        return False

# Disable DNS rebinding protection - breaks Docker internal networking (Host: mcp:8000)
TOOLS_METADATA: Dict[str, Dict] = {
    "memory_store": {
        "name": "memory_store",
        "category": "memory",
        "primary_use": "Store knowledge for later retrieval",
        "choose_when": [
            "Storing team decisions/notes",
            "Documenting conventions",
            "Building institutional memory",
        ],
        "choose_instead": {},
        "parameters": {
            "essential": ["information"],
            "common": ["metadata"],
            "advanced": ["collection", "session"],
        },
        "returns": {"ok": "bool", "id": "str", "message": "str"},
        "related_tools": ["memory_find", "context_search"],
        "performance": {
            "typical_latency_ms": (50, 500),
            "requires_index": False,
            "requires_decoder": False,
        },
    },
    "memory_find": {
        "name": "memory_find",
        "category": "memory",
        "primary_use": "Retrieve stored memories by similarity",
        "choose_when": [
            "Looking for stored notes/decisions",
            "Recalling team knowledge",
        ],
        "choose_instead": {"context_search": "Want code + memories together"},
        "parameters": {
            "essential": ["query"],
            "common": ["limit", "kind", "topic", "tags"],
            "advanced": ["priority_min", "collection"],
        },
        "returns": {
            "ok": "bool",
            "results": "list[{id, information, metadata, score}]",
            "total": "int",
        },
        "related_tools": ["memory_store", "context_search"],
        "performance": {
            "typical_latency_ms": (50, 300),
            "requires_index": False,
            "requires_decoder": False,
        },
    },
}

_security_settings = (
    TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if TransportSecuritySettings
    else None
)
mcp = FastMCP(name="memory-server", transport_security=_security_settings)


class _AuthHeaderASGIMiddleware:
    """Pure ASGI middleware that extracts Authorization header into context var."""
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()
            else:
                token = auth_header.strip() if auth_header else ""
            _AUTH_HEADER_TOKEN.set(token)
        return await self.app(scope, receive, send)


def _add_auth_middleware():
    """Wrap FastMCP's ASGI app with auth header extraction middleware."""
    logger.info("Setting up auth header middleware...")
    try:
        if hasattr(mcp, "streamable_http_app"):
            _orig_streamable = mcp.streamable_http_app
            def _patched_streamable(*args, **kwargs):
                app = _orig_streamable(*args, **kwargs)
                logger.info(f"Wrapping streamable_http_app with auth middleware")
                return _AuthHeaderASGIMiddleware(app)
            mcp.streamable_http_app = _patched_streamable
        
        if hasattr(mcp, "sse_app"):
            _orig_sse = mcp.sse_app
            def _patched_sse(*args, **kwargs):
                app = _orig_sse(*args, **kwargs)
                logger.info(f"Wrapping sse_app with auth middleware")
                return _AuthHeaderASGIMiddleware(app)
            mcp.sse_app = _patched_sse
        
        logger.info("Patched FastMCP app factory methods for auth middleware injection")
    except Exception as e:
        logger.warning(f"Failed to patch FastMCP for auth middleware: {e}")


_TOOLS_REGISTRY: list[dict] = []
try:
    _orig_tool = mcp.tool
    def _tool_capture_wrapper(*dargs, **dkwargs):
        orig_deco = _orig_tool(*dargs, **dkwargs)
        def _inner(fn):
            try:
                _TOOLS_REGISTRY.append({
                    "name": dkwargs.get("name") or getattr(fn, "__name__", ""),
                    "description": (getattr(fn, "__doc__", None) or "").strip(),
                })
            except Exception as e:
                logger.debug(f"Suppressed exception: {e}")
            return orig_deco(fn)
        return _inner
    mcp.tool = _tool_capture_wrapper  # type: ignore
except Exception as e:
    logger.debug(f"Suppressed exception: {e}")


def _relax_var_kwarg_defaults() -> None:
    """Allow tools that rely on **kwargs compatibility shims to be invoked without
    callers supplying an explicit 'kwargs' or 'arguments' field.
    
    This patches Pydantic models to add default_factory=dict for kwargs/arguments,
    making them optional instead of required.
    """
    try:
        from pydantic_core import PydanticUndefined as _PydanticUndefined  # type: ignore
    except Exception:  # pragma: no cover - defensive
        class _Sentinel:  # type: ignore
            pass
        _PydanticUndefined = _Sentinel()  # type: ignore

    try:
        tool_manager = getattr(mcp, "_tool_manager", None)
        tools = getattr(tool_manager, "_tools", {}) if tool_manager is not None else {}
    except Exception:
        tools = {}

    for tool in tools.values():
        try:
            model = getattr(tool.fn_metadata, "arg_model", None)
            if model is None:
                continue
            fields = getattr(model, "model_fields", {})
            changed = False
            for key in ("kwargs", "arguments"):
                fld = fields.get(key)
                if fld is None:
                    continue
                default = getattr(fld, "default", None)
                default_factory = getattr(fld, "default_factory", None)
                if default is _PydanticUndefined and default_factory is None:
                    try:
                        fld.default_factory = dict  # type: ignore[attr-defined]
                    except Exception:
                        fld.default_factory = lambda: {}  # type: ignore
                    fld.default = None
                    changed = True
            if changed:
                try:
                    model.model_rebuild(force=True)
                except Exception as e:
                    logger.debug(f"Suppressed exception: {e}")
        except Exception as e:
            logger.debug(f"Suppressed exception, continuing: {e}")
            continue


HOST = os.environ.get("FASTMCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("FASTMCP_PORT", "8000") or 8000)

# Lightweight readiness endpoint on a separate health port (non-MCP), optional
try:
    HEALTH_PORT = int(os.environ.get("FASTMCP_HEALTH_PORT", "18000") or 18000)
except Exception:
    HEALTH_PORT = 18000

# In-memory session defaults (legacy token-based)
_SESSION_LOCK = threading.Lock()
SESSION_DEFAULTS: Dict[str, Dict[str, Any]] = {}
# In-memory per-connection defaults keyed by ctx.session (no token required)
_SESSION_CTX_LOCK = threading.Lock()
SESSION_DEFAULTS_BY_SESSION: "WeakKeyDictionary[Any, Dict[str, Any]]" = WeakKeyDictionary()




def _start_readyz_server():
    try:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    if self.path == "/readyz":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        payload = {"ok": True, "app": "memory-server"}
                        self.wfile.write((json.dumps(payload)).encode("utf-8"))
                    elif self.path == "/tools":
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        enriched = []
                        for t in _TOOLS_REGISTRY:
                            name = t.get("name", "")
                            meta = TOOLS_METADATA.get(name, {})
                            enriched.append({**t, **meta})
                        payload = {"ok": True, "tools": enriched, "metadata": TOOLS_METADATA}
                        self.wfile.write((json.dumps(payload)).encode("utf-8"))
                    else:
                        self.send_response(404)
                        self.end_headers()
                except Exception:
                    try:
                        self.send_response(500)
                        self.end_headers()
                    except Exception as e:
                        logger.debug(f"Suppressed exception: {e}")

            def log_message(self, *args, **kwargs):
                return

        srv = HTTPServer((HOST, HEALTH_PORT), H)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Qdrant Client Management
# ---------------------------------------------------------------------------
# Use connection pooling when available, fallback to creating clients on-demand.
# This prevents socket exhaustion under load and improves connection reuse.

def _get_qdrant_client() -> QdrantClient:
    """Get a Qdrant client from pool or create one."""
    if _POOL_AVAILABLE:
        return get_qdrant_client(
            url=QDRANT_URL,
            api_key=os.environ.get("QDRANT_API_KEY")
        )
    return QdrantClient(url=QDRANT_URL, api_key=os.environ.get("QDRANT_API_KEY"))


def _return_qdrant_client(client: QdrantClient):
    """Return a client to the pool, or close it if pooling unavailable."""
    if client is None:
        return
    if _POOL_AVAILABLE:
        return_qdrant_client(client)
    else:
        # Fallback path: close client to avoid socket leak
        try:
            client.close()
        except Exception as e:
            logger.debug(f"Suppressed exception: {e}")  # Best effort cleanup


# Ensure collection exists with dual vectors


def _ensure_collection(name: str):
    """Create collection if missing.

    Default behavior mirrors the original implementation for PR compatibility:
    - Probe the embedding model to detect the dense vector dimension (MEMORY_PROBE_EMBED_DIM=1)
    - Eager ensure on startup (MEMORY_ENSURE_ON_START=1)

    For slow storage backends (e.g., Ceph + HDD), set the following in your env:
    - MEMORY_PROBE_EMBED_DIM=0  -> skip model probing; use MEMORY_VECTOR_DIM/EMBED_DIM
    - MEMORY_ENSURE_ON_START=0  -> ensure lazily on first tool call
    """
    client = _get_qdrant_client()
    try:
        client.get_collection(name)
        return True
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")
    finally:
        _return_qdrant_client(client)

    # Choose dense dimension based on config: probe (default) vs env-configured
    # When EMBEDDING_PROVIDER=remote, skip local model loading and use env dimension or probe via remote
    _embedding_provider = os.environ.get("EMBEDDING_PROVIDER", "local").strip().lower()

    if MEMORY_PROBE_EMBED_DIM and _embedding_provider != "remote":
        try:
            # Probe dimension without populating the shared model cache.
            # This preserves the "cache loads on first tool call" behavior and
            # keeps MEMORY_COLD_SKIP_DENSE semantics unchanged.
            from fastembed import TextEmbedding
            _model_probe = TextEmbedding(model_name=EMBEDDING_MODEL)
            _dense_vec = next(_model_probe.embed(["probe"]))
            if hasattr(_dense_vec, "tolist"):
                dense_dim = len(_dense_vec.tolist())
            else:
                try:
                    dense_dim = len(_dense_vec)
                except Exception:
                    dense_dim = int(os.environ.get("MEMORY_VECTOR_DIM") or os.environ.get("EMBED_DIM") or "768")
        except Exception:
            # Fallback to env-configured dimension if probing fails
            try:
                dense_dim = int(os.environ.get("MEMORY_VECTOR_DIM") or os.environ.get("EMBED_DIM") or "768")
            except Exception:
                dense_dim = 768
    elif MEMORY_PROBE_EMBED_DIM and _embedding_provider == "remote":
        # Remote mode: probe via remote embedding service instead of loading model locally
        try:
            import requests
            _embed_url = os.environ.get("EMBEDDING_SERVICE_URL", "http://embedding:8100")
            resp = requests.post(f"{_embed_url}/embed", json={"texts": ["probe"]}, timeout=30)
            resp.raise_for_status()
            vectors = resp.json().get("vectors", [])
            dense_dim = len(vectors[0]) if vectors else int(os.environ.get("MEMORY_VECTOR_DIM") or os.environ.get("EMBED_DIM") or "768")
            logger.info(f"Probed embedding dimension via remote service: {dense_dim}")
        except Exception as e:
            logger.warning(f"Remote embedding probe failed, using env dimension: {e}")
            try:
                dense_dim = int(os.environ.get("MEMORY_VECTOR_DIM") or os.environ.get("EMBED_DIM") or "768")
            except Exception:
                dense_dim = 768
    else:
        dense_dim = int(MEMORY_VECTOR_DIM or 768)

    vectors_cfg = {
        VECTOR_NAME: models.VectorParams(size=int(dense_dim or 768), distance=models.Distance.COSINE),
        LEX_VECTOR_NAME: models.VectorParams(size=LEX_VECTOR_DIM, distance=models.Distance.COSINE),
    }

    # Add mini vector for ReFRAG mode (same logic as ingest_code.py)
    try:
        if os.environ.get("REFRAG_MODE", "").strip().lower() in {
            "1", "true", "yes", "on"
        }:
            mini_vector_name = os.environ.get("MINI_VECTOR_NAME", "mini")
            mini_vec_dim = int(os.environ.get("MINI_VEC_DIM", "64"))
            vectors_cfg[mini_vector_name] = models.VectorParams(
                size=mini_vec_dim,
                distance=models.Distance.COSINE,
            )
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Add pattern vector for structural similarity search
    try:
        if os.environ.get("PATTERN_VECTORS", "").strip().lower() in {
            "1", "true", "yes", "on"
        }:
            pattern_vector_dim = int(os.environ.get("PATTERN_VECTOR_DIM", "64"))
            vectors_cfg["pattern_vector"] = models.VectorParams(
                size=pattern_vector_dim,
                distance=models.Distance.COSINE,
            )
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Build sparse vector config for lex_sparse (lossless lexical matching)
    sparse_cfg = None
    try:
        if os.environ.get("LEX_SPARSE_MODE", "").strip().lower() in {
            "1", "true", "yes", "on"
        }:
            lex_sparse_name = os.environ.get("LEX_SPARSE_NAME", "lex_sparse")
            sparse_params_kwargs = {
                "index": models.SparseIndexParams(full_scan_threshold=5000)
            }
            # Enable IDF modifier for BM25-style term weighting
            if os.environ.get("LEX_SPARSE_IDF", "1").strip().lower() in {"1", "true", "yes", "on"}:
                try:
                    sparse_params_kwargs["modifier"] = models.Modifier.IDF
                except AttributeError:
                    pass  # Older qdrant-client versions
            sparse_cfg = {lex_sparse_name: models.SparseVectorParams(**sparse_params_kwargs)}
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Get a fresh client for collection creation
    client = _get_qdrant_client()
    try:
        client.create_collection(
            collection_name=name,
            vectors_config=vectors_cfg,
            sparse_vectors_config=sparse_cfg,
            hnsw_config=models.HnswConfigDiff(m=16, ef_construct=256),
        )
        vector_names = list(vectors_cfg.keys())
        sparse_info = f", sparse: {list(sparse_cfg.keys())}" if sparse_cfg else ""
        logger.info(f"Created collection '{name}' with vectors: {vector_names}{sparse_info}")
        return True
    finally:
        _return_qdrant_client(client)


# Optional eager collection ensure on startup (enabled by default for backward compatibility).
# Set MEMORY_ENSURE_ON_START=0 to defer ensure to first tool call (recommended on slow storage).
if MEMORY_ENSURE_ON_START:
    try:
        _ensure_collection(DEFAULT_COLLECTION)
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

@mcp.tool()
def set_session_defaults(
    collection: Optional[str] = None,
    session: Optional[str] = None,
    mode: Optional[str] = None,
    language: Optional[str] = None,
    under: Optional[str] = None,
    repo: Any = None,
    compact: Any = None,
    output_format: Optional[str] = None,
    include_snippet: Any = None,
    rerank_enabled: Any = None,
    limit: Any = None,
    ctx: Context = None,
    kwargs: Any = None,
) -> Dict[str, Any]:
    """Set defaults (e.g., collection, mode, language, under) for subsequent calls.

    Behavior:
    - If a request Context is provided (normal with FastMCP), store defaults per-connection
      so subsequent calls on the same MCP session automatically use them (no token needed).
    - Optionally, also supports a lightweight token for clients that prefer cross-connection reuse.

    Precedence everywhere: explicit collection > per-connection defaults > token defaults > env default.

    Parameters:
    - collection: Default collection name
    - mode: Search mode hint
    - under: Default path prefix filter
    - language: Default language filter
    - repo: Default repo filter for multi-repo setups
    - compact: Default compact response mode (bool)
    - output_format: Default output format ("json" or "toon")
    - include_snippet: Default snippet inclusion (bool)
    - rerank_enabled: Default reranking toggle (bool)
    - limit: Default result limit (int)
    - session: Session token for cross-connection reuse
    """
    # Handle kwargs payload from some clients
    try:
        _extra = kwargs or {}
        if isinstance(_extra, str):
            try:
                _extra = json.loads(_extra)
            except Exception:
                _extra = {}
        if isinstance(_extra, dict):
            if not collection and _extra.get("collection"):
                collection = _extra["collection"]
            if not mode and _extra.get("mode"):
                mode = _extra["mode"]
            if not language and _extra.get("language"):
                language = _extra["language"]
            if not under and _extra.get("under"):
                under = _extra["under"]
            if not session and _extra.get("session"):
                session = _extra["session"]
            if repo is None and _extra.get("repo"):
                repo = _extra["repo"]
            if compact is None and _extra.get("compact") is not None:
                compact = _extra["compact"]
            if not output_format and _extra.get("output_format"):
                output_format = _extra["output_format"]
            if include_snippet is None and _extra.get("include_snippet") is not None:
                include_snippet = _extra["include_snippet"]
            if rerank_enabled is None and _extra.get("rerank_enabled") is not None:
                rerank_enabled = _extra["rerank_enabled"]
            if limit is None and _extra.get("limit") is not None:
                limit = _extra["limit"]
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Prepare defaults payload
    defaults: Dict[str, Any] = {}
    if isinstance(collection, str) and collection.strip():
        defaults["collection"] = collection.strip()
    if isinstance(mode, str) and mode.strip():
        defaults["mode"] = mode.strip()
    if isinstance(language, str) and language.strip():
        defaults["language"] = language.strip()
    if isinstance(under, str) and under.strip():
        defaults["under"] = under.strip()
    if isinstance(repo, str) and repo.strip():
        defaults["repo"] = repo.strip()
    elif isinstance(repo, list):
        defaults["repo"] = repo
    if isinstance(output_format, str) and output_format.strip():
        defaults["output_format"] = output_format.strip()
    if compact is not None:
        defaults["compact"] = bool(compact) if not isinstance(compact, bool) else compact
    if include_snippet is not None:
        defaults["include_snippet"] = bool(include_snippet) if not isinstance(include_snippet, bool) else include_snippet
    if rerank_enabled is not None:
        defaults["rerank_enabled"] = bool(rerank_enabled) if not isinstance(rerank_enabled, bool) else rerank_enabled
    if limit is not None:
        try:
            defaults["limit"] = int(limit)
        except (ValueError, TypeError):
            pass

    # Store per-connection (preferred, no token required)
    try:
        if ctx is not None and getattr(ctx, "session", None) is not None and defaults:
            with _SESSION_CTX_LOCK:
                existing = SESSION_DEFAULTS_BY_SESSION.get(ctx.session) or {}
                existing.update(defaults)
                SESSION_DEFAULTS_BY_SESSION[ctx.session] = existing
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Optional: also support legacy token
    sid = (str(session).strip() if session is not None else "") or None
    if not sid:
        import uuid as _uuid
        sid = _uuid.uuid4().hex[:12]
    try:
        if defaults:
            with _SESSION_LOCK:
                existing = SESSION_DEFAULTS.get(sid) or {}
                existing.update(defaults)
                SESSION_DEFAULTS[sid] = existing
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    return {
        "ok": True,
        "session": sid,
        "defaults": (SESSION_DEFAULTS.get(sid, {}) if sid else {}),
        "applied": ("connection" if (ctx is not None and getattr(ctx, "session", None) is not None) else "token"),
    }


@mcp.tool()
def memory_store(
    information: str,
    metadata: Optional[Dict[str, Any]] = None,
    collection: Optional[str] = None,
    session: Optional[str] = None,
    ctx: Context = None,
) -> Dict[str, Any]:
    """Store knowledge/notes into the memory system for later retrieval.

    PRIMARY USE: Persist team knowledge, decisions, conventions, or notes
    that should be retrievable alongside code search results.

    CHOOSE THIS WHEN:
    - You want to store a decision or convention for future reference
    - You're documenting why code works a certain way
    - You want to persist knowledge that context_search can find
    - You're building institutional memory for the codebase

    WHAT TO STORE:
    Good candidates for memory storage:
      - Architecture decisions: "We use JWT for auth because..."
      - Conventions: "All API responses follow the envelope pattern..."
      - Gotchas: "The cache has a 5-minute TTL, not configurable..."
      - Debugging notes: "If X fails, check Y first..."
      - Integration details: "External API requires header Z..."
      - Performance notes: "This query is O(n^2), optimize for large N..."

    Bad candidates (don't store these):
      - Code itself (it's already indexed)
      - Temporary debug output
      - Personal notes not relevant to the codebase
      - Sensitive data (passwords, keys, secrets)

    ESSENTIAL PARAMETERS:
    - information (str): The knowledge/note to store. Should be clear,
      self-contained text that will be useful when retrieved later.

    METADATA PARAMETERS:
    - metadata (dict): Optional structured metadata for filtering.
      Common keys:
      - kind: "note", "decision", "convention", "gotcha", "policy"
      - topic: Subject area ("auth", "caching", "api", "database")
      - priority: Importance (1=low, 5=high)
      - tags: List of tags for filtering
      - author: Who wrote this note

      Auto-added if not provided:
      - created_at: ISO timestamp
      - kind: "memory" (default)
      - source: "memory" (default)

    SESSION PARAMETERS:
    - collection (str): Target collection. Defaults to workspace collection.
    - session (str): Session token for multi-user scenarios.

    RETURNS:
    {
        "ok": true,
        "id": "abc123...",           // Unique ID for this memory
        "message": "Successfully stored information",
        "collection": "codebase",
        "vector": "bge-base-en-v1-5"  // Embedding model used
    }

    USAGE PATTERNS:

    # Store an architecture decision
    memory_store(
        information="We chose FastAPI over Flask because we need async support
        for the WebSocket handlers and automatic OpenAPI documentation.",
        metadata={
            "kind": "decision",
            "topic": "api",
            "tags": ["framework", "architecture"]
        }
    )

    # Store a debugging gotcha
    memory_store(
        information="If authentication fails silently, check that the JWT_SECRET
        env var is set. The auth middleware swallows exceptions.",
        metadata={
            "kind": "gotcha",
            "topic": "auth",
            "priority": 4
        }
    )

    # Store a convention
    memory_store(
        information="All database queries must use parameterized statements.
        Raw string interpolation is forbidden for security.",
        metadata={
            "kind": "convention",
            "topic": "database",
            "tags": ["security", "sql"]
        }
    )

    RETRIEVAL:
    Stored memories can be retrieved via:
    - memory_find(query="...") -> searches only memories
    - context_search(query="...", include_memories=True) -> code + memories

    NOTES:
    - First call may be slower due to embedding model loading
    - Memories are embedded using the same model as code for consistent search
    - Duplicate content is not deduplicated; avoid storing the same thing twice
    """
    sess = _require_auth_session(session)
    coll = _resolve_collection(collection, session=session, ctx=ctx)
    _require_collection_access((sess or {}).get("user_id"), coll, "write")
    _ensure_once(coll)

    # Prepare metadata with defaults and timestamp as documented
    md = metadata.copy() if metadata else {}
    if "created_at" not in md:
        md["created_at"] = datetime.utcnow().isoformat() + "Z"
    if "kind" not in md:
        md["kind"] = "memory"
    if "source" not in md:
        md["source"] = "memory"

    model = _get_embedding_model()
    dense = _embed_text(model, str(information))
    lex = _lex_hash_vector_text(str(information), LEX_VECTOR_DIM)

    # Use UUID to avoid point ID collisions under concurrent load
    import uuid
    pid = uuid.uuid4().hex
    payload = {
        "information": str(information),
        "metadata": md,
    }
    point = models.PointStruct(
        id=pid, vector={VECTOR_NAME: dense, LEX_VECTOR_NAME: lex}, payload=payload
    )
    # wait=True blocks until Qdrant confirms write; set MEMORY_UPSERT_WAIT=0 for async writes
    _upsert_wait = os.environ.get("MEMORY_UPSERT_WAIT", "1").strip().lower() in {"1", "true", "yes", "on"}

    # Use pooled client for upsert
    client = _get_qdrant_client()
    try:
        client.upsert(collection_name=coll, points=[point], wait=_upsert_wait)
    finally:
        _return_qdrant_client(client)

    return {
        "ok": True,
        "id": pid,
        "message": "Successfully stored information",
        "collection": coll,
        "vector": VECTOR_NAME
    }


@mcp.tool()
def memory_find(
    query: str,
    limit: Optional[int] = None,
    collection: Optional[str] = None,
    top_k: Optional[int] = None,
    session: Optional[str] = None,
    q: Optional[str] = None,
    kind: Optional[str] = None,
    language: Optional[str] = None,
    topic: Optional[str] = None,
    tags: Optional[Union[str, List[str]]] = None,
    priority_min: Optional[int] = None,
    ctx: Context = None,
) -> Dict[str, Any]:
    """Retrieve stored memories/notes by semantic similarity.

    PRIMARY USE: Find previously stored knowledge, decisions, or notes.
    Searches ONLY the memory store, not code.

    CHOOSE THIS WHEN:
    - You want to find previously stored notes/decisions
    - You're looking for team knowledge without code results
    - You want to filter memories by metadata (kind, topic, tags)
    - You need to recall specific documented information

    CHOOSE INSTEAD:
    - context_search with include_memories=True -> when you want code + memories
    - repo_search -> when you want code only, no memories

    QUERY EXAMPLES:
    Good queries (conceptual, knowledge-seeking):
      "authentication decisions"      - finds auth-related notes
      "why we chose this approach"    - finds decision rationale
      "database performance tips"     - finds DB-related notes
      "API design conventions"        - finds API conventions
      "deployment gotchas"            - finds deployment notes

    Bad queries:
      "def authenticate"              - code fragment, use repo_search
      "src/auth.py"                   - file path, not a memory query
      "UserService"                   - class name, use repo_search

    ESSENTIAL PARAMETERS:
    - query (str): Natural language description of what you're looking for.

    ALTERNATIVE QUERY PARAMETERS:
    - q (str): Alias for query.
    - top_k (int): Alias for limit.

    FILTER PARAMETERS:
    - kind (str): Filter by memory kind.
      Values: "note", "decision", "convention", "gotcha", "policy", "preference"
    - topic (str): Filter by topic/subject area.
      Example: "auth", "database", "api", "caching"
    - tags (str | list[str]): Filter by tags.
      Example: "security" or ["security", "sql"]
    - language (str): Filter by programming language context.
    - priority_min (int): Minimum priority (1-5). Higher = more important.

    COMMON PARAMETERS:
    - limit (int, default=5): Maximum results to return.
    - collection (str): Target collection. Defaults to workspace collection.
    - session (str): Session token for multi-user scenarios.

    RETURNS:
    {
        "ok": true,
        "results": [
            {
                "id": "abc123...",
                "information": "We chose JWT for authentication because...",
                "metadata": {
                    "kind": "decision",
                    "topic": "auth",
                    "created_at": "2024-01-15T10:30:00Z",
                    "tags": ["security", "architecture"]
                },
                "score": 0.85,
                "highlights": ["...chose <<JWT>> for <<authentication>>..."]
            }
        ],
        "total": 3,
        "count": 3,
        "query": "authentication decisions"
    }

    USAGE PATTERNS:

    # Find all authentication-related notes
    memory_find(query="authentication", topic="auth")

    # Find high-priority gotchas
    memory_find(query="common issues", kind="gotcha", priority_min=4)

    # Find security-related conventions
    memory_find(query="security best practices", kind="convention", tags="security")

    # Find recent decisions
    memory_find(query="recent architecture decisions", kind="decision", limit=10)

    NOTES:
    - Cold start: First call may be slower if embedding model isn't cached
    - Set MEMORY_COLD_SKIP_DENSE=1 to skip dense embedding on cold start
    - Highlights show query term matches in context
    - Results are ranked by hybrid similarity (dense + lexical fusion)
    """
    # Handle 'q' alias for query
    if not query and q:
        query = q

    sess = _require_auth_session(session)
    coll = _resolve_collection(collection, session=session, ctx=ctx)
    _require_collection_access((sess or {}).get("user_id") if sess else None, coll, "read")
    _ensure_once(coll)

    use_dense = True
    if MEMORY_COLD_SKIP_DENSE and not _is_model_cached(EMBEDDING_MODEL):
        use_dense = False
    if use_dense:
        model = _get_embedding_model()
        dense = _embed_text(model, str(query))
    else:
        dense = None
    lex = _lex_hash_vector_text(str(query), LEX_VECTOR_DIM)

    # Harmonize alias: top_k -> limit
    lim = int(limit if limit is not None else (top_k if top_k is not None else MEMORY_FIND_LIMIT_DEFAULT))

    # Build Qdrant filter
    must = []
    if kind:
        must.append(models.FieldCondition(key="metadata.kind", match=models.MatchValue(value=kind)))
    if language:
        must.append(models.FieldCondition(key="metadata.language", match=models.MatchValue(value=language)))
    if topic:
        must.append(models.FieldCondition(key="metadata.topic", match=models.MatchValue(value=topic)))
    if priority_min is not None:
        must.append(models.FieldCondition(key="metadata.priority", range=models.Range(gte=float(priority_min))))
    if tags:
        if isinstance(tags, str):
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        else:
            tag_list = tags
        if tag_list:
            must.append(models.FieldCondition(key="metadata.tags", match=models.MatchAny(any=tag_list)))

    flt = models.Filter(must=must) if must else None

    # Two searches (prefer query_points) then simple RRF-like merge
    # Use pooled client for all search operations
    client = _get_qdrant_client()
    try:
        if use_dense:
            try:
                qp_dense = client.query_points(
                    collection_name=coll,
                    query=dense,
                    using=VECTOR_NAME,
                    query_filter=flt,
                    limit=max(10, lim),
                    with_payload=True,
                )
                res_dense = getattr(qp_dense, "points", qp_dense)
            except AttributeError:
                res_dense = client.search(
                    collection_name=coll,
                    query_vector=(VECTOR_NAME, dense),
                    query_filter=flt,
                    limit=max(10, lim),
                    with_payload=True,
                )
        else:
            res_dense = []

        try:
            qp_lex = client.query_points(
                collection_name=coll,
                query=lex,
                using=LEX_VECTOR_NAME,
                query_filter=flt,
                limit=max(10, lim),
                with_payload=True,
            )
            res_lex = getattr(qp_lex, "points", qp_lex)
        except AttributeError:
            res_lex = client.search(
                collection_name=coll,
                query_vector=(LEX_VECTOR_NAME, lex),
                query_filter=flt,
                limit=max(10, lim),
                with_payload=True,
            )
    finally:
        _return_qdrant_client(client)

    def is_memory_like(payload: Dict[str, Any]) -> bool:
        md = (payload or {}).get("metadata") or {}
        path = md.get("path")
        m_kind = (md.get("kind") or "").lower()
        source = (md.get("source") or "").lower()
        return (
            (not path)
            or (m_kind in {"memory", "preference", "note", "policy", "chat"})
            or (source in {"memory", "chat"})
        )

    def get_highlights(text: str, q_text: str) -> List[str]:
        if not text or not q_text:
            return []
        import re
        # Take interesting tokens from query
        tokens = [t for t in re.split(r'[^A-Za-z0-9]+', q_text) if len(t) > 2]
        if not tokens:
            return []
        
        results = []
        for t in tokens[:3]: # Max 3 types of highlights
            pattern = re.compile(re.escape(t), re.IGNORECASE)
            match = pattern.search(text)
            if match:
                # Get small context
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                snip = text[start:end]
                # Wrap all occurrences of this token in this snip
                highlighted = pattern.sub(lambda m: f"<<{m.group(0)}>>", snip)
                results.append(f"...{highlighted}...")
        return results

    scores: Dict[str, float] = {}
    items: Dict[str, Dict[str, Any]] = {}

    def add_hits(hits, weight: float):
        for r in hits:
            pid = str(getattr(r, "id", None))
            if not pid:
                continue
            pl = getattr(r, "payload", {}) or {}
            if not is_memory_like(pl):
                continue
            scores[pid] = scores.get(pid, 0.0) + weight / (
                1.0 + getattr(r, "score", 0.0)
            )
            inf = pl.get("information") or pl.get("content") or pl.get("text") or ""
            items[pid] = {
                "id": getattr(r, "id", None),
                "information": inf,
                "metadata": pl.get("metadata") or {},
                "score": getattr(r, "score", None),
                "highlights": get_highlights(inf, query)
            }

    add_hits(res_dense, 1.0)
    add_hits(res_lex, 0.9)

    ordered = sorted(
        items.values(), key=lambda x: scores.get(str(x["id"]), 0.0), reverse=True
    )[:lim]
    return {
        "ok": True, 
        "results": ordered, 
        "total": len(ordered), 
        "count": len(ordered),
        "query": query
    }


def _resolve_collection(
    collection: Optional[str],
    session: Optional[str] = None,
    ctx: Context = None,
    extra_kwargs: Any = None,
) -> str:
    """Resolve the collection name honoring explicit args, session defaults, and env fallbacks."""
    coll = (collection or "").strip()
    sid: Optional[str] = None

    # Extract overrides from nested kwargs payloads some clients send
    try:
        payload = extra_kwargs or {}
        if isinstance(payload, dict) and "kwargs" in payload:
            payload = payload.get("kwargs")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
        if not coll and isinstance(payload, dict) and payload.get("collection") is not None:
            coll = str(payload.get("collection")).strip()
        if isinstance(payload, dict) and payload.get("session") is not None:
            sid = str(payload.get("session")).strip()
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Explicit session parameter wins over payload session
    try:
        if session is not None and str(session).strip():
            sid = str(session).strip()
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Per-connection defaults via Context session
    if not coll and ctx is not None and getattr(ctx, "session", None) is not None:
        try:
            with _SESSION_CTX_LOCK:
                defaults = SESSION_DEFAULTS_BY_SESSION.get(ctx.session) or {}
                candidate = str(defaults.get("collection") or "").strip()
                if candidate:
                    coll = candidate
        except Exception as e:
            logger.debug(f"Suppressed exception: {e}")

    # Legacy token-based session defaults
    if not coll and sid:
        try:
            with _SESSION_LOCK:
                defaults = SESSION_DEFAULTS.get(sid) or {}
                candidate = str(defaults.get("collection") or "").strip()
                if candidate:
                    coll = candidate
        except Exception as e:
            logger.debug(f"Suppressed exception: {e}")

    return coll or DEFAULT_COLLECTION


if __name__ == "__main__":
    transport = os.environ.get("FASTMCP_TRANSPORT", "sse").strip().lower()
    # Start lightweight /readyz health endpoint in background (best-effort)
    try:
        _start_readyz_server()
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Relax Pydantic model defaults for **kwargs compatibility
    # This must be called AFTER all tools are registered but BEFORE mcp.run()
    try:
        _relax_var_kwarg_defaults()
    except Exception as e:
        logger.debug(f"Suppressed exception: {e}")

    # Enable stateless HTTP mode to avoid session handshake requirement
    stateless_http = str(os.environ.get("FASTMCP_STATELESS_HTTP", "1")).strip().lower() in {"1", "true", "yes", "on"}
    
    # Add auth header extraction middleware for HTTP transports
    if transport != "stdio":
        _add_auth_middleware()
    
    if transport == "stdio":
        # Run over stdio (for clients that don't support network transports)
        mcp.run(transport="stdio")
    elif transport in {"http", "streamable", "streamable_http", "streamable-http"}:
        # Streamable HTTP (recommended) — endpoint at /mcp (FastMCP default)
        try:
            mcp.settings.host = HOST
            mcp.settings.port = PORT
            # Set stateless mode via settings (not run kwarg)
            if stateless_http:
                mcp.settings.stateless_http = True
        except Exception as e:
            logger.debug(f"Suppressed exception setting config: {e}")
        # Use the correct FastMCP transport name
        try:
            logger.info(f"Starting streamable-http transport on {HOST}:{PORT} (stateless={stateless_http})")
            mcp.run(transport="streamable-http")
        except Exception as e:
            # Log the actual error instead of silently falling back
            logger.warning(f"streamable-http transport failed: {e}, falling back to SSE")
            mcp.settings.host = HOST
            mcp.settings.port = PORT
            mcp.run(transport="sse")
    else:
        # SSE (legacy) — endpoint at /sse
        mcp.settings.host = HOST
        mcp.settings.port = PORT
        mcp.run(transport="sse")
