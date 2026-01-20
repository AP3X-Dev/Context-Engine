# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Plugin Interface for Neo4j Graph Backend.

This module defines the plugin contract for Context-Engine integration:
- Version compatibility checking
- Capability declaration
- Factory functions for backend and tools
- Health checks

Usage:
    from plugins.neo4j_graph.plugin import register_plugin, PLUGIN_MANIFEST
    
    manifest = register_plugin(context_engine_version="1.0.0")
    if manifest["compatible"]:
        backend = manifest["get_backend"]()
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import GraphBackend

logger = logging.getLogger(__name__)

# =============================================================================
# Plugin Metadata
# =============================================================================

PLUGIN_NAME = "context-engine-neo4j-graph"
PLUGIN_VERSION = "1.0.0"
PLUGIN_AUTHOR = "Context-Engine Contributors"
PLUGIN_DESCRIPTION = "Neo4j Knowledge Graph backend for Context-Engine Graph RAG"

# Context-Engine version compatibility
MIN_CE_VERSION = "1.0.0"
MAX_CE_VERSION = "2.0.0"

# Required environment variables
REQUIRED_ENV = ["NEO4J_PASSWORD"]
OPTIONAL_ENV = ["NEO4J_URI", "NEO4J_USER", "NEO4J_DATABASE", "NEO4J_MAX_POOL_SIZE"]


@dataclass
class PluginCapability:
    """Describes a capability provided by the plugin."""
    name: str
    description: str
    enabled: bool = True


@dataclass 
class PluginManifest:
    """Plugin manifest with metadata and factory functions."""
    name: str
    version: str
    description: str
    compatible: bool = False
    error: Optional[str] = None
    capabilities: List[PluginCapability] = field(default_factory=list)
    
    # Factory functions (set by register_plugin)
    get_backend: Optional[Callable[[], "GraphBackend"]] = None
    get_knowledge_graph: Optional[Callable] = None
    get_mcp_tools: Optional[Callable[[], List[Dict]]] = None
    health_check: Optional[Callable[[], Dict]] = None


def _check_neo4j_available() -> tuple[bool, Optional[str]]:
    """Check if Neo4j driver is installed."""
    try:
        import neo4j
        return True, None
    except ImportError:
        return False, "neo4j package not installed. Run: pip install neo4j"


def _check_env() -> tuple[bool, Optional[str]]:
    """Check required environment variables."""
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        return False, f"Missing env vars: {', '.join(missing)}"
    return True, None


def register_plugin(context_engine_version: str = "1.0.0") -> PluginManifest:
    """
    Register plugin with Context-Engine.
    
    Args:
        context_engine_version: Version of Context-Engine loading plugin
        
    Returns:
        PluginManifest with compatibility and factory functions
    """
    # Version check (simple comparison)
    compatible = True
    error = None
    
    try:
        from packaging.version import Version
        v = Version(context_engine_version)
        if v < Version(MIN_CE_VERSION) or v >= Version(MAX_CE_VERSION):
            compatible = False
            error = f"Requires Context-Engine {MIN_CE_VERSION} - {MAX_CE_VERSION}"
    except ImportError:
        pass  # Skip version check if packaging not available
    
    # Check Neo4j availability
    neo4j_ok, neo4j_err = _check_neo4j_available()
    
    # Capabilities
    capabilities = [
        PluginCapability("neo4j_backend", "Neo4j graph database backend", neo4j_ok),
        PluginCapability("knowledge_graph", "Rich knowledge graph with algorithms", neo4j_ok),
        PluginCapability("graph_rag", "Graph-based context retrieval", neo4j_ok),
        PluginCapability("mcp_tools", "MCP tools for graph queries", neo4j_ok),
    ]
    
    # Factory functions - handle both package and standalone imports
    def _get_backend():
        try:
            from .backend import Neo4jGraphBackend
        except ImportError:
            from backend import Neo4jGraphBackend
        return Neo4jGraphBackend()

    def _get_knowledge_graph():
        try:
            from .knowledge_graph import get_knowledge_graph
        except ImportError:
            from knowledge_graph import get_knowledge_graph
        return get_knowledge_graph()

    def _get_mcp_tools():
        # Only return tools if Neo4j is enabled and available
        if not neo4j_ok:
            return []
        return [{
            "name": "neo4j_graph_query",
            "description": "Advanced Neo4j graph traversals",
            "module": "neo4j_graph.mcp_tools",
            "function": "neo4j_graph_query",
        }]

    def _health_check():
        status = {"plugin": PLUGIN_NAME, "version": PLUGIN_VERSION, "healthy": True, "checks": {}}

        # Check driver availability
        driver_ok, driver_err = _check_neo4j_available()
        status["checks"]["neo4j_driver"] = "available" if driver_ok else driver_err
        if not driver_ok:
            status["healthy"] = False
            return status  # Can't proceed without driver

        # Check env only if driver is available
        env_ok, env_err = _check_env()
        status["checks"]["env_config"] = "valid" if env_ok else env_err
        if not env_ok:
            # Missing env is only unhealthy if we're trying to use Neo4j
            status["checks"]["connection"] = "skipped (missing config)"
            status["healthy"] = False
            return status

        # Test connection
        try:
            try:
                from .backend import Neo4jGraphBackend
            except ImportError:
                from backend import Neo4jGraphBackend
            backend = Neo4jGraphBackend()
            backend._get_driver()
            status["checks"]["connection"] = "connected"
        except Exception as e:
            status["checks"]["connection"] = f"error: {e}"
            status["healthy"] = False

        return status
    
    return PluginManifest(
        name=PLUGIN_NAME,
        version=PLUGIN_VERSION,
        description=PLUGIN_DESCRIPTION,
        compatible=compatible,
        error=error,
        capabilities=capabilities,
        get_backend=_get_backend if neo4j_ok else None,
        get_knowledge_graph=_get_knowledge_graph if neo4j_ok else None,
        get_mcp_tools=_get_mcp_tools,
        health_check=_health_check,
    )


# Static manifest for discovery
PLUGIN_MANIFEST = {
    "name": PLUGIN_NAME,
    "version": PLUGIN_VERSION,
    "description": PLUGIN_DESCRIPTION,
    "type": "graph_backend",
    "capabilities": ["neo4j_backend", "knowledge_graph", "graph_rag", "mcp_tools"],
    "config": {k: f"Required" if k in REQUIRED_ENV else "Optional" for k in REQUIRED_ENV + OPTIONAL_ENV},
}

