# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Neo4j Knowledge Graph Service - Graph RAG Brain.

This is the core knowledge graph that powers advanced code understanding:
- Rich semantic relationships beyond simple calls/imports
- Graph algorithms (PageRank, community detection, path finding)
- Embeddings for semantic similarity
- Async batch operations for production scale
- Context retrieval for RAG augmentation

The knowledge graph is the "brain" that understands code relationships.
"""
from __future__ import annotations

import atexit
import asyncio
import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

# Support both package and standalone imports
try:
    from .schema import NodeType, RelationType, GraphNode, GraphRelationship
except ImportError:
    from schema import NodeType, RelationType, GraphNode, GraphRelationship

logger = logging.getLogger(__name__)

__all__ = [
    # Main class
    "Neo4jKnowledgeGraph",
    "get_knowledge_graph",
    # Stats
    "KnowledgeGraphStats",
    # Configuration
    "BATCH_SIZE_NODES",
    "BATCH_SIZE_RELS",
]

# Configuration
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
NEO4J_MAX_POOL_SIZE = int(os.environ.get("NEO4J_MAX_POOL_SIZE", "50") or 50)

# Fail fast on empty password when Neo4j is explicitly enabled
_NEO4J_GRAPH_ENABLED = os.environ.get("NEO4J_GRAPH", "").strip().lower() in {"1", "true", "yes", "on"}
if _NEO4J_GRAPH_ENABLED and not NEO4J_PASSWORD:
    logger.warning(
        "NEO4J_GRAPH=1 but NEO4J_PASSWORD is empty. "
        "Set NEO4J_PASSWORD environment variable for production use."
    )

# Allowlist of valid node type labels for Cypher queries (security)
_VALID_NODE_LABELS: frozenset[str] = frozenset(nt.value for nt in NodeType)

# Batch sizes for production
BATCH_SIZE_NODES = int(os.environ.get("NEO4J_BATCH_NODES", "500") or 500)
BATCH_SIZE_RELS = int(os.environ.get("NEO4J_BATCH_RELS", "1000") or 1000)

# Maximum allowed depth for graph traversals (security limit)
MAX_GRAPH_DEPTH = 10

# Transaction timeout in seconds (default: 30s, long queries like PageRank: 120s)
DEFAULT_TX_TIMEOUT = int(os.environ.get("NEO4J_TX_TIMEOUT", "30") or 30)
LONG_TX_TIMEOUT = int(os.environ.get("NEO4J_LONG_TX_TIMEOUT", "120") or 120)


def _sanitize_depth(depth: int, default: int = 2, max_depth: int = MAX_GRAPH_DEPTH) -> int:
    """Sanitize depth parameter for Cypher queries to prevent injection.

    Args:
        depth: User-provided depth value
        default: Default value if depth is invalid
        max_depth: Maximum allowed depth

    Returns:
        Sanitized integer depth between 1 and max_depth
    """
    try:
        d = int(depth)
        return max(1, min(d, max_depth))
    except (TypeError, ValueError):
        return default

# Thread pool for async operations
_EXECUTOR: Optional[ThreadPoolExecutor] = None


def _get_executor() -> ThreadPoolExecutor:
    """Get thread pool executor for async operations."""
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=4)
    return _EXECUTOR


@dataclass
class KnowledgeGraphStats:
    """Statistics about the knowledge graph."""
    node_count: int = 0
    relationship_count: int = 0
    file_count: int = 0
    class_count: int = 0
    function_count: int = 0
    community_count: int = 0
    avg_pagerank: float = 0.0


class Neo4jKnowledgeGraph:
    """
    Production-ready Neo4j Knowledge Graph for Graph RAG.

    Features:
    - Async batch operations with connection pooling
    - Rich node types and semantic relationships
    - Graph algorithms (PageRank, communities, path finding)
    - Embedding storage for semantic similarity
    - Subgraph extraction for RAG context
    """

    # Class-level cache for initialized databases (shared across instances)
    # Protected by _db_init_lock for thread safety
    _initialized_databases: Set[str] = set()
    _db_init_lock: threading.Lock = threading.Lock()

    def __init__(self):
        """Initialize knowledge graph service."""
        self._driver = None
        self._driver_lock = threading.Lock()
        self._uri = NEO4J_URI
        self._user = NEO4J_USER
        self._password = NEO4J_PASSWORD
        self._database = NEO4J_DATABASE

    def _get_driver(self):
        """Get Neo4j driver with connection pooling and health check."""
        if self._driver is not None:
            return self._driver

        with self._driver_lock:
            # Double-check after acquiring lock
            if self._driver is not None:
                return self._driver

            try:
                from neo4j import GraphDatabase
            except ImportError:
                raise ImportError("neo4j package required: pip install neo4j")

            self._driver = GraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
                max_connection_pool_size=NEO4J_MAX_POOL_SIZE,
            )

            # Verify connectivity before returning
            try:
                self._driver.verify_connectivity()
                logger.info(f"Neo4j knowledge graph connected: {self._uri}")
            except Exception as e:
                logger.error(f"Neo4j connectivity check failed: {e}")
                self._driver.close()
                self._driver = None
                raise

            return self._driver

    def close(self):
        """Close driver connection."""
        with self._driver_lock:
            if self._driver:
                self._driver.close()
                self._driver = None



    def initialize_schema(self) -> bool:
        """Initialize Neo4j schema with indexes and constraints."""
        with self._db_init_lock:
            if self._database in self._initialized_databases:
                return True

            driver = self._get_driver()

            try:
                with driver.session(database=self._database) as session:
                    # Node indexes for each type - validate against allowlist
                    for node_type in NodeType:
                        label = node_type.value
                        # Security: Validate label is in allowlist before using in Cypher
                        if label not in _VALID_NODE_LABELS:
                            logger.warning(f"Skipping unknown node type: {label}")
                            continue

                        # Use validated label in index creation
                        idx_prefix = label.lower()
                        session.run(f"""
                            CREATE INDEX {idx_prefix}_id_idx IF NOT EXISTS
                            FOR (n:{label}) ON (n.id)
                        """)
                        session.run(f"""
                            CREATE INDEX {idx_prefix}_name_idx IF NOT EXISTS
                            FOR (n:{label}) ON (n.name)
                        """)
                        session.run(f"""
                            CREATE INDEX {idx_prefix}_repo_idx IF NOT EXISTS
                            FOR (n:{label}) ON (n.repo)
                        """)

                    # Composite indexes for common queries
                    session.run("""
                        CREATE INDEX function_path_idx IF NOT EXISTS
                        FOR (n:Function) ON (n.path, n.name)
                    """)
                    session.run("""
                        CREATE INDEX class_path_idx IF NOT EXISTS
                        FOR (n:Class) ON (n.path, n.name)
                    """)

                    # Full-text search index for docstrings
                    try:
                        session.run("""
                            CREATE FULLTEXT INDEX docstring_search IF NOT EXISTS
                            FOR (n:Function|Class|Method)
                            ON EACH [n.docstring, n.name]
                        """)
                    except Exception:
                        pass  # Fulltext may already exist

                self._initialized_databases.add(self._database)
                logger.info(f"Neo4j schema initialized for {self._database}")
                return True

            except Exception as e:
                logger.error(f"Failed to initialize Neo4j schema: {e}")
                return False

    # =========================================================================
    # Batch Node Operations
    # =========================================================================

    def upsert_nodes(
        self,
        nodes: List[GraphNode],
        batch_size: int = BATCH_SIZE_NODES,
    ) -> int:
        """Batch upsert nodes into knowledge graph."""
        if not nodes:
            return 0

        driver = self._get_driver()
        self.initialize_schema()

        total = 0
        for i in range(0, len(nodes), batch_size):
            batch = nodes[i:i + batch_size]
            # Group by node type for efficient MERGE
            by_type: Dict[NodeType, List[GraphNode]] = {}
            for node in batch:
                by_type.setdefault(node.node_type, []).append(node)

            with driver.session(database=self._database) as session:
                for node_type, type_nodes in by_type.items():
                    params = [n.to_neo4j_props() for n in type_nodes]
                    result = session.run(f"""
                        UNWIND $nodes AS node
                        MERGE (n:{node_type.value} {{id: node.id}})
                        SET n += node
                        RETURN count(n) AS cnt
                    """, nodes=params)
                    total += result.single()["cnt"]

        logger.debug(f"Upserted {total} nodes")
        return total

    def upsert_relationships(
        self,
        relationships: List[GraphRelationship],
        batch_size: int = BATCH_SIZE_RELS,
    ) -> int:
        """Batch upsert relationships into knowledge graph."""
        if not relationships:
            return 0

        driver = self._get_driver()
        self.initialize_schema()

        total = 0
        for i in range(0, len(relationships), batch_size):
            batch = relationships[i:i + batch_size]
            # Group by relationship type
            by_type: Dict[RelationType, List[GraphRelationship]] = {}
            for rel in batch:
                by_type.setdefault(rel.rel_type, []).append(rel)

            with driver.session(database=self._database) as session:
                for rel_type, type_rels in by_type.items():
                    params = [
                        {
                            "source_id": r.source_id,
                            "target_id": r.target_id,
                            **r.to_neo4j_props()
                        }
                        for r in type_rels
                    ]
                    # Use MATCH for existing nodes, create rel
                    result = session.run(f"""
                        UNWIND $rels AS rel
                        MATCH (a {{id: rel.source_id}})
                        MATCH (b {{id: rel.target_id}})
                        MERGE (a)-[r:{rel_type.value}]->(b)
                        SET r.weight = rel.weight,
                            r.start_line = rel.start_line,
                            r.caller_path = rel.caller_path,
                            r.repo = rel.repo
                        RETURN count(r) AS cnt
                    """, rels=params)
                    total += result.single()["cnt"]

        logger.debug(f"Upserted {total} relationships")
        return total

    def delete_by_repo(self, repo: str) -> int:
        """Delete all nodes and relationships for a repository."""
        driver = self._get_driver()

        with driver.session(database=self._database) as session:
            result = session.run("""
                MATCH (n {repo: $repo})
                DETACH DELETE n
                RETURN count(n) AS deleted
            """, repo=repo)
            deleted = result.single()["deleted"]

        logger.info(f"Deleted {deleted} nodes for repo {repo}")
        return deleted

    def delete_by_path(self, path: str, repo: str) -> int:
        """Delete all nodes in a specific file path."""
        driver = self._get_driver()

        with driver.session(database=self._database) as session:
            result = session.run("""
                MATCH (n {path: $path, repo: $repo})
                DETACH DELETE n
                RETURN count(n) AS deleted
            """, path=path, repo=repo)
            deleted = result.single()["deleted"]

        return deleted

    # =========================================================================
    # Graph Algorithms
    # =========================================================================

    def compute_pagerank(
        self,
        repo: Optional[str] = None,
        iterations: int = 20,
        damping: float = 0.85,
        timeout: int = LONG_TX_TIMEOUT,
    ) -> int:
        """Compute PageRank for code symbols (importance scoring).

        Args:
            repo: Optional repository filter
            iterations: Number of PageRank iterations
            damping: PageRank damping factor
            timeout: Transaction timeout in seconds (default: LONG_TX_TIMEOUT)
        """
        driver = self._get_driver()

        with driver.session(database=self._database) as session:
            # Use GDS if available, otherwise simple approximation
            try:
                # Check if GDS is available (use auto-commit, not long running)
                session.run("CALL gds.version()")

                # Build node and relationship queries with proper parameterization
                if repo:
                    node_query = "MATCH (n) WHERE n.repo = $repo RETURN id(n) AS id"
                    rel_query = """MATCH (a)-[r:CALLS|IMPORTS]->(b)
                                   WHERE a.repo = $repo
                                   RETURN id(a) AS source, id(b) AS target, r.weight AS weight"""
                else:
                    node_query = "MATCH (n) RETURN id(n) AS id"
                    rel_query = """MATCH (a)-[r:CALLS|IMPORTS]->(b)
                                   RETURN id(a) AS source, id(b) AS target, r.weight AS weight"""

                # Use explicit transaction with timeout for expensive GDS operations
                with session.begin_transaction(timeout=timeout) as tx:
                    # Project graph with parameterized queries
                    tx.run("""
                        CALL gds.graph.project.cypher(
                            'code_graph',
                            $nodeQuery,
                            $relQuery,
                            {parameters: {repo: $repo}}
                        )
                    """, nodeQuery=node_query, relQuery=rel_query, repo=repo)

                    tx.run("""
                        CALL gds.pageRank.write('code_graph', {
                            maxIterations: $iterations,
                            dampingFactor: $damping,
                            writeProperty: 'pagerank'
                        })
                    """, iterations=iterations, damping=damping)

                    tx.run("CALL gds.graph.drop('code_graph')")
                    tx.commit()

            except Exception:
                # Fallback: simple in-degree approximation with timeout
                with session.begin_transaction(timeout=timeout) as tx:
                    if repo:
                        result = tx.run("""
                            MATCH (n)<-[r:CALLS|IMPORTS]-()
                            WHERE n.repo = $repo
                            WITH n, count(r) AS in_degree
                            SET n.pagerank = toFloat(in_degree) / 100.0
                            RETURN count(n) AS cnt
                        """, repo=repo)
                    else:
                        result = tx.run("""
                            MATCH (n)<-[r:CALLS|IMPORTS]-()
                            WITH n, count(r) AS in_degree
                            SET n.pagerank = toFloat(in_degree) / 100.0
                            RETURN count(n) AS cnt
                        """)
                    cnt = result.single()["cnt"]
                    tx.commit()
                    return cnt

        return 0

    def detect_communities(
        self,
        repo: Optional[str] = None,
        timeout: int = LONG_TX_TIMEOUT,
    ) -> int:
        """Detect code communities using label propagation.

        Args:
            repo: Optional repository filter
            timeout: Transaction timeout in seconds (default: LONG_TX_TIMEOUT)
        """
        driver = self._get_driver()

        with driver.session(database=self._database) as session:
            try:
                # Check if GDS available
                session.run("CALL gds.version()")

                # Build queries with proper parameterization
                if repo:
                    node_query = "MATCH (n) WHERE n.repo = $repo RETURN id(n) AS id"
                    rel_query = """MATCH (a)-[r:CALLS|IMPORTS|INHERITS_FROM]->(b)
                                   WHERE a.repo = $repo
                                   RETURN id(a) AS source, id(b) AS target"""
                else:
                    node_query = "MATCH (n) RETURN id(n) AS id"
                    rel_query = """MATCH (a)-[r:CALLS|IMPORTS|INHERITS_FROM]->(b)
                                   RETURN id(a) AS source, id(b) AS target"""

                # Use explicit transaction with timeout for expensive GDS operations
                with session.begin_transaction(timeout=timeout) as tx:
                    tx.run("""
                        CALL gds.graph.project.cypher(
                            'community_graph',
                            $nodeQuery,
                            $relQuery,
                            {parameters: {repo: $repo}}
                        )
                    """, nodeQuery=node_query, relQuery=rel_query, repo=repo)

                    tx.run("""
                        CALL gds.louvain.write('community_graph', {
                            writeProperty: 'community_id'
                        })
                    """)

                    tx.run("CALL gds.graph.drop('community_graph')")
                    tx.commit()

            except Exception:
                # Fallback: assign community by file path with timeout
                with session.begin_transaction(timeout=timeout) as tx:
                    if repo:
                        result = tx.run("""
                            MATCH (n)
                            WHERE n.repo = $repo
                            WITH n, CASE
                                WHEN n.path IS NOT NULL
                                THEN toInteger(abs(reduce(h = 0, c IN split(n.path, '/') | h + size(c)))) % 100
                                ELSE 0
                            END AS community
                            SET n.community_id = community
                            RETURN count(n) AS cnt
                        """, repo=repo)
                    else:
                        result = tx.run("""
                            MATCH (n)
                            WITH n, CASE
                                WHEN n.path IS NOT NULL
                                THEN toInteger(abs(reduce(h = 0, c IN split(n.path, '/') | h + size(c)))) % 100
                                ELSE 0
                            END AS community
                            SET n.community_id = community
                            RETURN count(n) AS cnt
                        """)
                    cnt = result.single()["cnt"]
                    tx.commit()
                    return cnt

        return 0

    # =========================================================================
    # Query Operations - Graph RAG Context Retrieval
    # =========================================================================

    def find_symbol(
        self,
        name: str,
        repo: Optional[str] = None,
        node_type: Optional[NodeType] = None,
    ) -> List[Dict[str, Any]]:
        """Find symbols by name (fuzzy match)."""
        driver = self._get_driver()

        type_filter = f":{node_type.value}" if node_type else ""
        repo_filter = "AND n.repo = $repo" if repo else ""

        with driver.session(database=self._database) as session:
            result = session.run(f"""
                MATCH (n{type_filter})
                WHERE n.name =~ $pattern {repo_filter}
                RETURN n.id AS id, n.name AS name, labels(n)[0] AS type,
                       n.path AS path, n.start_line AS start_line,
                       n.signature AS signature, n.docstring AS docstring,
                       n.pagerank AS importance
                ORDER BY n.pagerank DESC
                LIMIT 20
            """, pattern=f"(?i).*{name}.*", repo=repo)
            return [dict(r) for r in result]

    def get_callers(
        self,
        symbol_name: str,
        repo: Optional[str] = None,
        depth: int = 1,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get all callers of a symbol (with depth for transitive)."""
        driver = self._get_driver()
        safe_depth = _sanitize_depth(depth, default=1)

        repo_filter = "AND n.repo = $repo" if repo else ""

        with driver.session(database=self._database) as session:
            result = session.run(f"""
                MATCH (target {{name: $name}})
                MATCH (caller)-[:CALLS*1..{safe_depth}]->(target)
                WHERE caller <> target {repo_filter.replace('n', 'caller')}
                RETURN DISTINCT
                    caller.id AS id, caller.name AS name, labels(caller)[0] AS type,
                    caller.path AS path, caller.start_line AS start_line,
                    caller.signature AS signature,
                    size((caller)-[:CALLS]->()) AS call_count
                ORDER BY caller.pagerank DESC
                LIMIT $limit
            """, name=symbol_name, repo=repo, limit=limit)
            return [dict(r) for r in result]

    def get_callees(
        self,
        symbol_name: str,
        repo: Optional[str] = None,
        depth: int = 1,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get all symbols called by a symbol (with depth for transitive)."""
        driver = self._get_driver()
        safe_depth = _sanitize_depth(depth, default=1)

        repo_filter = "AND n.repo = $repo" if repo else ""

        with driver.session(database=self._database) as session:
            result = session.run(f"""
                MATCH (source {{name: $name}})
                MATCH (source)-[:CALLS*1..{safe_depth}]->(callee)
                WHERE source <> callee {repo_filter.replace('n', 'callee')}
                RETURN DISTINCT
                    callee.id AS id, callee.name AS name, labels(callee)[0] AS type,
                    callee.path AS path, callee.start_line AS start_line,
                    callee.signature AS signature
                ORDER BY callee.pagerank DESC
                LIMIT $limit
            """, name=symbol_name, repo=repo, limit=limit)
            return [dict(r) for r in result]

    def get_inheritance_chain(
        self,
        class_name: str,
        repo: Optional[str] = None,
        direction: str = "up",  # up = ancestors, down = descendants
    ) -> List[Dict[str, Any]]:
        """Get class inheritance chain."""
        driver = self._get_driver()

        # Add repo filter when specified to avoid cross-repo collisions
        repo_filter = "WHERE c.repo = $repo" if repo else ""

        if direction == "up":
            # Get ancestors (what this class inherits from)
            query = f"""
                MATCH (c:Class {{name: $name}})
                {repo_filter}
                MATCH path = (c)-[:INHERITS_FROM*1..10]->(ancestor)
                RETURN DISTINCT
                    ancestor.id AS id, ancestor.name AS name,
                    ancestor.path AS path, ancestor.signature AS signature,
                    length(path) AS distance
                ORDER BY distance
            """
        else:
            # Get descendants (what inherits from this class)
            query = f"""
                MATCH (c:Class {{name: $name}})
                {repo_filter}
                MATCH path = (descendant)-[:INHERITS_FROM*1..10]->(c)
                RETURN DISTINCT
                    descendant.id AS id, descendant.name AS name,
                    descendant.path AS path, descendant.signature AS signature,
                    length(path) AS distance
                ORDER BY distance
            """

        with driver.session(database=self._database) as session:
            result = session.run(query, name=class_name, repo=repo)
            return [dict(r) for r in result]

    def impact_analysis(
        self,
        symbol_name: str,
        repo: Optional[str] = None,
        max_depth: int = 3,
    ) -> Dict[str, Any]:
        """Analyze impact of changing a symbol."""
        driver = self._get_driver()
        safe_depth = _sanitize_depth(max_depth, default=3)

        with driver.session(database=self._database) as session:
            # Get direct and transitive callers with proper parameterized query
            if repo:
                callers = session.run(f"""
                    MATCH (target {{name: $name}})
                    WHERE target.repo = $repo
                    MATCH path = (caller)-[:CALLS*1..{safe_depth}]->(target)
                    WHERE caller <> target
                    RETURN caller.name AS name, caller.path AS path,
                           labels(caller)[0] AS type, length(path) AS depth
                    ORDER BY depth
                """, name=symbol_name, repo=repo)
            else:
                callers = session.run(f"""
                    MATCH (target {{name: $name}})
                    MATCH path = (caller)-[:CALLS*1..{safe_depth}]->(target)
                    WHERE caller <> target
                    RETURN caller.name AS name, caller.path AS path,
                           labels(caller)[0] AS type, length(path) AS depth
                    ORDER BY depth
                """, name=symbol_name)

            caller_list = [dict(r) for r in callers]

            # Get affected files
            affected_files = set()
            for c in caller_list:
                if c.get("path"):
                    affected_files.add(c["path"])

            # Count by depth
            by_depth: Dict[int, int] = {}
            for c in caller_list:
                d = c.get("depth", 1)
                by_depth[d] = by_depth.get(d, 0) + 1

            return {
                "symbol": symbol_name,
                "total_impacted": len(caller_list),
                "affected_files": len(affected_files),
                "files": list(affected_files)[:20],
                "by_depth": by_depth,
                "callers": caller_list[:50],
            }

    def find_similar(
        self,
        symbol_name: str,
        repo: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Find similar symbols based on call patterns."""
        driver = self._get_driver()

        with driver.session(database=self._database) as session:
            # Jaccard similarity on callees with proper parameterization
            if repo:
                result = session.run("""
                    MATCH (target {name: $name})
                    WHERE target.repo = $repo
                    MATCH (target)-[:CALLS]->(shared)<-[:CALLS]-(similar)
                    WHERE similar <> target
                    WITH target, similar, count(shared) AS shared_calls
                    MATCH (target)-[:CALLS]->(t_calls)
                    WITH similar, shared_calls, count(DISTINCT t_calls) AS target_calls
                    MATCH (similar)-[:CALLS]->(s_calls)
                    WITH similar, shared_calls, target_calls, count(DISTINCT s_calls) AS similar_calls
                    WITH similar,
                         toFloat(shared_calls) / (target_calls + similar_calls - shared_calls) AS jaccard
                    WHERE jaccard > 0.1
                    RETURN similar.id AS id, similar.name AS name, labels(similar)[0] AS type,
                           similar.path AS path, similar.signature AS signature,
                           jaccard AS similarity
                    ORDER BY jaccard DESC
                    LIMIT $limit
                """, name=symbol_name, repo=repo, limit=limit)
            else:
                result = session.run("""
                    MATCH (target {name: $name})
                    MATCH (target)-[:CALLS]->(shared)<-[:CALLS]-(similar)
                    WHERE similar <> target
                    WITH target, similar, count(shared) AS shared_calls
                    MATCH (target)-[:CALLS]->(t_calls)
                    WITH similar, shared_calls, count(DISTINCT t_calls) AS target_calls
                    MATCH (similar)-[:CALLS]->(s_calls)
                    WITH similar, shared_calls, target_calls, count(DISTINCT s_calls) AS similar_calls
                    WITH similar,
                         toFloat(shared_calls) / (target_calls + similar_calls - shared_calls) AS jaccard
                    WHERE jaccard > 0.1
                    RETURN similar.id AS id, similar.name AS name, labels(similar)[0] AS type,
                           similar.path AS path, similar.signature AS signature,
                           jaccard AS similarity
                    ORDER BY jaccard DESC
                    LIMIT $limit
                """, name=symbol_name, limit=limit)
            return [dict(r) for r in result]

    def get_subgraph_context(
        self,
        symbol_name: str,
        repo: Optional[str] = None,
        radius: int = 2,
        include_code: bool = False,
    ) -> Dict[str, Any]:
        """
        Extract subgraph context around a symbol for RAG augmentation.

        Returns nodes and relationships within N hops of the target,
        useful for providing context to the LLM.
        """
        driver = self._get_driver()
        safe_radius = _sanitize_depth(radius, default=2, max_depth=5)

        with driver.session(database=self._database) as session:
            # Try APOC first with proper parameterization
            try:
                if repo:
                    result = session.run("""
                        MATCH (center {name: $name})
                        WHERE center.repo = $repo
                        CALL apoc.path.subgraphAll(center, {
                            maxLevel: $radius,
                            relationshipFilter: 'CALLS|IMPORTS|INHERITS_FROM|CONTAINS'
                        })
                        YIELD nodes, relationships
                        RETURN nodes, relationships
                    """, name=symbol_name, repo=repo, radius=safe_radius)
                else:
                    result = session.run("""
                        MATCH (center {name: $name})
                        CALL apoc.path.subgraphAll(center, {
                            maxLevel: $radius,
                            relationshipFilter: 'CALLS|IMPORTS|INHERITS_FROM|CONTAINS'
                        })
                        YIELD nodes, relationships
                        RETURN nodes, relationships
                    """, name=symbol_name, radius=safe_radius)

                record = result.single()
                if record:
                    nodes = []
                    for n in record["nodes"]:
                        node_data = dict(n)
                        node_data["labels"] = list(n.labels)
                        if not include_code and "docstring" in node_data:
                            # Truncate docstrings for context
                            node_data["docstring"] = node_data["docstring"][:200] + "..."
                        nodes.append(node_data)

                    rels = []
                    for r in record["relationships"]:
                        rels.append({
                            "source": r.start_node["name"],
                            "target": r.end_node["name"],
                            "type": r.type,
                        })

                    return {
                        "center": symbol_name,
                        "radius": radius,
                        "nodes": nodes,
                        "relationships": rels,
                    }
            except Exception as e:
                logger.debug(f"APOC subgraph query failed, falling back: {e}")

            # Fallback without APOC - proper parameterization
            if repo:
                result = session.run(f"""
                    MATCH (center {{name: $name}})
                    WHERE center.repo = $repo
                    MATCH path = (center)-[*1..{safe_radius}]-(related)
                    WITH center, collect(DISTINCT related) AS nodes,
                         collect(DISTINCT relationships(path)) AS all_rels
                    UNWIND all_rels AS rel_list
                    UNWIND rel_list AS rel
                    WITH center, nodes, collect(DISTINCT rel) AS rels
                    RETURN center, nodes, rels
                """, name=symbol_name, repo=repo)
            else:
                result = session.run(f"""
                    MATCH (center {{name: $name}})
                    MATCH path = (center)-[*1..{safe_radius}]-(related)
                    WITH center, collect(DISTINCT related) AS nodes,
                         collect(DISTINCT relationships(path)) AS all_rels
                    UNWIND all_rels AS rel_list
                    UNWIND rel_list AS rel
                    WITH center, nodes, collect(DISTINCT rel) AS rels
                    RETURN center, nodes, rels
                """, name=symbol_name)

            record = result.single()
            if not record:
                return {"center": symbol_name, "nodes": [], "relationships": []}

            # Extract actual node data from the fallback query
            nodes = []
            if record["nodes"]:
                for n in record["nodes"]:
                    node_data = dict(n)
                    node_data["labels"] = list(n.labels) if hasattr(n, "labels") else []
                    if not include_code and "docstring" in node_data:
                        node_data["docstring"] = node_data["docstring"][:200] + "..."
                    nodes.append(node_data)

            # Extract actual relationship data
            rels = []
            if record["rels"]:
                for r in record["rels"]:
                    try:
                        rels.append({
                            "source": r.start_node.get("name", "") if hasattr(r, "start_node") else "",
                            "target": r.end_node.get("name", "") if hasattr(r, "end_node") else "",
                            "type": r.type if hasattr(r, "type") else "",
                        })
                    except Exception:
                        # Handle neo4j relationship object variations
                        pass

            return {
                "center": symbol_name,
                "radius": safe_radius,
                "nodes": nodes,
                "relationships": rels,
            }

    def get_stats(self, repo: Optional[str] = None) -> KnowledgeGraphStats:
        """Get knowledge graph statistics."""
        driver = self._get_driver()

        repo_filter = "WHERE n.repo = $repo" if repo else ""

        with driver.session(database=self._database) as session:
            result = session.run(f"""
                MATCH (n) {repo_filter}
                WITH count(n) AS total,
                     sum(CASE WHEN 'File' IN labels(n) THEN 1 ELSE 0 END) AS files,
                     sum(CASE WHEN 'Class' IN labels(n) THEN 1 ELSE 0 END) AS classes,
                     sum(CASE WHEN 'Function' IN labels(n) THEN 1 ELSE 0 END) AS functions,
                     avg(n.pagerank) AS avg_pr,
                     count(DISTINCT n.community_id) AS communities
                MATCH ()-[r]->()
                RETURN total, files, classes, functions, avg_pr, communities,
                       count(r) AS rels
            """, repo=repo)

            record = result.single()
            if not record:
                return KnowledgeGraphStats()

            return KnowledgeGraphStats(
                node_count=record["total"] or 0,
                relationship_count=record["rels"] or 0,
                file_count=record["files"] or 0,
                class_count=record["classes"] or 0,
                function_count=record["functions"] or 0,
                community_count=record["communities"] or 0,
                avg_pagerank=record["avg_pr"] or 0.0,
            )

    def get_shortest_path_length(
        self,
        source_symbol: str,
        target_symbol: str,
        repo: Optional[str] = None,
        max_depth: int = 4,
    ) -> Optional[int]:
        """Get shortest path length between two symbols.

        Args:
            source_symbol: Starting symbol name
            target_symbol: Target symbol name
            repo: Optional repo filter
            max_depth: Maximum path length to search

        Returns:
            Path length (number of hops), or None if no path exists.
        """
        driver = self._get_driver()
        safe_depth = _sanitize_depth(max_depth, default=4, max_depth=8)

        with driver.session(database=self._database) as session:
            # Use shortestPath with depth limit and proper parameterization
            if repo:
                result = session.run(f"""
                    MATCH (source {{name: $source}})
                    MATCH (target {{name: $target}})
                    WHERE source.repo = $repo AND target.repo = $repo
                    MATCH path = shortestPath((source)-[*1..{safe_depth}]-(target))
                    RETURN length(path) AS distance
                    LIMIT 1
                """, source=source_symbol, target=target_symbol, repo=repo)
            else:
                result = session.run(f"""
                    MATCH (source {{name: $source}})
                    MATCH (target {{name: $target}})
                    MATCH path = shortestPath((source)-[*1..{safe_depth}]-(target))
                    RETURN length(path) AS distance
                    LIMIT 1
                """, source=source_symbol, target=target_symbol)

            record = result.single()
            if record:
                return record["distance"]
            return None

    def get_batch_shortest_path_lengths(
        self,
        source_symbols: List[str],
        target_symbols: List[str],
        repo: Optional[str] = None,
        max_depth: int = 4,
    ) -> Dict[Tuple[str, str], int]:
        """Get shortest path lengths for multiple source-target pairs in a single query.

        This is much more efficient than calling get_shortest_path_length repeatedly.

        Args:
            source_symbols: List of source symbol names
            target_symbols: List of target symbol names
            repo: Optional repo filter
            max_depth: Maximum path length to search

        Returns:
            Dict mapping (source, target) tuples to their shortest path lengths.
            Pairs with no path are not included in the result.
        """
        if not source_symbols or not target_symbols:
            return {}

        driver = self._get_driver()
        safe_depth = _sanitize_depth(max_depth, default=4, max_depth=8)

        # Deduplicate inputs
        sources = list(set(source_symbols))[:10]  # Limit to prevent huge queries
        targets = list(set(target_symbols))[:50]

        with driver.session(database=self._database) as session:
            try:
                if repo:
                    result = session.run(f"""
                        UNWIND $sources AS src_name
                        UNWIND $targets AS tgt_name
                        MATCH (source {{name: src_name}})
                        MATCH (target {{name: tgt_name}})
                        WHERE source.repo = $repo AND target.repo = $repo
                              AND source <> target
                        MATCH path = shortestPath((source)-[*1..{safe_depth}]-(target))
                        RETURN source.name AS source, target.name AS target, length(path) AS distance
                    """, sources=sources, targets=targets, repo=repo)
                else:
                    result = session.run(f"""
                        UNWIND $sources AS src_name
                        UNWIND $targets AS tgt_name
                        MATCH (source {{name: src_name}})
                        MATCH (target {{name: tgt_name}})
                        WHERE source <> target
                        MATCH path = shortestPath((source)-[*1..{safe_depth}]-(target))
                        RETURN source.name AS source, target.name AS target, length(path) AS distance
                    """, sources=sources, targets=targets)

                distances: Dict[Tuple[str, str], int] = {}
                for record in result:
                    src = record["source"]
                    tgt = record["target"]
                    dist = record["distance"]
                    # Keep minimum distance if same pair found multiple times
                    key = (src, tgt)
                    if key not in distances or dist < distances[key]:
                        distances[key] = dist
                return distances

            except Exception as e:
                logger.debug(f"Batch shortest path query failed: {e}")
                return {}


# =============================================================================
# Singleton instance
# =============================================================================

_KNOWLEDGE_GRAPH: Optional[Neo4jKnowledgeGraph] = None


def get_knowledge_graph() -> Neo4jKnowledgeGraph:
    """Get singleton knowledge graph instance."""
    global _KNOWLEDGE_GRAPH
    if _KNOWLEDGE_GRAPH is None:
        _KNOWLEDGE_GRAPH = Neo4jKnowledgeGraph()
    return _KNOWLEDGE_GRAPH


def _cleanup_knowledge_graph() -> None:
    """Cleanup knowledge graph singleton on process exit."""
    global _KNOWLEDGE_GRAPH, _EXECUTOR
    if _KNOWLEDGE_GRAPH is not None:
        try:
            _KNOWLEDGE_GRAPH.close()
            logger.debug("Knowledge graph driver closed on shutdown")
        except Exception:
            pass
        _KNOWLEDGE_GRAPH = None
    if _EXECUTOR is not None:
        try:
            _EXECUTOR.shutdown(wait=False)
        except Exception:
            pass
        _EXECUTOR = None


# Register cleanup on process exit
atexit.register(_cleanup_knowledge_graph)
