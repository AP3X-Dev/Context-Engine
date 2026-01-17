# Graph Backends (Open Core)

Qdrant-based graph storage for symbol relationships.

## Overview

This module provides a pluggable graph storage layer for code symbol relationships.
The **Qdrant backend** is the default, included in open core.

For advanced graph features, see the [Neo4j Plugin](../../plugins/neo4j_graph/).

## Backends

| Backend | Location | Use Case | Enable |
|---------|----------|----------|--------|
| **Qdrant** | `scripts/graph_backends/` | Default, lightweight | Default |
| **Neo4j** | `plugins/neo4j_graph/` | Production, advanced | `NEO4J_GRAPH=1` |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Indexing Pipeline                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Code File → AST Analysis → calls/imports → ingest_adapter             │
│                                                   │                     │
│                                    ┌──────────────┴──────────────┐     │
│                                    ▼                             ▼     │
│                          ┌─────────────────┐          ┌───────────────┐│
│                          │ QdrantBackend   │          │ Neo4jBackend  ││
│                          │ (open core)     │          │ (plugin)      ││
│                          └────────┬────────┘          └───────┬───────┘│
│                                   │                           │        │
│                                   ▼                           ▼        │
│                          ┌─────────────────┐          ┌───────────────┐│
│                          │ Qdrant          │          │ Neo4j         ││
│                          │ *_graph coll    │          │ Database      ││
│                          └─────────────────┘          └───────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

## Module Structure

```
scripts/graph_backends/
├── __init__.py          # Backend factory, loads plugin if NEO4J_GRAPH=1
├── base.py              # GraphBackend ABC, GraphEdge, GraphQueryResult
├── qdrant_backend.py    # Default Qdrant implementation
├── ingest_adapter.py    # Unified API for indexer pipeline
└── README.md            # This file
```

## Core Components

### `base.py` - Interface

```python
class GraphEdge:
    """Represents a call/import relationship."""
    id: str
    caller_symbol: str
    callee_symbol: str
    caller_path: str
    edge_type: str  # "calls" or "imports"
    repo: str
    # Optional: start_line, end_line, language, caller_point_id

class GraphBackend(ABC):
    """Abstract base class for graph storage backends."""

    def ensure_graph_store(self, base_collection: str) -> Optional[str]: ...
    def upsert_edges(self, graph_store: str, edges: List[GraphEdge]) -> int: ...
    def delete_edges_by_path(self, graph_store: str, path: str) -> int: ...
    def get_callers(self, graph_store: str, symbol: str) -> List[Dict]: ...
    def get_callees(self, graph_store: str, symbol: str) -> List[Dict]: ...
    def get_importers(self, graph_store: str, module: str) -> List[Dict]: ...
```

### `ingest_adapter.py` - Pipeline Integration

The adapter routes edge operations to the active backend:

```python
from scripts.graph_backends.ingest_adapter import (
    ensure_graph_store,
    extract_call_edges,
    extract_import_edges,
    upsert_edges,
    delete_edges_by_path,
)

# During indexing:
graph_store = ensure_graph_store(client, "my-collection")
edges = extract_call_edges(symbol_path="main", calls=["helper"], ...)
upsert_edges(client, graph_store, edges)
```

## Usage

### Get Backend

```python
from scripts.graph_backends import get_graph_backend, GRAPH_BACKEND_TYPE

backend = get_graph_backend()  # Singleton
print(GRAPH_BACKEND_TYPE)  # "qdrant" or "neo4j"
```

### Query Relationships

```python
graph_store = "collection_graph" if GRAPH_BACKEND_TYPE == "qdrant" else "collection"

# Find callers of a function
callers = backend.get_callers(graph_store, "my_function", repo="my-repo")

# Find what a function calls
callees = backend.get_callees(graph_store, "my_function")

# Find files that import a module
importers = backend.get_importers(graph_store, "os", repo="my-repo")
```

## Neo4j Plugin

For advanced features (PageRank, path finding, knowledge graph), enable the plugin:

```bash
# Copy plugin to deployment
cp -r plugins/neo4j_graph /path/to/deployment/plugins/

# Install driver
pip install neo4j>=5.0.0

# Enable
export NEO4J_GRAPH=1
export NEO4J_PASSWORD=your_password

# Start with Neo4j
docker compose -f docker-compose.yml -f docker-compose.neo4j.yml up -d
```

See [plugins/neo4j_graph/README.md](../../plugins/neo4j_graph/README.md) for details.
