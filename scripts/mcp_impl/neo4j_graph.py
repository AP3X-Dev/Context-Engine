# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
# See the LICENSE file in the repository root for full terms.
"""
Neo4j graph query MCP tool implementation.

Provides advanced graph traversals enabled when NEO4J_GRAPH=1:
- Multi-hop path finding
- Transitive dependency analysis
- Impact analysis (what depends on X?)
- Cycle detection
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["_neo4j_graph_query_impl", "_format_neo4j_graph_toon"]


def _get_neo4j_backend():
    """Get the Neo4j backend instance."""
    from scripts.graph_backends import get_graph_backend, GRAPH_BACKEND_TYPE
    
    if GRAPH_BACKEND_TYPE != "neo4j":
        return None
    
    backend = get_graph_backend()
    if backend.backend_type != "neo4j":
        return None
    
    return backend


async def _neo4j_graph_query_impl(
    query_type: str = "callers",
    symbol: Optional[str] = None,
    depth: int = 1,
    limit: int = 50,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    include_paths: bool = False,
    collection: Optional[str] = None,
    output_format: str = "json",
) -> Dict[str, Any]:
    """Execute Neo4j-specific graph queries.
    
    Query types:
    - callers: Who calls this symbol? (equivalent to symbol_graph callers)
    - callees: What does this symbol call?
    - transitive_callers: Multi-hop callers (up to depth)
    - transitive_callees: Multi-hop callees (up to depth)
    - impact: What would break if I change this? (reverse transitive)
    - dependencies: What does this symbol depend on? (transitive callees + imports)
    - path: Find shortest path between two symbols (symbol=from, to=target)
    - cycles: Detect circular dependencies involving this symbol
    
    Args:
        query_type: Type of graph query
        symbol: Symbol to query (required for most query types)
        depth: Maximum traversal depth for transitive queries (1-10, default 1)
        limit: Maximum results to return
        repo: Optional repository filter
        language: Optional language filter
        include_paths: Include full traversal paths in results
        collection: Optional collection scope (defaults to COLLECTION_NAME)
        output_format: "json" or "toon"
        
    Returns:
        Query results with graph traversal information
    """
    start_time = time.time()
    
    backend = _get_neo4j_backend()
    if not backend:
        return {
            "ok": False,
            "error": "Neo4j backend not enabled. Set NEO4J_GRAPH=1",
            "backend": "none",
        }
    
    if not symbol:
        return {
            "ok": False,
            "error": "symbol parameter is required",
        }

    collection = str(collection or os.environ.get("COLLECTION_NAME", "codebase")).strip() or "codebase"
    if collection.endswith("_graph"):
        collection = collection[: -len("_graph")]
    
    # Clamp depth
    depth = max(1, min(10, depth))
    
    db = backend._get_database()
    driver = backend._get_driver()
    
    results = []
    query_info = {"query_type": query_type, "symbol": symbol, "depth": depth, "collection": collection}
    
    try:
        with driver.session(database=db) as session:
            if query_type == "callers":
                results = _query_callers(session, symbol, repo, limit, collection)
                
            elif query_type == "callees":
                results = _query_callees(session, symbol, repo, limit, collection)
                
            elif query_type == "transitive_callers":
                results = _query_transitive_callers(
                    session, symbol, depth, repo, limit, include_paths, collection
                )
                
            elif query_type == "transitive_callees":
                results = _query_transitive_callees(
                    session, symbol, depth, repo, limit, include_paths, collection
                )
                
            elif query_type == "impact":
                # Impact = what would break if symbol changes
                # This is transitive callers (what calls this, directly or indirectly)
                results = _query_transitive_callers(
                    session, symbol, depth, repo, limit, include_paths=True, collection=collection
                )
                query_info["impact_note"] = "Shows all symbols that depend on this symbol"
                
            elif query_type == "dependencies":
                results = _query_dependencies(
                    session, symbol, depth, repo, limit, include_paths, collection
                )
                
            elif query_type == "cycles":
                results = _query_cycles(session, symbol, repo, limit, collection)
                
            else:
                return {
                    "ok": False,
                    "error": f"Unknown query_type: {query_type}. "
                             "Valid: callers, callees, transitive_callers, transitive_callees, "
                             "impact, dependencies, cycles",
                }
    
    except Exception as e:
        logger.error(f"Neo4j query failed: {e}")
        return {
            "ok": False,
            "error": str(e),
            "backend": "neo4j",
        }
    
    elapsed_ms = (time.time() - start_time) * 1000
    
    response = {
        "ok": True,
        "results": results,
        "total": len(results),
        "query": query_info,
        "backend": "neo4j",
        "query_time_ms": round(elapsed_ms, 2),
    }
    
    if output_format == "toon":
        return _format_neo4j_graph_toon(response)

    return response


def _query_callers(
    session,
    symbol: str,
    repo: Optional[str],
    limit: int,
    collection: str,
) -> List[Dict]:
    """Simple caller query (depth 1)."""
    if repo and repo != "*":
        result = session.run("""
            MATCH (caller:Symbol {collection: $collection})-[r:CALLS]->(callee:Symbol {name: $symbol, collection: $collection})
            WHERE r.collection = $collection AND (r.repo = $repo OR callee.repo = $repo)
            RETURN caller.name as symbol, r.caller_path as path,
                   r.start_line as start_line, r.end_line as end_line,
                   r.language as language, callee.repo as repo
            LIMIT $limit
        """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
    else:
        result = session.run("""
            MATCH (caller:Symbol {collection: $collection})-[r:CALLS]->(callee:Symbol {name: $symbol, collection: $collection})
            WHERE r.collection = $collection
            RETURN caller.name as symbol, r.caller_path as path,
                   r.start_line as start_line, r.end_line as end_line,
                   r.language as language, callee.repo as repo
            LIMIT $limit
        """, {"symbol": symbol, "collection": collection, "limit": limit})

    return [dict(r) for r in result]


def _query_callees(
    session,
    symbol: str,
    repo: Optional[str],
    limit: int,
    collection: str,
) -> List[Dict]:
    """Simple callee query (depth 1)."""
    if repo and repo != "*":
        result = session.run("""
            MATCH (caller:Symbol {name: $symbol, collection: $collection})-[r:CALLS]->(callee:Symbol {collection: $collection})
            WHERE r.collection = $collection AND (r.repo = $repo OR caller.repo = $repo)
            RETURN callee.name as symbol, r.caller_path as path,
                   r.start_line as start_line, r.end_line as end_line,
                   r.language as language, caller.repo as repo
            LIMIT $limit
        """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
    else:
        result = session.run("""
            MATCH (caller:Symbol {name: $symbol, collection: $collection})-[r:CALLS]->(callee:Symbol {collection: $collection})
            WHERE r.collection = $collection
            RETURN callee.name as symbol, r.caller_path as path,
                   r.start_line as start_line, r.end_line as end_line,
                   r.language as language, caller.repo as repo
            LIMIT $limit
        """, {"symbol": symbol, "collection": collection, "limit": limit})

    return [dict(r) for r in result]


def _query_transitive_callers(
    session,
    symbol: str,
    depth: int,
    repo: Optional[str],
    limit: int,
    include_paths: bool,
    collection: str,
) -> List[Dict]:
    """Multi-hop caller traversal."""
    # Cypher doesn't support parameterized path lengths, so we embed depth directly
    safe_depth = max(1, min(10, int(depth)))

    if include_paths:
        # Include full path information
        if repo and repo != "*":
            result = session.run(f"""
                MATCH path = (caller:Symbol {{collection: $collection}})-[:CALLS*1..{safe_depth}]->(target:Symbol {{name: $symbol, collection: $collection}})
                WHERE all(r IN relationships(path) WHERE r.collection = $collection AND r.repo = $repo)
                WITH caller, path, length(path) as hop
                RETURN caller.name as symbol, hop,
                       [n in nodes(path) | n.name] as path_nodes,
                       caller.repo as repo
                ORDER BY hop
                LIMIT $limit
            """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
        else:
            result = session.run(f"""
                MATCH path = (caller:Symbol {{collection: $collection}})-[:CALLS*1..{safe_depth}]->(target:Symbol {{name: $symbol, collection: $collection}})
                WHERE all(r IN relationships(path) WHERE r.collection = $collection)
                WITH caller, path, length(path) as hop
                RETURN caller.name as symbol, hop,
                       [n in nodes(path) | n.name] as path_nodes,
                       caller.repo as repo
                ORDER BY hop
                LIMIT $limit
            """, {"symbol": symbol, "collection": collection, "limit": limit})
    else:
        if repo and repo != "*":
            result = session.run(f"""
                MATCH path = (caller:Symbol {{collection: $collection}})-[:CALLS*1..{safe_depth}]->(target:Symbol {{name: $symbol, collection: $collection}})
                WHERE all(r IN relationships(path) WHERE r.collection = $collection AND r.repo = $repo)
                WITH DISTINCT caller
                RETURN caller.name as symbol, caller.repo as repo
                LIMIT $limit
            """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
        else:
            result = session.run(f"""
                MATCH path = (caller:Symbol {{collection: $collection}})-[:CALLS*1..{safe_depth}]->(target:Symbol {{name: $symbol, collection: $collection}})
                WHERE all(r IN relationships(path) WHERE r.collection = $collection)
                WITH DISTINCT caller
                RETURN caller.name as symbol, caller.repo as repo
                LIMIT $limit
            """, {"symbol": symbol, "collection": collection, "limit": limit})

    return [dict(r) for r in result]


def _query_transitive_callees(
    session,
    symbol: str,
    depth: int,
    repo: Optional[str],
    limit: int,
    include_paths: bool,
    collection: str,
) -> List[Dict]:
    """Multi-hop callee traversal."""
    # Cypher doesn't support parameterized path lengths, so we embed depth directly
    safe_depth = max(1, min(10, int(depth)))

    if include_paths:
        if repo and repo != "*":
            result = session.run(f"""
                MATCH path = (source:Symbol {{name: $symbol, collection: $collection}})-[:CALLS*1..{safe_depth}]->(callee:Symbol {{collection: $collection}})
                WHERE all(r IN relationships(path) WHERE r.collection = $collection AND r.repo = $repo)
                WITH callee, path, length(path) as hop
                RETURN callee.name as symbol, hop,
                       [n in nodes(path) | n.name] as path_nodes,
                       callee.repo as repo
                ORDER BY hop
                LIMIT $limit
            """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
        else:
            result = session.run(f"""
                MATCH path = (source:Symbol {{name: $symbol, collection: $collection}})-[:CALLS*1..{safe_depth}]->(callee:Symbol {{collection: $collection}})
                WHERE all(r IN relationships(path) WHERE r.collection = $collection)
                WITH callee, path, length(path) as hop
                RETURN callee.name as symbol, hop,
                       [n in nodes(path) | n.name] as path_nodes,
                       callee.repo as repo
                ORDER BY hop
                LIMIT $limit
            """, {"symbol": symbol, "collection": collection, "limit": limit})
    else:
        if repo and repo != "*":
            result = session.run(f"""
                MATCH path = (source:Symbol {{name: $symbol, collection: $collection}})-[:CALLS*1..{safe_depth}]->(callee:Symbol {{collection: $collection}})
                WHERE all(r IN relationships(path) WHERE r.collection = $collection AND r.repo = $repo)
                WITH DISTINCT callee
                RETURN callee.name as symbol, callee.repo as repo
                LIMIT $limit
            """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
        else:
            result = session.run(f"""
                MATCH path = (source:Symbol {{name: $symbol, collection: $collection}})-[:CALLS*1..{safe_depth}]->(callee:Symbol {{collection: $collection}})
                WHERE all(r IN relationships(path) WHERE r.collection = $collection)
                WITH DISTINCT callee
                RETURN callee.name as symbol, callee.repo as repo
                LIMIT $limit
            """, {"symbol": symbol, "collection": collection, "limit": limit})

    return [dict(r) for r in result]


def _query_dependencies(
    session,
    symbol: str,
    depth: int,
    repo: Optional[str],
    limit: int,
    include_paths: bool,
    collection: str,
) -> List[Dict]:
    """Query both calls and imports for full dependency analysis."""
    # Cypher doesn't support parameterized path lengths, so we embed depth directly
    safe_depth = max(1, min(10, int(depth)))
    _ = include_paths  # Reserved for future use

    if repo and repo != "*":
        result = session.run(f"""
            MATCH path = (source:Symbol {{name: $symbol, collection: $collection}})-[:CALLS|IMPORTS*1..{safe_depth}]->(dep:Symbol {{collection: $collection}})
            WHERE all(r IN relationships(path) WHERE r.collection = $collection AND r.repo = $repo)
            WITH DISTINCT dep
            RETURN dep.name as symbol, dep.repo as repo
            LIMIT $limit
        """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
    else:
        result = session.run(f"""
            MATCH path = (source:Symbol {{name: $symbol, collection: $collection}})-[:CALLS|IMPORTS*1..{safe_depth}]->(dep:Symbol {{collection: $collection}})
            WHERE all(r IN relationships(path) WHERE r.collection = $collection)
            WITH DISTINCT dep
            RETURN dep.name as symbol, dep.repo as repo
            LIMIT $limit
        """, {"symbol": symbol, "collection": collection, "limit": limit})

    return [dict(r) for r in result]


def _query_cycles(
    session,
    symbol: str,
    repo: Optional[str],
    limit: int,
    collection: str,
) -> List[Dict]:
    """Detect circular dependencies involving the symbol."""
    if repo and repo != "*":
        result = session.run("""
            MATCH path = (s:Symbol {name: $symbol, collection: $collection})-[:CALLS*2..10]->(s)
            WHERE all(r IN relationships(path) WHERE r.collection = $collection AND r.repo = $repo)
            WITH s, path, length(path) as cycle_length
            RETURN [n in nodes(path) | n.name] as cycle_path,
                   cycle_length,
                   s.repo as repo
            ORDER BY cycle_length
            LIMIT $limit
        """, {"symbol": symbol, "repo": repo, "collection": collection, "limit": limit})
    else:
        result = session.run("""
            MATCH path = (s:Symbol {name: $symbol, collection: $collection})-[:CALLS*2..10]->(s)
            WHERE all(r IN relationships(path) WHERE r.collection = $collection)
            WITH s, path, length(path) as cycle_length
            RETURN [n in nodes(path) | n.name] as cycle_path,
                   cycle_length,
                   s.repo as repo
            ORDER BY cycle_length
            LIMIT $limit
        """, {"symbol": symbol, "collection": collection, "limit": limit})

    return [dict(r) for r in result]


def _format_neo4j_graph_toon(response: Dict[str, Any]) -> str:
    """Format Neo4j graph results in TOON format."""
    if not response.get("ok"):
        return f"⚠ NEO4J_ERROR | {response.get('error', 'Unknown error')}"

    results = response.get("results", [])
    query = response.get("query", {})
    query_type = query.get("query_type", "")
    symbol = query.get("symbol", "")

    if not results:
        return f"≡ NEO4J_GRAPH | {query_type} | {symbol}\n⚠ No results found"

    lines = [f"≡ NEO4J_GRAPH | {query_type} | {symbol} | {len(results)} results"]

    for r in results:
        sym = r.get("symbol", "")
        path = r.get("path", "")
        hop = r.get("hop", "")
        repo = r.get("repo", "")

        if path:
            lines.append(f"  → {sym} @ {path}")
        elif hop:
            lines.append(f"  → {sym} (hop {hop})")
        else:
            lines.append(f"  → {sym}")

        if r.get("path_nodes"):
            lines.append(f"    path: {' → '.join(r['path_nodes'])}")
        if r.get("cycle_path"):
            lines.append(f"    cycle: {' → '.join(r['cycle_path'])}")

    return "\n".join(lines)
