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

Usage:
  ctx status [--json] [--verbose]
"""

import json
import sys
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import socket


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


def format_timestamp(ts: Optional[str]) -> str:
    """Format timestamp for display."""
    if not ts:
        return "Never"

    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        return ts


def print_status_table(
    docker_ok: bool,
    services: List[Dict[str, Any]],
    qdrant_ok: bool,
    indexer_ok: bool,
    memory_ok: bool,
    collection_info: Optional[Dict[str, Any]],
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

    # Collection info
    collection_name = "Unknown"
    points_count = "Unknown"
    last_indexed = "Unknown"

    if collection_info:
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
    print(f"│ Last index: {last_indexed}" + " " * (46 - len(f"Last index: {last_indexed}") - 2) + "│")
    print(f"│ Health:     {health_symbol} {health_text}" + " " * (46 - len(f"Health:     {health_symbol} {health_text}") - 2) + "│")

    print("└" + "─" * 46 + "┘")

    # Verbose mode: show per-service details
    if verbose and services:
        print("\nService Details:")
        print("┌" + "─" * 60 + "┐")
        print("│ " + "Service".ljust(20) + " State".ljust(12) + " Status".ljust(26) + "│")
        print("├" + "─" * 60 + "┤")

        for svc in services:
            name = svc.get("Service", svc.get("Name", "Unknown"))[:20]
            state = svc.get("State", "unknown")[:12]
            status = svc.get("Status", "")[:26]

            state_symbol = "✓" if state == "running" else "✗"
            print(f"│ {state_symbol} {name.ljust(18)} {state.ljust(12)} {status.ljust(24)} │")

        print("└" + "─" * 60 + "┘")

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
    collection_info: Optional[Dict[str, Any]]
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
            "details": services
        },
        "health_checks": {
            "qdrant": qdrant_ok,
            "mcp_indexer": indexer_ok,
            "mcp_memory": memory_ok
        },
        "collection": collection_info or {}
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

    # Get collection info
    collection_ok, collection_info = get_collection_info("http://localhost:6333")

    # Output
    if args.json:
        print_status_json(
            docker_ok, services, qdrant_ok, indexer_ok, memory_ok, collection_info
        )
    else:
        print_status_table(
            docker_ok, services, qdrant_ok, indexer_ok, memory_ok, collection_info,
            verbose=args.verbose
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
        help="Show detailed per-service information"
    )

    parser.set_defaults(func=run_status)
