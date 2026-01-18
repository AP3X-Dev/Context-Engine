# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Neo4j graph backend implementation.

Graph database backend using Neo4j for symbol relationships.
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

import atexit
import hashlib
import logging
import os
import threading
import weakref
from typing import Any, Dict, List, Optional

# Support both package and standalone imports
try:
    from .base import GraphBackend, GraphEdge
except ImportError:
    from base import GraphBackend, GraphEdge

logger = logging.getLogger(__name__)

__all__ = [
    "Neo4jGraphBackend",
    "EDGE_TYPE_CALLS",
    "EDGE_TYPE_IMPORTS",
]

# Track all driver instances for cleanup
_DRIVER_INSTANCES: weakref.WeakSet = weakref.WeakSet()

# Track collections that have been checked for auto-backfill (avoid repeated checks)
_BACKFILL_CHECKED: set = set()

# Environment variable to disable auto-backfill (enabled by default)
AUTO_BACKFILL_DISABLED = os.environ.get("NEO4J_AUTO_BACKFILL_DISABLE", "").strip().lower() in {"1", "true", "yes", "on"}


def _cleanup_drivers():
    """Cleanup all Neo4j drivers on process exit."""
    for backend in list(_DRIVER_INSTANCES):
        try:
            if backend._driver is not None:
                backend._driver.close()
                logger.debug("Neo4j driver closed on shutdown")
        except Exception:
            pass


# Register cleanup on process exit
atexit.register(_cleanup_drivers)

# Edge types (match Qdrant backend)
EDGE_TYPE_CALLS = "calls"
EDGE_TYPE_IMPORTS = "imports"


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

    # Class-level cache for initialized databases (shared across instances)
    # This is intentional - we only need to create indexes once per database
    _initialized_databases: set[str] = set()

    # Circuit breaker state (class-level, shared)
    _circuit_lock = threading.Lock()  # Protects circuit breaker state
    _circuit_open: bool = False
    _circuit_failures: int = 0
    _circuit_last_failure: float = 0.0
    _CIRCUIT_FAILURE_THRESHOLD = int(os.environ.get("NEO4J_CIRCUIT_FAILURE_THRESHOLD", "3") or 3)
    _CIRCUIT_RESET_TIMEOUT = float(os.environ.get("NEO4J_CIRCUIT_RESET_TIMEOUT", "30.0") or 30.0)

    def __init__(self):
        """Initialize the Neo4j graph backend."""
        self._driver = None
        self._async_driver = None
        self._driver_initialized = False
        self._async_driver_initialized = False
        # Register for cleanup on process exit
        _DRIVER_INSTANCES.add(self)

    @classmethod
    def clear_initialized_cache(cls) -> None:
        """Clear the initialized databases cache.

        Useful for testing or when database schema needs to be re-initialized.
        """
        cls._initialized_databases.clear()

    @classmethod
    def reset_circuit_breaker(cls) -> None:
        """Reset the circuit breaker state.

        Useful for testing or manual recovery.
        """
        with cls._circuit_lock:
            cls._circuit_open = False
            cls._circuit_failures = 0
            cls._circuit_last_failure = 0.0

    @classmethod
    def _check_circuit(cls) -> bool:
        """Check if circuit breaker allows requests.

        Returns True if requests are allowed, False if circuit is open.
        """
        import time

        with cls._circuit_lock:
            if not cls._circuit_open:
                return True

            # Check if enough time has passed to try again (half-open state)
            if time.time() - cls._circuit_last_failure > cls._CIRCUIT_RESET_TIMEOUT:
                logger.info("Neo4j circuit breaker entering half-open state")
                return True

            return False

    @classmethod
    def _record_success(cls) -> None:
        """Record a successful connection/operation."""
        with cls._circuit_lock:
            if cls._circuit_open:
                logger.info("Neo4j circuit breaker closed after successful operation")
            cls._circuit_open = False
            cls._circuit_failures = 0

    @classmethod
    def _record_failure(cls) -> None:
        """Record a connection/operation failure."""
        import time

        with cls._circuit_lock:
            cls._circuit_failures += 1
            cls._circuit_last_failure = time.time()

            if cls._circuit_failures >= cls._CIRCUIT_FAILURE_THRESHOLD:
                if not cls._circuit_open:
                    logger.warning(
                        f"Neo4j circuit breaker OPEN after {cls._circuit_failures} failures. "
                        f"Will retry after {cls._CIRCUIT_RESET_TIMEOUT}s"
                    )
                cls._circuit_open = True

    @property
    def backend_type(self) -> str:
        return "neo4j"

    def _get_driver(self):
        """Get or create Neo4j driver (lazy singleton per instance with connection pooling).

        Uses circuit breaker pattern to avoid repeated timeouts when Neo4j is down.
        """
        # Check circuit breaker first
        if not self._check_circuit():
            raise ConnectionError(
                f"Neo4j circuit breaker is OPEN. Too many failures. "
                f"Will retry after {self._CIRCUIT_RESET_TIMEOUT}s"
            )

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

        try:
            self._driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                max_connection_pool_size=max_pool,
            )
            # Verify connection works
            self._driver.verify_connectivity()
            self._driver_initialized = True
            self._record_success()
            logger.info(f"Neo4j driver initialized: {uri}")
            return self._driver
        except Exception as e:
            self._record_failure()
            logger.error(f"Neo4j connection failed: {e}")
            raise
    
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
        """Close the Neo4j driver(s)."""
        if self._driver:
            self._driver.close()
            self._driver = None
            self._driver_initialized = False
        # Note: async driver must be closed with await in an async context
        # This sync close only handles the sync driver

    async def _get_async_driver(self):
        """Get or create async Neo4j driver (lazy singleton with connection pooling).

        Uses the same circuit breaker as sync driver.
        """
        # Check circuit breaker first
        if not self._check_circuit():
            raise ConnectionError(
                f"Neo4j circuit breaker is OPEN. Too many failures. "
                f"Will retry after {self._CIRCUIT_RESET_TIMEOUT}s"
            )

        if self._async_driver is not None:
            return self._async_driver

        try:
            from neo4j import AsyncGraphDatabase
        except ImportError:
            raise ImportError(
                "neo4j package not installed or async not supported. "
                "Install with: pip install neo4j>=5.0"
            )

        uri = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "")
        max_pool = int(os.environ.get("NEO4J_MAX_POOL_SIZE", "50") or 50)

        if not password:
            logger.warning("NEO4J_PASSWORD not set - using empty password")

        try:
            self._async_driver = AsyncGraphDatabase.driver(
                uri,
                auth=(user, password),
                max_connection_pool_size=max_pool,
            )
            # Verify connection works
            await self._async_driver.verify_connectivity()
            self._async_driver_initialized = True
            self._record_success()
            logger.info(f"Neo4j async driver initialized: {uri}")
            return self._async_driver
        except Exception as e:
            self._record_failure()
            logger.error(f"Neo4j async connection failed: {e}")
            raise

    async def close_async(self):
        """Close the async Neo4j driver."""
        if self._async_driver:
            await self._async_driver.close()
            self._async_driver = None
            self._async_driver_initialized = False

    # Default transaction timeout in seconds (configurable via env)
    _QUERY_TIMEOUT_SECONDS = float(os.environ.get("NEO4J_QUERY_TIMEOUT", "30.0") or 30.0)

    async def run_query_async(
        self,
        query: str,
        parameters: dict,
        database: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> list[dict]:
        """Execute a Cypher query asynchronously and return results as dicts.

        This is the primary async interface for Neo4j queries.
        Falls back to sync execution in thread pool if async driver unavailable.

        Args:
            query: Cypher query string
            parameters: Query parameters
            database: Target database (defaults to NEO4J_DATABASE env)
            timeout: Query timeout in seconds (defaults to NEO4J_QUERY_TIMEOUT env)
        """
        db = database or self._get_database()
        tx_timeout = timeout if timeout is not None else self._QUERY_TIMEOUT_SECONDS

        try:
            driver = await self._get_async_driver()

            async with driver.session(database=db) as session:
                # Use begin_transaction with explicit timeout
                # Note: execute_read doesn't accept timeout directly - it passes kwargs to tx function
                tx = await session.begin_transaction(timeout=tx_timeout)
                async with tx:
                    result = await tx.run(query, parameters)
                    records = await result.data()
                    # Commit is automatic on exit if no exception, but explicit commit is safer for read-only if we just want to close
                    await tx.commit()
                    return records
        except ImportError:
            # Fallback: run sync query in thread pool
            import asyncio
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self._run_query_sync,
                query,
                parameters,
                db,
                tx_timeout,
            )

    def _run_query_sync(
        self,
        query: str,
        parameters: dict,
        database: str,
        timeout: Optional[float] = None,
    ) -> list[dict]:
        """Sync query execution (used as fallback)."""
        tx_timeout = timeout if timeout is not None else self._QUERY_TIMEOUT_SECONDS
        driver = self._get_driver()

        with driver.session(database=database) as session:
            # Use begin_transaction with explicit timeout
            with session.begin_transaction(timeout=tx_timeout) as tx:
                result = tx.run(query, parameters)
                return [dict(r) for r in result]

    def ensure_graph_store(self, base_collection: str) -> Optional[str]:
        """Ensure Neo4j database and indexes exist.
        
        For Neo4j, we keep a single database and scope by collection name.
        Indexes are created on first use for efficient lookups.
        """
        db = self._get_database()

        if db in self._initialized_databases:
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
                # Language index for language-specific queries
                session.run("""
                    CREATE INDEX symbol_language_idx IF NOT EXISTS
                    FOR (s:Symbol) ON (s.language)
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
                session.run("""
                    CREATE INDEX calls_language_idx IF NOT EXISTS
                    FOR ()-[r:CALLS]-() ON (r.language)
                """)
                # Index for caller_point_id to support "find all edges from chunk X" queries
                session.run("""
                    CREATE INDEX calls_caller_point_idx IF NOT EXISTS
                    FOR ()-[r:CALLS]-() ON (r.caller_point_id)
                """)
                session.run("""
                    CREATE INDEX imports_caller_point_idx IF NOT EXISTS
                    FOR ()-[r:IMPORTS]-() ON (r.caller_point_id)
                """)

            self._initialized_databases.add(db)
            logger.info(f"Neo4j graph store initialized: {db}")

            # Trigger auto-backfill check after initialization
            if base_collection:
                self._check_auto_backfill(base_collection)

            return base_collection or db

        except Exception as e:
            logger.error(f"Failed to initialize Neo4j graph store: {e}")
            return None

    def _count_edges_for_collection(self, collection: str) -> int:
        """Count edges in Neo4j for a specific collection."""
        try:
            driver = self._get_driver()
            db = self._get_database()
            with driver.session(database=db) as session:
                result = session.run("""
                    MATCH ()-[r:CALLS|IMPORTS {collection: $coll}]->()
                    RETURN count(r) AS cnt
                """, coll=collection)
                record = result.single()
                return record["cnt"] if record else 0
        except Exception as e:
            logger.debug(f"Failed to count Neo4j edges: {e}")
            return -1  # Return -1 to indicate error, not empty

    def _check_auto_backfill(self, collection: str) -> None:
        """Check if Neo4j needs backfill from Qdrant and perform it automatically.

        This runs once per collection per process. If Neo4j has no edges but Qdrant
        has data, edges are automatically backfilled.
        """
        global _BACKFILL_CHECKED

        # Skip if disabled via env var
        if AUTO_BACKFILL_DISABLED:
            return

        # Only check once per collection
        if collection in _BACKFILL_CHECKED:
            return
        _BACKFILL_CHECKED.add(collection)

        # Check if Neo4j already has edges for this collection
        edge_count = self._count_edges_for_collection(collection)
        if edge_count != 0:  # Has edges or error occurred
            if edge_count > 0:
                logger.debug(f"Neo4j already has {edge_count} edges for {collection}, skipping backfill")
            return

        # Check if Qdrant has data to backfill from
        try:
            from qdrant_client import QdrantClient
            qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
            qdrant = QdrantClient(url=qdrant_url, timeout=5)

            try:
                info = qdrant.get_collection(collection)
                if info.points_count == 0:
                    logger.debug(f"Qdrant collection {collection} is empty, skipping backfill")
                    return
            except Exception:
                logger.debug(f"Qdrant collection {collection} not found, skipping backfill")
                return

            logger.info(f"Neo4j empty for {collection}, starting auto-backfill from Qdrant ({info.points_count} points)...")
            self._perform_backfill(collection, qdrant)

        except ImportError:
            logger.debug("qdrant_client not available, skipping auto-backfill")
        except Exception as e:
            logger.warning(f"Auto-backfill check failed: {e}")

    def _perform_backfill(self, collection: str, qdrant_client) -> None:
        """Perform backfill from Qdrant to Neo4j."""
        try:
            from scripts.graph_backends.ingest_adapter import extract_call_edges, extract_import_edges
        except ImportError:
            logger.warning("ingest_adapter not available, cannot perform auto-backfill")
            return

        edges = []
        offset = None
        total_edges = 0
        total_points = 0

        try:
            while True:
                result = qdrant_client.scroll(
                    collection_name=collection,
                    limit=500,
                    offset=offset,
                    with_payload=True,
                )
                points, offset = result
                if not points:
                    break

                for p in points:
                    payload = p.payload or {}
                    meta = payload.get("metadata", {})

                    path = meta.get("path", "")
                    symbol_path = meta.get("symbol_path", "") or path
                    repo = meta.get("repo", "")
                    language = meta.get("language", "")
                    start_line = meta.get("start_line")
                    end_line = meta.get("end_line")

                    calls = meta.get("calls", []) or []
                    imports = meta.get("imports", []) or []

                    # Extract edges using ingest_adapter for consistent resolution
                    call_edges = extract_call_edges(
                        symbol_path=symbol_path,
                        calls=calls,
                        path=path,
                        repo=repo,
                        start_line=start_line,
                        end_line=end_line,
                        language=language,
                        caller_point_id=str(p.id),
                        collection=collection,
                        qdrant_client=qdrant_client,
                    )
                    edges.extend(call_edges)

                    import_edges = extract_import_edges(
                        symbol_path=symbol_path,
                        imports=imports,
                        path=path,
                        repo=repo,
                        language=language,
                        caller_point_id=str(p.id),
                        collection=collection,
                        qdrant_client=qdrant_client,
                    )
                    edges.extend(import_edges)

                    total_points += 1

                    # Batch upsert
                    if len(edges) >= 500:
                        count = self.upsert_edges(collection, edges)
                        total_edges += count
                        edges = []
                        logger.debug(f"Auto-backfill progress: {total_points} points, {total_edges} edges")

                if offset is None:
                    break

            # Final batch
            if edges:
                count = self.upsert_edges(collection, edges)
                total_edges += count

            logger.info(f"Auto-backfill complete: {total_edges} edges from {total_points} points")

            # Compute PageRank after populating edges
            if total_edges > 0:
                try:
                    pr_count = self.compute_pagerank(collection)
                    logger.info(f"Auto-backfill: computed PageRank for {pr_count} nodes")
                except Exception as e:
                    logger.warning(f"Auto-backfill: PageRank computation failed: {e}")

        except Exception as e:
            logger.error(f"Auto-backfill failed: {e}")

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
        # ON CREATE SET: populate Symbol node properties when first created
        # ON MATCH SET: update start_line if we now have a more specific value
        for i in range(0, len(calls_edges), batch_size):
            batch = calls_edges[i:i + batch_size]
            try:
                with driver.session(database=db) as session:
                    result = session.run("""
                        UNWIND $edges AS edge
                        MERGE (caller:Symbol {name: edge.caller_symbol, repo: edge.repo, collection: edge.collection, path: edge.caller_path})
                        ON CREATE SET caller.start_line = edge.start_line,
                                      caller.language = edge.language,
                                      caller.indexed_at = timestamp()
                        // On match, prefer non-zero/non-null incoming value if existing is 0/null
                        // This ensures "more specific" values (actual line numbers) overwrite placeholders
                        ON MATCH SET caller.start_line = CASE
                                         WHEN edge.start_line IS NOT NULL AND edge.start_line > 0 THEN edge.start_line
                                         ELSE COALESCE(caller.start_line, edge.start_line)
                                     END,
                                     caller.language = COALESCE(edge.language, caller.language)
                        MERGE (callee:Symbol {name: edge.callee_symbol, repo: edge.repo, collection: edge.collection, path: edge.callee_path})
                        ON CREATE SET callee.indexed_at = timestamp()
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
        # ON CREATE SET: populate Symbol node properties when first created
        for i in range(0, len(import_edges), batch_size):
            batch = import_edges[i:i + batch_size]
            try:
                with driver.session(database=db) as session:
                    result = session.run("""
                        UNWIND $edges AS edge
                        MERGE (importer:Symbol {name: edge.caller_symbol, repo: edge.repo, collection: edge.collection, path: edge.caller_path})
                        ON CREATE SET importer.language = edge.language,
                                      importer.indexed_at = timestamp()
                        // Prefer incoming language value (consistent with CALLS upsert behavior)
                        ON MATCH SET importer.language = COALESCE(edge.language, importer.language)
                        MERGE (imported:Symbol {name: edge.callee_symbol, repo: edge.repo, collection: edge.collection, path: edge.callee_path})
                        ON CREATE SET imported.indexed_at = timestamp()
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

        # Compute simple degree-based importance scores for new nodes
        # This avoids requiring Neo4j GDS (Graph Data Science) library
        if total > 0:
            try:
                self._compute_simple_pagerank(collection)
            except Exception as e:
                logger.warning(f"Failed to compute pagerank: {e}")

        return total

    def _compute_simple_pagerank(self, collection: str) -> int:
        """Compute degree-based importance scores (simple PageRank approximation).

        This sets n.pagerank = (in_degree / max_in_degree) for all nodes.
        No GDS library required - uses simple Cypher aggregation.
        """
        driver = self._get_driver()
        db = self._get_database()

        try:
            with driver.session(database=db) as session:
                # Two-pass approach:
                # 1. Calculate max in-degree for normalization
                # 2. Set pagerank as normalized in-degree
                result = session.run("""
                    MATCH (n:Symbol {collection: $collection})
                    OPTIONAL MATCH (n)<-[r:CALLS|IMPORTS]-()
                    WITH n, count(r) AS in_degree
                    WITH max(in_degree) AS max_degree
                    MATCH (n2:Symbol {collection: $collection})
                    OPTIONAL MATCH (n2)<-[r2:CALLS|IMPORTS]-()
                    WITH n2, count(r2) AS in_degree, max_degree
                    WHERE max_degree > 0
                    SET n2.pagerank = toFloat(in_degree) / toFloat(max_degree)
                    RETURN count(n2) AS updated
                """, collection=collection)
                record = result.single()
                updated = record["updated"] if record else 0
                if updated > 0:
                    logger.debug(f"Updated pagerank for {updated} symbols in {collection}")
                return updated
        except Exception as e:
            logger.warning(f"Pagerank computation failed: {e}")
            return 0

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
                # Note: count(r) must be computed BEFORE DELETE, not after
                if repo:
                    result = session.run("""
                        MATCH ()-[r]->()
                        WHERE r.caller_path = $path AND r.repo = $repo AND r.collection = $collection
                        WITH r, count(r) AS deleted
                        DELETE r
                        RETURN deleted
                    """, {"path": norm_path, "repo": repo, "collection": collection})
                else:
                    result = session.run("""
                        MATCH ()-[r]->()
                        WHERE r.caller_path = $path AND r.collection = $collection
                        WITH r, count(r) AS deleted
                        DELETE r
                        RETURN deleted
                    """, {"path": norm_path, "collection": collection})

                record = result.single()
                return record["deleted"] if record else 0

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
        """Find all callers of a symbol using Cypher.

        Supports both exact matches and class-level queries (includes methods).
        For "MyClass", also matches callers of "MyClass.method" etc.
        """
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)
        # Pattern for class + methods: exact match OR starts with "Class."
        symbol_prefix = f"{symbol}."

        try:
            with driver.session(database=db) as session:
                if repo and repo != "*":
                    result = session.run("""
                        MATCH (caller:Symbol {collection: $collection})-[r:CALLS]->(callee:Symbol {collection: $collection})
                        WHERE (callee.name = $symbol OR callee.name STARTS WITH $symbol_prefix)
                              AND r.collection = $collection AND (r.repo = $repo OR callee.repo = $repo)
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
                    """, {"symbol": symbol, "symbol_prefix": symbol_prefix, "repo": repo, "collection": collection, "limit": limit})
                else:
                    result = session.run("""
                        MATCH (caller:Symbol {collection: $collection})-[r:CALLS]->(callee:Symbol {collection: $collection})
                        WHERE (callee.name = $symbol OR callee.name STARTS WITH $symbol_prefix)
                              AND r.collection = $collection
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
                    """, {"symbol": symbol, "symbol_prefix": symbol_prefix, "collection": collection, "limit": limit})

                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"Failed to get callers for {symbol}: {e}")
            raise  # Let caller handle the error

    def get_callees(
        self,
        graph_store: str,
        symbol: str,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find all symbols called by a symbol using Cypher.

        Supports both exact matches and class-level queries (includes methods).
        For "MyClass", also matches "MyClass.method" etc.
        """
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)
        # Pattern for class + methods: exact match OR starts with "Class."
        symbol_prefix = f"{symbol}."

        try:
            with driver.session(database=db) as session:
                if repo and repo != "*":
                    result = session.run("""
                        MATCH (caller:Symbol {collection: $collection})-[r:CALLS]->(callee:Symbol {collection: $collection})
                        WHERE (caller.name = $symbol OR caller.name STARTS WITH $symbol_prefix)
                              AND r.collection = $collection AND (r.repo = $repo OR caller.repo = $repo)
                        RETURN caller.name as caller_symbol,
                               callee.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.callee_path as callee_path,
                               r.start_line as start_line,
                               r.end_line as end_line,
                               r.language as language,
                               caller.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"symbol": symbol, "symbol_prefix": symbol_prefix, "repo": repo, "collection": collection, "limit": limit})
                else:
                    result = session.run("""
                        MATCH (caller:Symbol {collection: $collection})-[r:CALLS]->(callee:Symbol {collection: $collection})
                        WHERE (caller.name = $symbol OR caller.name STARTS WITH $symbol_prefix)
                              AND r.collection = $collection
                        RETURN caller.name as caller_symbol,
                               callee.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.callee_path as callee_path,
                               r.start_line as start_line,
                               r.end_line as end_line,
                               r.language as language,
                               caller.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"symbol": symbol, "symbol_prefix": symbol_prefix, "collection": collection, "limit": limit})

                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"Failed to get callees for {symbol}: {e}")
            raise  # Let caller handle the error

    def get_importers(
        self,
        graph_store: str,
        module: str,
        repo: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find all files that import a module using Cypher.

        Supports both exact matches and submodule queries.
        For "mypackage", also matches importers of "mypackage.submodule" etc.
        """
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)
        # Pattern for module + submodules: exact match OR starts with "module."
        module_prefix = f"{module}."

        try:
            with driver.session(database=db) as session:
                if repo and repo != "*":
                    result = session.run("""
                        MATCH (importer:Symbol {collection: $collection})-[r:IMPORTS]->(imported:Symbol {collection: $collection})
                        WHERE (imported.name = $module OR imported.name STARTS WITH $module_prefix)
                              AND r.collection = $collection AND (r.repo = $repo OR imported.repo = $repo)
                        RETURN importer.name as caller_symbol,
                               imported.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.language as language,
                               imported.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"module": module, "module_prefix": module_prefix, "repo": repo, "collection": collection, "limit": limit})
                else:
                    result = session.run("""
                        MATCH (importer:Symbol {collection: $collection})-[r:IMPORTS]->(imported:Symbol {collection: $collection})
                        WHERE (imported.name = $module OR imported.name STARTS WITH $module_prefix)
                              AND r.collection = $collection
                        RETURN importer.name as caller_symbol,
                               imported.name as callee_symbol,
                               r.caller_path as caller_path,
                               r.language as language,
                               imported.repo as repo,
                               r.edge_id as edge_id,
                               r.caller_point_id as caller_point_id
                        LIMIT $limit
                    """, {"module": module, "module_prefix": module_prefix, "collection": collection, "limit": limit})

                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"Failed to get importers for {module}: {e}")
            raise  # Let caller handle the error

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
        language: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve an import to its source file path via Neo4j.

        Args:
            graph_store: Collection/graph store name
            import_name: Dotted import name (e.g., "scripts.utils")
            repo: Optional repo filter
            language: Programming language for extension detection
        """
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)

        # Convert dotted import to file path pattern
        module_parts = import_name.replace(".", "/")

        # Language-specific file extensions (supports 16+ languages)
        extensions_by_language = {
            "python": [".py", ".pyi"],
            "javascript": [".js", ".mjs", ".cjs"],
            "typescript": [".ts", ".tsx", ".mts", ".cts"],
            "go": [".go"],
            "rust": [".rs"],
            "java": [".java"],
            "kotlin": [".kt", ".kts"],
            "c": [".c", ".h"],
            "cpp": [".cpp", ".cc", ".cxx", ".hpp", ".h"],
            "csharp": [".cs"],
            "ruby": [".rb"],
            "php": [".php"],
            "swift": [".swift"],
            "scala": [".scala"],
            "elixir": [".ex", ".exs"],
        }

        # Get extensions to try
        if language and language.lower() in extensions_by_language:
            extensions = extensions_by_language[language.lower()]
        else:
            # Default: try common extensions
            extensions = [".py", ".ts", ".js", ".go", ".rs", ".java"]

        try:
            with driver.session(database=db) as session:
                # Try each extension until we find a match
                for ext in extensions:
                    suffix = f"/{module_parts}{ext}"
                    result = session.run("""
                        MATCH (s:Symbol {collection: $collection})
                        WHERE s.path ENDS WITH $suffix
                        RETURN s.path as path
                        LIMIT 1
                    """, {"collection": collection, "suffix": suffix})

                    record = result.single()
                    if record:
                        return record["path"]

                # Also try index file patterns (e.g., module/index.ts)
                index_patterns = ["/__init__.py", "/index.ts", "/index.js", "/mod.rs"]
                for pattern in index_patterns:
                    suffix = f"/{module_parts}{pattern}"
                    result = session.run("""
                        MATCH (s:Symbol {collection: $collection})
                        WHERE s.path ENDS WITH $suffix
                        RETURN s.path as path
                        LIMIT 1
                    """, {"collection": collection, "suffix": suffix})

                    record = result.single()
                    if record:
                        return record["path"]

                return None

        except Exception as e:
            logger.debug(f"Failed to resolve import {import_name}: {e}")
            return None

    def compute_pagerank(
        self,
        graph_store: str,
        repo: Optional[str] = None,
        timeout: int = 120,
    ) -> int:
        """Compute PageRank for code symbols (importance scoring).

        Uses simple in-degree approximation as a fallback since GDS may not be available.
        All nodes get a base rank (0.001), nodes with incoming edges get rank proportional
        to in-degree.

        Args:
            graph_store: Graph store name (collection)
            repo: Optional repository filter
            timeout: Transaction timeout in seconds

        Returns:
            Count of nodes updated
        """
        driver = self._get_driver()
        db = self._get_database()
        collection = self._get_collection(graph_store)

        try:
            with driver.session(database=db) as session:
                # Simple in-degree approximation with OPTIONAL MATCH
                # Ensures ALL nodes get a base rank, not just those with incoming edges
                with session.begin_transaction(timeout=timeout) as tx:
                    if repo and repo != "*":
                        result = tx.run("""
                            MATCH (n:Symbol {collection: $collection})
                            WHERE n.repo = $repo
                            OPTIONAL MATCH (n)<-[r:CALLS|IMPORTS]-()
                            WITH n, count(r) AS in_degree
                            SET n.pagerank = CASE WHEN in_degree > 0
                                                  THEN toFloat(in_degree) / 100.0
                                                  ELSE 0.001 END
                            RETURN count(n) AS cnt
                        """, collection=collection, repo=repo)
                    else:
                        result = tx.run("""
                            MATCH (n:Symbol {collection: $collection})
                            OPTIONAL MATCH (n)<-[r:CALLS|IMPORTS]-()
                            WITH n, count(r) AS in_degree
                            SET n.pagerank = CASE WHEN in_degree > 0
                                                  THEN toFloat(in_degree) / 100.0
                                                  ELSE 0.001 END
                            RETURN count(n) AS cnt
                        """, collection=collection)

                    record = result.single()
                    cnt = record["cnt"] if record else 0
                    tx.commit()
                    logger.info(f"Computed PageRank for {cnt} nodes in {collection}")
                    return cnt

        except Exception as e:
            logger.error(f"Failed to compute PageRank: {e}")
            return 0