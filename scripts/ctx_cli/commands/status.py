#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Status command for ctx CLI.

Displays health status of Context-Engine stack:
- Docker services (qdrant, mcp, mcp_indexer)
- Qdrant health endpoint
- MCP Indexer health endpoint
- MCP Memory health endpoint
- Collection info (name, point count, last indexed)
- Model warmup state (embedding/reranker models)
- Cache statistics (hit rate, size)
- Memory usage per service
- Index progress if indexing is in progress

Usage:
  ctx status [--json] [--verbose] [--brief]
"""

import json
import sys
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import socket

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError


def check_docker_services() -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Check Docker Compose service status.

    Returns:
        Tuple of (all_running, services_list)
    """
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5
        )

        if result.returncode != 0:
            return False, []

        # Parse JSON output - docker compose ps returns JSONL (one JSON object per line)
        services = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    services.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        # Check if all services are running
        all_running = all(
            svc.get("State") == "running"
            for svc in services
        )

        return all_running, services

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        return False, []


def check_http_health(url: str, timeout: int = 2) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Check HTTP health endpoint.

    Args:
        url: Health check URL
        timeout: Request timeout in seconds

    Returns:
        Tuple of (is_healthy, response_data)
    """
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                try:
                    data = json.loads(response.read().decode('utf-8'))
                    return True, data
                except json.JSONDecodeError:
                    # Some endpoints return plain text "OK"
                    return True, {"status": "ok"}
            return False, None
    except (HTTPError, URLError, socket.timeout, Exception) as e:
        return False, None


def call_mcp_tool(server_url: str, tool_name: str, arguments: Dict[str, Any] = None, timeout: int = 5) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Call an MCP tool via HTTP.

    Args:
        server_url: MCP server base URL (e.g., http://localhost:8003/mcp)
        tool_name: Tool name to call
        arguments: Tool arguments
        timeout: Request timeout in seconds

    Returns:
        Tuple of (success, response_data)
    """
    if arguments is None:
        arguments = {}

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        },
        "id": 1
    }

    try:
        req = Request(
            server_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
        )

        with urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))

                # MCP response format: {"jsonrpc": "2.0", "result": {...}, "id": 1}
                if "result" in data:
                    return True, data["result"]
                elif "error" in data:
                    return False, data["error"]

            return False, None

    except (HTTPError, URLError, socket.timeout, Exception) as e:
        return False, None


def get_collection_info(qdrant_url: str = "http://localhost:6333") -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Get collection information directly from Qdrant API.

    Returns:
        Tuple of (success, collection_info)
        collection_info format: {
            "collection": "name",
            "points_count": 1234,
            "indexed_at": "2024-01-15T10:30:00Z" (optional)
        }
    """
    try:
        # Get list of collections
        req = Request(f"{qdrant_url}/collections", headers={"Accept": "application/json"})
        with urlopen(req, timeout=2) as response:
            if response.status != 200:
                return False, None

            data = json.loads(response.read().decode('utf-8'))
            collections = data.get("result", {}).get("collections", [])

            if not collections:
                return True, {"collection": "None", "points_count": 0}

            # Get the first non-global collection or the first collection
            collection_name = None
            for coll in collections:
                name = coll.get("name", "")
                if name and "global" not in name.lower():
                    collection_name = name
                    break

            if not collection_name and collections:
                collection_name = collections[0].get("name", "Unknown")

            # Get collection details
            req = Request(
                f"{qdrant_url}/collections/{collection_name}",
                headers={"Accept": "application/json"}
            )
            with urlopen(req, timeout=2) as response:
                if response.status != 200:
                    return True, {"collection": collection_name, "points_count": "Unknown"}

                data = json.loads(response.read().decode('utf-8'))
                result = data.get("result", {})

                points_count = result.get("points_count", 0)
                # Qdrant doesn't provide indexed_at, so we'll omit it
                return True, {
                    "collection": collection_name,
                    "points_count": points_count
                }

    except (HTTPError, URLError, socket.timeout, json.JSONDecodeError, Exception) as e:
        return False, None


def get_warmup_status() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Get model warmup status from MCP indexer.

    Returns:
        Tuple of (success, warmup_info)
        warmup_info format: {
            "embedding_ready": true,
            "reranker_ready": true,
            "decoder_ready": false,
            ...
        }
    """
    try:
        client = MCPClient(server="indexer", timeout=5)
        result = client.call_tool("warmup_status")
        return True, result
    except (MCPError, Exception) as e:
        return False, None


def get_qdrant_status() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Get Qdrant collection status from MCP indexer.

    Returns:
        Tuple of (success, qdrant_info)
        qdrant_info format: {
            "collection": "name",
            "count": 1234,
            "last_indexed": "2024-01-15T10:30:00Z",
            ...
        }
    """
    try:
        client = MCPClient(server="indexer", timeout=5)
        result = client.call_tool("qdrant_status")
        return True, result
    except (MCPError, Exception) as e:
        return False, None


def get_workspace_info() -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Get workspace information from MCP indexer.

    Returns:
        Tuple of (success, workspace_info)
        workspace_info format: {
            "workspace_root": "/path/to/workspace",
            "indexing_status": "idle|indexing|error",
            "indexing_progress": {...},
            ...
        }
    """
    try:
        client = MCPClient(server="indexer", timeout=5)
        result = client.call_tool("workspace_info")
        return True, result
    except (MCPError, Exception) as e:
        return False, None


def get_graph_status(collection_name: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Get graph backend status (Qdrant _graph collection and/or Neo4j).

    Returns:
        Tuple of (success, graph_info)
        graph_info format: {
            "backend": "qdrant" | "neo4j" | "both",
            "qdrant_graph": {
                "collection": "name_graph",
                "edge_count": 1234,
            },
            "neo4j": {
                "connected": True/False,
                "node_count": 1234,
                "edge_count": 5678,
            }
        }
    """
    import os

    graph_info: Dict[str, Any] = {"backend": "none"}
    success = False

    # Check Qdrant graph collection
    try:
        qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        graph_coll = f"{collection_name}_graph" if collection_name else None

        if graph_coll:
            req = Request(
                f"{qdrant_url}/collections/{graph_coll}",
                headers={"Accept": "application/json"}
            )
            with urlopen(req, timeout=2) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    result = data.get("result", {})
                    edge_count = result.get("points_count", 0)

                    graph_info["qdrant_graph"] = {
                        "collection": graph_coll,
                        "edge_count": edge_count,
                    }
                    graph_info["backend"] = "qdrant"
                    success = True
    except Exception:
        pass  # Graph collection doesn't exist or Qdrant not available

    # Check Neo4j if enabled
    neo4j_enabled = os.environ.get("NEO4J_GRAPH", "").lower() in {"1", "true", "yes", "on"}
    if neo4j_enabled:
        try:
            # Try to import and use Neo4j plugin
            from plugins.neo4j_graph import Neo4jGraphBackend

            backend = Neo4jGraphBackend()
            # Quick health check - try a simple query
            driver = backend._get_driver()
            if driver:
                with driver.session() as session:
                    # Count nodes and relationships
                    node_result = session.run(
                        "MATCH (n:Symbol) RETURN count(n) as count"
                    )
                    node_count = node_result.single()["count"]

                    edge_result = session.run(
                        "MATCH ()-[r]->() RETURN count(r) as count"
                    )
                    edge_count = edge_result.single()["count"]

                    graph_info["neo4j"] = {
                        "connected": True,
                        "node_count": node_count,
                        "edge_count": edge_count,
                    }

                    if graph_info["backend"] == "qdrant":
                        graph_info["backend"] = "both"
                    else:
                        graph_info["backend"] = "neo4j"
                    success = True
        except ImportError:
            graph_info["neo4j"] = {"connected": False, "error": "plugin not installed"}
        except Exception as e:
            graph_info["neo4j"] = {"connected": False, "error": str(e)[:50]}

    return success, graph_info if success else None


def get_docker_stats(services: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Get Docker container memory statistics.

    Args:
        services: List of Docker Compose services

    Returns:
        Dict mapping service names to stats (memory_usage, memory_limit, cpu_percent)
    """
    stats = {}

    try:
        # Get container IDs from services
        for svc in services:
            service_name = svc.get("Service", svc.get("Name", ""))
            if not service_name:
                continue

            # Get container ID
            container_id = svc.get("ID", "")
            if not container_id:
                continue

            # Get stats for this container (no-stream for single snapshot)
            result = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}", container_id],
                capture_output=True,
                text=True,
                check=False,
                timeout=3
            )

            if result.returncode == 0 and result.stdout.strip():
                try:
                    container_stats = json.loads(result.stdout.strip())
                    stats[service_name] = {
                        "memory_usage": container_stats.get("MemUsage", "N/A"),
                        "memory_percent": container_stats.get("MemPerc", "N/A"),
                        "cpu_percent": container_stats.get("CPUPerc", "N/A"),
                    }
                except json.JSONDecodeError:
                    pass

    except (subprocess.TimeoutExpired, Exception) as e:
        pass

    return stats


def format_timestamp(ts: Optional[str]) -> str:
    """Format timestamp for display."""
    if not ts:
        return "Never"

    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return ts


def print_status_brief(
    docker_ok: bool,
    qdrant_ok: bool,
    indexer_ok: bool,
    memory_ok: bool
):
    """
    Print minimal status output (brief mode).

    Shows only up/down status for each component.
    """
    all_healthy = docker_ok and qdrant_ok and indexer_ok and memory_ok

    # Print single-line status
    status_char = "✓" if all_healthy else "✗"
    status_text = "UP" if all_healthy else "DOWN"

    print(f"{status_char} Context-Engine: {status_text}")

    # Show individual component status
    components = [
        ("Docker", docker_ok),
        ("Qdrant", qdrant_ok),
        ("MCP Indexer", indexer_ok),
        ("MCP Memory", memory_ok),
    ]

    for name, ok in components:
        char = "✓" if ok else "✗"
        print(f"  {char} {name}")


def format_bytes(bytes_str: str) -> str:
    """
    Format bytes string from Docker stats.

    Args:
        bytes_str: String like "123.4MiB" or "1.234GiB"

    Returns:
        Formatted string
    """
    if not bytes_str or bytes_str == "N/A":
        return bytes_str

    # Already formatted by Docker
    return bytes_str


def print_status_table(
    docker_ok: bool,
    services: List[Dict[str, Any]],
    qdrant_ok: bool,
    indexer_ok: bool,
    memory_ok: bool,
    collection_info: Optional[Dict[str, Any]],
    warmup_info: Optional[Dict[str, Any]] = None,
    qdrant_status_info: Optional[Dict[str, Any]] = None,
    workspace_info: Optional[Dict[str, Any]] = None,
    docker_stats: Optional[Dict[str, Dict[str, Any]]] = None,
    graph_info: Optional[Dict[str, Any]] = None,
    verbose: bool = False
):
    """
    Print status as a formatted table using simple box drawing.

    Note: Using simple ASCII box drawing instead of Rich to avoid
    adding new dependencies.
    """

    # Count running services
    running_count = sum(1 for svc in services if svc.get("State") == "running")
    total_count = len(services)

    # Overall health check
    all_healthy = docker_ok and qdrant_ok and indexer_ok and memory_ok
    health_symbol = "✓" if all_healthy else "✗"
    health_text = "All checks passed" if all_healthy else "Some checks failed"

    # Collection info (prefer qdrant_status_info if available)
    collection_name = "Unknown"
    points_count = "Unknown"
    last_indexed = "Unknown"

    if qdrant_status_info:
        collection_name = qdrant_status_info.get("collection", "Unknown")
        points_count = qdrant_status_info.get("count", "Unknown")
        if isinstance(points_count, int):
            points_count = f"{points_count:,}"
        last_indexed = format_timestamp(qdrant_status_info.get("last_indexed"))
    elif collection_info:
        collection_name = collection_info.get("collection", "Unknown")
        points_count = collection_info.get("points_count", collection_info.get("count", "Unknown"))
        if isinstance(points_count, int):
            points_count = f"{points_count:,}"
        last_indexed = format_timestamp(
            collection_info.get("indexed_at") or
            collection_info.get("last_indexed") or
            collection_info.get("updated_at")
        )

    # Build the table
    print("┌" + "─" * 46 + "┐")
    print("│ Context-Engine Status" + " " * 24 + "│")
    print("├" + "─" * 46 + "┤")

    stack_symbol = "✓" if docker_ok else "✗"
    print(f"│ Stack:      {stack_symbol} {'Running' if docker_ok else 'Stopped'} ({running_count}/{total_count} services)" + " " * (46 - len(f"Stack:      {stack_symbol} {'Running' if docker_ok else 'Stopped'} ({running_count}/{total_count} services)") - 2) + "│")

    print(f"│ Collection: {collection_name}" + " " * (46 - len(f"Collection: {collection_name}") - 2) + "│")
    print(f"│ Documents:  {points_count} indexed" + " " * (46 - len(f"Documents:  {points_count} indexed") - 2) + "│")

    # Graph info (edges from Qdrant _graph and/or Neo4j)
    if graph_info:
        backend = graph_info.get("backend", "none")
        if backend != "none":
            # Build edge count display
            edge_parts = []

            # Qdrant graph edges
            if "qdrant_graph" in graph_info:
                qdrant_edges = graph_info["qdrant_graph"].get("edge_count", 0)
                if qdrant_edges > 0:
                    edge_parts.append(f"{qdrant_edges:,} qdrant")

            # Neo4j edges
            if "neo4j" in graph_info and graph_info["neo4j"].get("connected"):
                neo4j_edges = graph_info["neo4j"].get("edge_count", 0)
                neo4j_nodes = graph_info["neo4j"].get("node_count", 0)
                if neo4j_edges > 0:
                    edge_parts.append(f"{neo4j_edges:,} neo4j ({neo4j_nodes:,} nodes)")

            if edge_parts:
                graph_text = " + ".join(edge_parts)
                print(f"│ Graph:      {graph_text}" + " " * max(0, 46 - len(f"Graph:      {graph_text}") - 2) + "│")

    print(f"│ Last index: {last_indexed}" + " " * (46 - len(f"Last index: {last_indexed}") - 2) + "│")

    # Model warmup status
    if warmup_info:
        embedding_ready = warmup_info.get("embedding_ready", False)
        reranker_ready = warmup_info.get("reranker_ready", False)
        models_symbol = "✓" if (embedding_ready and reranker_ready) else "⚠"
        models_text = "Ready" if (embedding_ready and reranker_ready) else "Loading"
        print(f"│ Models:     {models_symbol} {models_text}" + " " * (46 - len(f"Models:     {models_symbol} {models_text}") - 2) + "│")

    # Indexing progress
    if workspace_info:
        indexing_status = workspace_info.get("indexing_status", "unknown")
        if indexing_status == "indexing":
            progress = workspace_info.get("indexing_progress", {})
            current = progress.get("current", 0)
            total = progress.get("total", 0)
            percent = (current / total * 100) if total > 0 else 0
            progress_text = f"Indexing: {current}/{total} ({percent:.0f}%)"
            print(f"│ Progress:   {progress_text}" + " " * (46 - len(f"Progress:   {progress_text}") - 2) + "│")

    print(f"│ Health:     {health_symbol} {health_text}" + " " * (46 - len(f"Health:     {health_symbol} {health_text}") - 2) + "│")

    print("└" + "─" * 46 + "┘")

    # Verbose mode: show per-service details
    if verbose and services:
        print("\nService Details:")
        print("┌" + "─" * 78 + "┐")
        print("│ " + "Service".ljust(20) + " State".ljust(10) + " Memory".ljust(15) + " CPU".ljust(8) + " Status".ljust(22) + "│")
        print("├" + "─" * 78 + "┤")

        for svc in services:
            name = svc.get("Service", svc.get("Name", "Unknown"))[:20]
            state = svc.get("State", "unknown")[:10]
            status = svc.get("Status", "")[:22]

            # Get memory stats if available
            mem_usage = "N/A"
            cpu_usage = "N/A"
            if docker_stats and name in docker_stats:
                stats = docker_stats[name]
                mem_usage = stats.get("memory_usage", "N/A")[:15]
                cpu_usage = stats.get("cpu_percent", "N/A")[:8]

            state_symbol = "✓" if state == "running" else "✗"
            print(f"│ {state_symbol} {name.ljust(18)} {state.ljust(10)} {mem_usage.ljust(15)} {cpu_usage.ljust(8)} {status.ljust(20)} │")

        print("└" + "─" * 78 + "┘")

        # Model warmup details
        if warmup_info:
            print("\nModel Warmup Status:")
            print("┌" + "─" * 50 + "┐")
            print("│ " + "Model".ljust(25) + " Status".ljust(23) + "│")
            print("├" + "─" * 50 + "┤")

            models = [
                ("Embedding", warmup_info.get("embedding_ready", False)),
                ("Reranker", warmup_info.get("reranker_ready", False)),
                ("Decoder", warmup_info.get("decoder_ready", False)),
            ]

            for model_name, ready in models:
                status_text = "✓ Ready" if ready else "✗ Not Ready"
                print(f"│ {model_name.ljust(25)} {status_text.ljust(23)} │")

            # Show cache info if available
            if "cache_info" in warmup_info:
                cache = warmup_info["cache_info"]
                print("├" + "─" * 50 + "┤")
                print("│ Cache Statistics" + " " * 33 + "│")
                print("├" + "─" * 50 + "┤")

                hit_rate = cache.get("hit_rate", 0)
                total_requests = cache.get("total_requests", 0)
                cache_size = cache.get("size", 0)

                print(f"│ Hit Rate:    {hit_rate:.1%}" + " " * (50 - len(f"Hit Rate:    {hit_rate:.1%}") - 2) + "│")
                print(f"│ Total Requests: {total_requests:,}" + " " * (50 - len(f"Total Requests: {total_requests:,}") - 2) + "│")
                print(f"│ Cache Size:  {cache_size:,} items" + " " * (50 - len(f"Cache Size:  {cache_size:,} items") - 2) + "│")

            print("└" + "─" * 50 + "┘")

        # Health check details
        print("\nHealth Checks:")
        print("┌" + "─" * 50 + "┐")
        print("│ " + "Endpoint".ljust(25) + " Status".ljust(23) + "│")
        print("├" + "─" * 50 + "┤")

        endpoints = [
            ("Qdrant (6333)", qdrant_ok),
            ("MCP Indexer (8003)", indexer_ok),
            ("MCP Memory (8002)", memory_ok),
        ]

        for endpoint, ok in endpoints:
            status_text = "✓ Healthy" if ok else "✗ Unhealthy"
            print(f"│ {endpoint.ljust(25)} {status_text.ljust(23)} │")

        print("└" + "─" * 50 + "┘")


def print_status_json(
    docker_ok: bool,
    services: List[Dict[str, Any]],
    qdrant_ok: bool,
    indexer_ok: bool,
    memory_ok: bool,
    collection_info: Optional[Dict[str, Any]],
    warmup_info: Optional[Dict[str, Any]] = None,
    qdrant_status_info: Optional[Dict[str, Any]] = None,
    workspace_info: Optional[Dict[str, Any]] = None,
    docker_stats: Optional[Dict[str, Dict[str, Any]]] = None,
    graph_info: Optional[Dict[str, Any]] = None
):
    """Print status as JSON."""

    running_count = sum(1 for svc in services if svc.get("State") == "running")
    total_count = len(services)
    all_healthy = docker_ok and qdrant_ok and indexer_ok and memory_ok

    status = {
        "healthy": all_healthy,
        "docker": {
            "running": docker_ok,
            "services": {
                "total": total_count,
                "running": running_count
            },
            "details": services,
            "stats": docker_stats or {}
        },
        "health_checks": {
            "qdrant": qdrant_ok,
            "mcp_indexer": indexer_ok,
            "mcp_memory": memory_ok
        },
        "collection": qdrant_status_info or collection_info or {},
        "warmup": warmup_info or {},
        "workspace": workspace_info or {},
        "graph": graph_info or {}
    }

    print(json.dumps(status, indent=2))


def run_status(args) -> int:
    """
    Run the status command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """

    # Check Docker services
    docker_ok, services = check_docker_services()

    # Check health endpoints
    qdrant_ok, _ = check_http_health("http://localhost:6333")
    indexer_ok, _ = check_http_health("http://localhost:18003/readyz")
    memory_ok, _ = check_http_health("http://localhost:18002/readyz")

    # Get collection info (fallback method)
    collection_ok, collection_info = get_collection_info("http://localhost:6333")

    # Brief mode: minimal output
    if hasattr(args, 'brief') and args.brief:
        print_status_brief(docker_ok, qdrant_ok, indexer_ok, memory_ok)
        all_healthy = docker_ok and qdrant_ok and indexer_ok and memory_ok
        return 0 if all_healthy else 1

    # Get additional data via MCP (only if services are healthy)
    warmup_info = None
    qdrant_status_info = None
    workspace_info = None
    docker_stats = None

    graph_info = None
    if indexer_ok:
        # Get warmup status
        warmup_ok, warmup_info = get_warmup_status()

        # Get Qdrant status via MCP (preferred over direct API)
        qdrant_status_ok, qdrant_status_info = get_qdrant_status()

        # Get workspace info (includes indexing progress)
        workspace_ok, workspace_info = get_workspace_info()

        # Get graph status (Qdrant _graph collection and/or Neo4j)
        collection_for_graph = (
            qdrant_status_info.get("collection") if qdrant_status_info else
            collection_info.get("collection") if collection_info else None
        )
        if collection_for_graph:
            _, graph_info = get_graph_status(collection_for_graph)

    # Get Docker stats if verbose
    if hasattr(args, 'verbose') and args.verbose and docker_ok:
        docker_stats = get_docker_stats(services)

    # Output
    if args.json:
        print_status_json(
            docker_ok, services, qdrant_ok, indexer_ok, memory_ok, collection_info,
            warmup_info, qdrant_status_info, workspace_info, docker_stats, graph_info
        )
    else:
        print_status_table(
            docker_ok, services, qdrant_ok, indexer_ok, memory_ok, collection_info,
            warmup_info, qdrant_status_info, workspace_info, docker_stats, graph_info,
            verbose=hasattr(args, 'verbose') and args.verbose
        )

    # Return exit code based on overall health
    all_healthy = docker_ok and qdrant_ok and indexer_ok and memory_ok
    return 0 if all_healthy else 1


def register_command(subparsers):
    """Register the status command with the CLI parser."""
    parser = subparsers.add_parser(
        "status",
        help="Show Context-Engine stack status",
        description="Display health status of Docker services, Qdrant, and MCP servers"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output status as JSON"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed per-service information (includes memory usage, model warmup, cache stats)"
    )

    parser.add_argument(
        "--brief", "-b",
        action="store_true",
        help="Show minimal output (just up/down status)"
    )

    parser.set_defaults(func=run_status)
