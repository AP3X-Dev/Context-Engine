# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Neo4j Knowledge Graph Plugin for Context-Engine.

This is a STANDALONE PLUGIN that can be:
- Extracted from the main repo and maintained privately
- Dropped into any Context-Engine deployment
- Installed via pip: pip install context-engine-neo4j-graph

The plugin provides:
- Neo4j graph database backend for code relationships
- Rich knowledge graph with PageRank, community detection
- Advanced MCP tools for graph traversals
- Graph RAG context retrieval

Usage:
    # Enable via environment variable
    export NEO4J_GRAPH=1
    export NEO4J_PASSWORD=your_password
    
    # Plugin auto-registers when Context-Engine starts
    
Requirements:
    - Neo4j 5.x (Community or Enterprise)
    - neo4j Python driver: pip install neo4j
    
For Qdrant backend (open core default), no plugin needed.
"""
from __future__ import annotations

__version__ = "1.0.0"
__plugin_name__ = "context-engine-neo4j-graph"

# Lazy exports
__all__ = [
    "__version__",
    "__plugin_name__",
    "Neo4jGraphBackend",
    "Neo4jKnowledgeGraph",
    "get_knowledge_graph",
    "register_plugin",
    "PLUGIN_MANIFEST",
]


def __getattr__(name: str):
    """Lazy imports for plugin components."""
    if name == "Neo4jGraphBackend":
        from .backend import Neo4jGraphBackend
        return Neo4jGraphBackend
    if name == "Neo4jKnowledgeGraph":
        from .knowledge_graph import Neo4jKnowledgeGraph
        return Neo4jKnowledgeGraph
    if name == "get_knowledge_graph":
        from .knowledge_graph import get_knowledge_graph
        return get_knowledge_graph
    if name == "register_plugin":
        from .plugin import register_plugin
        return register_plugin
    if name == "PLUGIN_MANIFEST":
        from .plugin import PLUGIN_MANIFEST
        return PLUGIN_MANIFEST
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

