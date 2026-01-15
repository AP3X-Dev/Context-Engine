# Neo4j Knowledge Graph Plugin

Standalone Neo4j graph backend plugin for Context-Engine.

## Overview

This plugin provides a Neo4j-based graph backend as an alternative to the default Qdrant graph storage. It enables:

- **Rich graph traversals** - Multi-hop caller/callee chains via Cypher
- **Graph algorithms** - PageRank, community detection, path finding
- **Knowledge graph** - Semantic relationships beyond calls/imports
- **Graph RAG** - Context retrieval using graph structure

## Installation

Copy the plugin directory to your Context-Engine deployment:

```bash
cp -r plugins/neo4j_graph /path/to/your/deployment/plugins/
```

Install the Neo4j driver:

```bash
pip install neo4j>=5.0.0
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEO4J_GRAPH` | Yes | `0` | Set to `1` to enable Neo4j backend |
| `NEO4J_PASSWORD` | Yes | - | Neo4j authentication password |
| `NEO4J_URI` | No | `bolt://neo4j:7687` | Neo4j Bolt connection URI |
| `NEO4J_USER` | No | `neo4j` | Neo4j username |
| `NEO4J_DATABASE` | No | `neo4j` | Neo4j database name |
| `NEO4J_MAX_POOL_SIZE` | No | `50` | Connection pool size |

### Docker Compose

Use the provided compose file to add Neo4j to your stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.neo4j.yml up -d
```

This:
- Starts Neo4j 5.x with APOC plugins
- Connects to the Context-Engine network
- Configures indexer/MCP services with Neo4j env vars

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Context-Engine Core                       │
├─────────────────────────────────────────────────────────────┤
│  scripts/graph_backends/                                     │
│  ├── __init__.py      # Backend factory (loads plugin)      │
│  ├── base.py          # GraphBackend ABC, GraphEdge         │
│  ├── qdrant_backend.py # Default Qdrant implementation      │
│  └── ingest_adapter.py # Unified API for indexer            │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ NEO4J_GRAPH=1
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Neo4j Plugin                              │
├─────────────────────────────────────────────────────────────┤
│  plugins/neo4j_graph/                                        │
│  ├── __init__.py        # Plugin exports                    │
│  ├── backend.py         # Neo4jGraphBackend implementation  │
│  ├── knowledge_graph.py # Advanced graph features           │
│  ├── schema.py          # Node/relationship types           │
│  ├── plugin.py          # Plugin manifest & registration    │
│  └── base.py            # Standalone interface copy         │
└─────────────────────────────────────────────────────────────┘
```

## Indexing Flow

When `NEO4J_GRAPH=1`, the indexing pipeline routes graph edges to Neo4j:

```
Code File → AST Analysis → calls/imports extracted
                              │
                              ▼
                    extract_call_edges()
                    extract_import_edges()
                              │
                              ▼
                    GraphEdge objects
                              │
                              ▼
                    ingest_adapter.upsert_edges()
                              │
                              ▼
                    get_graph_backend()
                              │
              ┌───────────────┴───────────────┐
              │                               │
        NEO4J_GRAPH=0                   NEO4J_GRAPH=1
              │                               │
              ▼                               ▼
     QdrantGraphBackend              Neo4jGraphBackend
              │                               │
              ▼                               ▼
     Qdrant _graph collection      Neo4j CALLS/IMPORTS rels
```

## Graph Schema

### Nodes

| Label | Properties | Description |
|-------|------------|-------------|
| `Symbol` | `name`, `repo`, `path`, `collection`, `start_line` | Code symbol (function/class/method) |

### Relationships

| Type | Description | Properties |
|------|-------------|------------|
| `CALLS` | Function calls function | `edge_id`, `collection`, `caller_path`, `start_line`, `end_line`, `language` |
| `IMPORTS` | File imports module | `edge_id`, `collection`, `caller_path`, `language` |

## Usage

### Health Check

```python
from plugins.neo4j_graph.plugin import register_plugin

manifest = register_plugin("1.0.0")
health = manifest.health_check()
print(health)
# {'plugin': 'context-engine-neo4j-graph', 'healthy': True, 'checks': {...}}
```

### Direct Backend Access

```python
from plugins.neo4j_graph import Neo4jGraphBackend

backend = Neo4jGraphBackend()
callers = backend.get_callers("codebase", "my_function", repo="my-repo")
```

### Via Core (Recommended)

```python
# Set NEO4J_GRAPH=1 in environment
from scripts.graph_backends import get_graph_backend

backend = get_graph_backend()  # Returns Neo4jGraphBackend
callers = backend.get_callers("codebase", "my_function")
```

## CLI Commands

The plugin includes a CLI for testing and managing Neo4j graph data.

### Check Status

```bash
NEO4J_URI="bolt://localhost:7687" \
NEO4J_PASSWORD="your_password" \
python -m plugins.neo4j_graph status
```

Output:
```
Backend: neo4j
URI: bolt://localhost:7687

Graph Stats:
  Symbols: 4671
  CALLS edges: 15347
  IMPORTS edges: 2101

✓ Neo4j connection OK
```

### Backfill from Qdrant

Extract graph edges from the main Qdrant collection (using `metadata.calls` and `metadata.imports` fields) and populate Neo4j:

```bash
NEO4J_URI="bolt://localhost:7687" \
NEO4J_PASSWORD="your_password" \
QDRANT_URL="http://localhost:6333" \
python -m plugins.neo4j_graph backfill --collection my-collection
```

Options:
- `--collection`, `-c`: Main collection name (required)
- `--limit`, `-l`: Max edges to backfill (default: all)

### Index Directory

Index a codebase directly to Neo4j using AST analysis:

```bash
NEO4J_URI="bolt://localhost:7687" \
NEO4J_PASSWORD="your_password" \
python -m plugins.neo4j_graph index --path /path/to/code --repo my-repo
```

Options:
- `--path`, `-p`: Directory to index (required)
- `--repo`, `-r`: Repository name (default: directory name)

### Query Graph

Query the graph for callers, callees, or importers of a symbol:

```bash
NEO4J_URI="bolt://localhost:7687" \
NEO4J_PASSWORD="your_password" \
python -m plugins.neo4j_graph query --symbol my_function --type callers
```

Output:
```
Callers of 'my_function' (5 found):
  main (scripts/app.py)
  process_data (scripts/pipeline.py)
  handle_request (scripts/api.py)
  ...
```

Options:
- `--symbol`, `-s`: Symbol name to query (required)
- `--type`, `-t`: Query type - `callers`, `callees`, or `imports` (default: callers)
- `--limit`, `-l`: Maximum results to return (default: 20)

Query types:
- `callers`: Find all functions/methods that call this symbol
- `callees`: Find all functions/methods this symbol calls
- `imports`: Find all files that import this module/symbol

## Testing

Run isolated plugin tests:

```bash
cd plugins/neo4j_graph
pip install pytest neo4j
NEO4J_PASSWORD=test pytest tests/ -v
```

Skip tests requiring live Neo4j:

```bash
pytest tests/ -v -m "not neo4j"
```

## Files

| File | Purpose |
|------|---------|
| `backend.py` | `Neo4jGraphBackend` - implements `GraphBackend` interface |
| `knowledge_graph.py` | `Neo4jKnowledgeGraph` - advanced graph features |
| `schema.py` | `NodeType`, `RelationType`, `GraphNode`, `GraphRelationship` |
| `plugin.py` | Plugin manifest, `register_plugin()`, health checks |
| `base.py` | Standalone copy of `GraphBackend` ABC for independence |
