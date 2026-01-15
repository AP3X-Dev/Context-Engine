# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Neo4j graph backend implementation.

SaaS-ready graph database backend using Neo4j for symbol relationships.
Enables advanced graph traversals, path finding, and relationship analytics.

Enable via: NEO4J_GRAPH=1

Configuration:
- NEO4J_URI: Bolt URI (default: bolt://neo4j:7687)
- NEO4J_USER: Username (default: neo4j)
- NEO4J_PASSWORD: Password (required)
- NEO4J_DATABASE: Database name (default: neo4j)
- NEO4J_MAX_POOL_SIZE: Connection pool size (default: 50)
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional

# Support both package and standalone imports
try:
    from .base import GraphBackend, GraphEdge
except ImportError:
    from base import GraphBackend, GraphEdge

logger = logging.getLogger(__name__)

# Edge types (match Qdrant backend)
EDGE_TYPE_CALLS = "calls"
EDGE_TYPE_IMPORTS = "imports"

# Track initialized databases
_INITIALIZED_DATABASES: set[str] = set()


def _normalize_path(path: str) -> str:
    """Normalize path for consistent edge matching.

    Note: Standalone definition for plugin independence. Mirrors
    scripts.ingest.graph_edges.normalize_path for consistency.
    """
    if not path:
        return ""
    normalized = os.path.normpath(path)
    return normalized.replace("\\", "/")


class Neo4jGraphBackend(GraphBackend):
    """Neo4j-based graph storage backend.

    Uses Neo4j's native graph storage with Cypher queries for:
    - Fast relationship traversals
    - Multi-hop path finding
    - Cross-repo dependency analysis

    Schema:
    - (:Symbol {name, path, repo, collection, language})
    - (:File {path, repo, collection})
    - [:CALLS {edge_id, collection, caller_path, start_line, end_line, repo}]
    - [:IMPORTS {edge_id, collection, caller_path, repo}]
    """

    def __init__(self):
        """Initialize the Neo4j graph backend."""
        self._driver = None
        self._driver_initialized = False

    @property
    def backend_type(self) -> str:
        return "neo4j"

    def _get_driver(self):
        """Get or create Neo4j driver (lazy singleton per instance with connection pooling)."""
        if self._driver is not None:
            return self._driver

        try:
            from neo4j import GraphDatabase
        except ImportError:
            raise ImportError(
                "neo4j package not installed. Install with: pip install neo4j"
            )

        uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "")
        max_pool = int(os.environ.get("NEO4J_MAX_POOL_SIZE", "50") or 50)

        if not password:
            logger.warning("NEO4J_PASSWORD not set - using empty password")

        self._driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            max_connection_pool_size=max_pool,
        )
        self._driver_initialized = True
        logger.info(f"Neo4j driver initialized: {uri}")
        return self._driver
    
    def _get_database(self) -> str:
        """Get configured database name."""
        return os.environ.get("NEO4J_DATABASE", "neo4j")

    def _get_collection(self, graph_store: Optional[str]) -> str:
        """Resolve collection scope for per-collection isolation."""
        collection = str(graph_store or "").strip() or "default"
        if collection.endswith("_graph"):
            collection = collection[: -len("_graph")]
        return collection
    
    def close(self):
        """Close the Neo4j driver."""
        if self._driver:
            self._driver.close()
            self._driver = None
            self._driver_initialized = False
    
    def ensure_graph_store(self, base_collection: str) -> Optional[str]:
        """Ensure Neo4j database and indexes exist.
        
        For Neo4j, we keep a single database and scope by collection name.
        Indexes are created on first use for efficient lookups.
        """
        db = self._get_database()
        
        if db in _INITIALIZED_DATABASES:
            return base_collection or db
        
        try:
            driver = self._get_driver()
            with driver.session(database=db) as session:
                # Create indexes for efficient lookups
                session.run("""
                    CREATE INDEX symbol_name_idx IF NOT EXISTS
                    FOR (s:Symbol) ON (s.name)
                """)
                session.run("""
                    CREATE INDEX symbol_repo_idx IF NOT EXISTS
                    FOR (s:Symbol) ON (s.repo)
                """)
                session.run("""
                    CREATE INDEX symbol_collection_idx IF NOT EXISTS
                    FOR (s:Symbol) ON (s.collection)
                """)
                session.run("""
                    CREATE INDEX symbol_path_idx IF NOT EXISTS
                    FOR (s:Symbol) ON (s.path)
                """)
                session.run("""
                    CREATE INDEX file_path_idx IF NOT EXISTS
                    FOR (f:File) ON (f.path)
                """)
                session.run("""
                    CREATE INDEX file_repo_idx IF NOT EXISTS
                    FOR (f:File) ON (f.repo)
                """)
                session.run("""
                    CREATE INDEX file_collection_idx IF NOT EXISTS
                    FOR (f:File) ON (f.collection)
                """)
                # Relationship property indexes (Neo4j 5.x)
                session.run("""
                    CREATE INDEX calls_edge_id_idx IF NOT EXISTS
                    FOR ()-[r:CALLS]-() ON (r.edge_id)
                """)
                session.run("""
                    CREATE INDEX imports_edge_id_idx IF NOT EXISTS
                    FOR ()-[r:IMPORTS]-() ON (r.edge_id)
                """)
                session.run("""
                    CREATE INDEX calls_collection_idx IF NOT EXISTS
                    FOR ()-[r:CALLS]-() ON (r.collection)
                """)
                session.run("""
                    CREATE INDEX imports_collection_idx IF NOT EXISTS
                    FOR ()-[r:IMPORTS]-() ON (r.collection)
                """)
            
            _INITIALIZED_DATABASES.add(db)
            logger.info(f"Neo4j graph store initialized: {db}")
            return base_collection or db

        except Exception as e:
            logger.error(f"Failed to initialize Neo4j graph store: {e}")
            return None

    def upsert_edges(
        self,
        graph_store: str,
        edges: List[GraphEdge],
        batch_size: int = 100,
    ) -> int:
        """Upsert edges to Neo4j using UNWIND for efficient batch operations."""
        if not edges:
            return 0

        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)
        total = 0

        # Group edges by type for efficient batch processing
        calls_edges: List[Dict[str, Any]] = []
        import_edges: List[Dict[str, Any]] = []

        for edge in edges:
            caller_path = _normalize_path(edge.caller_path)
            callee_path = edge.callee_path or f"<unresolved>/{edge.callee_symbol}"

            edge_params = {
                "caller_symbol": edge.caller_symbol,
                "callee_symbol": edge.callee_symbol,
                "repo": edge.repo,
                "collection": collection,
                "caller_path": caller_path,
                "callee_path": callee_path,
                "start_line": edge.start_line,
                "end_line": edge.end_line,
                "language": edge.language or "",
                "edge_id": edge.id,
                "caller_point_id": edge.caller_point_id or "",
            }

            if edge.edge_type == EDGE_TYPE_CALLS:
                calls_edges.append(edge_params)
            else:
                import_edges.append(edge_params)

        # Batch upsert CALLS edges using UNWIND
        for i in range(0, len(calls_edges), batch_size):
            batch = calls_edges[i:i + batch_size]
            try:
                with driver.session(database=db) as session:
                    result = session.run("""
                        UNWIND $edges AS edge
                        MERGE (caller:Symbol {name: edge.caller_symbol, repo: edge.repo, collection: edge.collection, path: edge.caller_path})
                        MERGE (callee:Symbol {name: edge.callee_symbol, repo: edge.repo, collection: edge.collection, path: edge.callee_path})
                        MERGE (caller)-[r:CALLS {edge_id: edge.edge_id}]->(callee)
                        SET r.caller_path = edge.caller_path,
                            r.callee_path = edge.callee_path,
                            r.start_line = edge.start_line,
                            r.end_line = edge.end_line,
                            r.language = edge.language,
                            r.repo = edge.repo,
                            r.collection = edge.collection,
                            r.caller_point_id = edge.caller_point_id
                        RETURN count(r) AS cnt
                    """, {"edges": batch})
                    total += result.single()["cnt"]
            except Exception as e:
                logger.error(f"Failed to upsert Neo4j CALLS edges batch: {e}")

        # Batch upsert IMPORTS edges using UNWIND
        for i in range(0, len(import_edges), batch_size):
            batch = import_edges[i:i + batch_size]
            try:
                with driver.session(database=db) as session:
                    result = session.run("""
                        UNWIND $edges AS edge
                        MERGE (importer:Symbol {name: edge.caller_symbol, repo: edge.repo, collection: edge.collection, path: edge.caller_path})
                        MERGE (imported:Symbol {name: edge.callee_symbol, repo: edge.repo, collection: edge.collection, path: edge.callee_path})
                        MERGE (importer)-[r:IMPORTS {edge_id: edge.edge_id}]->(imported)
                        SET r.caller_path = edge.caller_path,
                            r.callee_path = edge.callee_path,
                            r.language = edge.language,
                            r.repo = edge.repo,
                            r.collection = edge.collection,
                            r.caller_point_id = edge.caller_point_id
                        RETURN count(r) AS cnt
                    """, {"edges": batch})
                    total += result.single()["cnt"]
            except Exception as e:
                logger.error(f"Failed to upsert Neo4j IMPORTS edges batch: {e}")

        return total

    def delete_edges_by_path(
        self,
        graph_store: str,
        path: str,
        repo: Optional[str] = None,
    ) -> int:
        """Delete all edges from a file path."""
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)
        norm_path = _normalize_path(path)

        try:
            with driver.session(database=db) as session:
                if repo:
                    result = session.run("""
                        MATCH ()-[r]->()
                        WHERE r.caller_path = $path AND r.repo = $repo AND r.collection = $collection
                        DELETE r
                        RETURN count(r) as deleted
                    """, {"path": norm_path, "repo": repo, "collection": collection})
                else:
                    result = session.run("""
                        MATCH ()-[r]->()
                        WHERE r.caller_path = $path AND r.collection = $collection
                        DELETE r
                        RETURN count(r) as deleted
                    """, {"path": norm_path, "collection": collection})

                record = result.single()
                return 1 if record and record["deleted"] > 0 else 0

        except Exception as e:
            logger.error(f"Failed to delete Neo4j edges for {norm_path}: {e}")
            return 0

    def get_callers(
        self,
        graph_store: str,
        symbol: str,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find all callers of a symbol using Cypher."""
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)

        try:
            with driver.session(database=db) as session:
                if repo and repo != "*":
                    result = session.run("""
                        MATCH (caller:Symbol {collection: $collection})-[r:CALLS]->(callee:Symbol {name: $symbol, collection: $collection})
                        WHERE r.collection = $collection AND (r.repo = $repo OR callee.repo = $repo)
                        RETURN caller.name as caller_symbol,
                               callee.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.start_line as start_line,
                               r.end_line as end_line,
                               r.language as language,
                               callee.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
                else:
                    result = session.run("""
                        MATCH (caller:Symbol {collection: $collection})-[r:CALLS]->(callee:Symbol {name: $symbol, collection: $collection})
                        WHERE r.collection = $collection
                        RETURN caller.name as caller_symbol,
                               callee.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.start_line as start_line,
                               r.end_line as end_line,
                               r.language as language,
                               callee.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"symbol": symbol, "collection": collection, "limit": limit})

                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"Failed to get callers for {symbol}: {e}")
            return []

    def get_callees(
        self,
        graph_store: str,
        symbol: str,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find all symbols called by a symbol using Cypher."""
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)

        try:
            with driver.session(database=db) as session:
                if repo and repo != "*":
                    result = session.run("""
                        MATCH (caller:Symbol {name: $symbol, collection: $collection})-[r:CALLS]->(callee:Symbol {collection: $collection})
                        WHERE r.collection = $collection AND (r.repo = $repo OR caller.repo = $repo)
                        RETURN caller.name as caller_symbol,
                               callee.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.start_line as start_line,
                               r.end_line as end_line,
                               r.language as language,
                               caller.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
                else:
                    result = session.run("""
                        MATCH (caller:Symbol {name: $symbol, collection: $collection})-[r:CALLS]->(callee:Symbol {collection: $collection})
                        WHERE r.collection = $collection
                        RETURN caller.name as caller_symbol,
                               callee.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.start_line as start_line,
                               r.end_line as end_line,
                               r.language as language,
                               caller.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"symbol": symbol, "collection": collection, "limit": limit})

                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"Failed to get callees for {symbol}: {e}")
            return []

    def get_importers(
        self,
        graph_store: str,
        module: str,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find all files that import a module using Cypher."""
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)

        try:
            with driver.session(database=db) as session:
                if repo and repo != "*":
                    result = session.run("""
                        MATCH (importer:Symbol {collection: $collection})-[r:IMPORTS]->(imported:Symbol {name: $module, collection: $collection})
                        WHERE r.collection = $collection AND (r.repo = $repo OR imported.repo = $repo)
                        RETURN importer.name as caller_symbol,
                               imported.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.language as language,
                               imported.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"module": module, "repo": repo, "collection": collection, "limit": limit})
                else:
                    result = session.run("""
                        MATCH (importer:Symbol {collection: $collection})-[r:IMPORTS]->(imported:Symbol {name: $module, collection: $collection})
                        WHERE r.collection = $collection
                        RETURN importer.name as caller_symbol,
                               imported.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.language as language,
                               imported.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"module": module, "collection": collection, "limit": limit})

                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"Failed to get importers for {module}: {e}")
            return []

    def resolve_symbol(
        self,
        graph_store: str,
        symbol_name: str,
        repo: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve a symbol name to its definition file path via Neo4j."""
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)

        try:
            with driver.session(database=db) as session:
                # Find symbol with matching name that has a real file path
                if repo and repo != "*":
                    result = session.run("""
                        MATCH (s:Symbol {name: $symbol, collection: $collection, repo: $repo})
                        WHERE s.path IS NOT NULL AND NOT s.path STARTS WITH '<'
                        RETURN s.path as path
                        LIMIT 1
                    """, {"symbol": symbol_name, "collection": collection, "repo": repo})
                else:
                    result = session.run("""
                        MATCH (s:Symbol {name: $symbol, collection: $collection})
                        WHERE s.path IS NOT NULL AND NOT s.path STARTS WITH '<'
                        RETURN s.path as path
                        LIMIT 1
                    """, {"symbol": symbol_name, "collection": collection})

                record = result.single()
                if record:
                    return record["path"]
                return None

        except Exception as e:
            logger.debug(f"Failed to resolve symbol {symbol_name}: {e}")
            return None

    def resolve_import(
        self,
        graph_store: str,
        import_name: str,
        repo: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve an import to its source file path via Neo4j."""
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)

        # Convert dotted import to file path pattern
        module_parts = import_name.replace(".", "/")

        try:
            with driver.session(database=db) as session:
                result = session.run("""
                    MATCH (s:Symbol {collection: $collection})
                    WHERE s.path ENDS WITH $suffix
                    RETURN s.path as path
                    LIMIT 1
                """, {"collection": collection, "suffix": f"/{module_parts}.py"})

                record = result.single()
                if record:
                    return record["path"]
                return None

        except Exception as e:
            logger.debug(f"Failed to resolve import {import_name}: {e}")
            return None