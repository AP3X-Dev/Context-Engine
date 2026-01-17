# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Graph backends abstraction layer (Open Core).

Provides the Qdrant graph storage backend for symbol relationships.
This is the default backend for Context-Engine.

For Neo4j backend, install the separate plugin:
    pip install context-engine-neo4j-graph

Or add the plugins/neo4j_graph directory to your installation.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import GraphBackend

logger = logging.getLogger(__name__)

__all__ = [
    "GraphBackend",
    "GraphEdge",
    "GraphQueryResult",
    "QdrantGraphBackend",
    "get_graph_backend",
    "ensure_plugins_path",
    "is_neo4j_enabled",
    "GRAPH_BACKEND_TYPE",
]


def is_neo4j_enabled() -> bool:
    """Check if Neo4j graph backend is enabled via environment.

    Checks the NEO4J_GRAPH environment variable.
    This is the canonical function to use across the codebase.

    Returns:
        True if NEO4J_GRAPH is set to a truthy value (1, true, yes, on).
    """
    return str(os.environ.get("NEO4J_GRAPH", "")).strip().lower() in {
        "1", "true", "yes", "on"
    }


# Environment variable to enable Neo4j backend (requires plugin)
_NEO4J_ENABLED = is_neo4j_enabled()

# Track which backend is active
GRAPH_BACKEND_TYPE = "neo4j" if _NEO4J_ENABLED else "qdrant"

# Lazy-loaded singleton backend instance
_BACKEND_INSTANCE: "GraphBackend | None" = None

# Track if plugins path has been added
_PLUGINS_PATH_ADDED = False


def ensure_plugins_path() -> Path:
    """Ensure the plugins directory is in sys.path.

    Call this before importing from plugin modules.
    Returns the plugins directory path.
    """
    global _PLUGINS_PATH_ADDED
    plugins_dir = Path(__file__).parent.parent.parent / "plugins"

    if not _PLUGINS_PATH_ADDED:
        plugins_str = str(plugins_dir)
        if plugins_str not in sys.path:
            sys.path.insert(0, plugins_str)
        _PLUGINS_PATH_ADDED = True

    return plugins_dir


def get_graph_backend() -> "GraphBackend":
    """Get the configured graph backend instance (lazy singleton).

    Returns:
        GraphBackend instance based on NEO4J_GRAPH environment variable.
        - NEO4J_GRAPH=1: Loads Neo4j plugin (must be installed)
        - Otherwise: Returns QdrantGraphBackend (default)
    """
    global _BACKEND_INSTANCE

    if _BACKEND_INSTANCE is not None:
        return _BACKEND_INSTANCE

    if _NEO4J_ENABLED:
        # Try to load Neo4j plugin from plugins/ directory
        try:
            ensure_plugins_path()
            from neo4j_graph import Neo4jGraphBackend
            _BACKEND_INSTANCE = Neo4jGraphBackend()
            logger.info("Loaded Neo4j graph backend from plugin")
        except ImportError as e:
            logger.warning(
                f"NEO4J_GRAPH=1 but neo4j_graph plugin not found: {e}. "
                "Falling back to Qdrant. Copy plugins/neo4j_graph to your deployment."
            )
            from .qdrant_backend import QdrantGraphBackend
            global GRAPH_BACKEND_TYPE
            GRAPH_BACKEND_TYPE = "qdrant"
            _BACKEND_INSTANCE = QdrantGraphBackend()
    else:
        from .qdrant_backend import QdrantGraphBackend
        _BACKEND_INSTANCE = QdrantGraphBackend()

    return _BACKEND_INSTANCE


# Lazy imports for type checkers
def __getattr__(name: str):
    if name == "GraphBackend":
        from .base import GraphBackend
        return GraphBackend
    if name == "GraphEdge":
        from .base import GraphEdge
        return GraphEdge
    if name == "GraphQueryResult":
        from .base import GraphQueryResult
        return GraphQueryResult
    if name == "QdrantGraphBackend":
        from .qdrant_backend import QdrantGraphBackend
        return QdrantGraphBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
