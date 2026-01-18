#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Quickstart command for Context-Engine CLI.

The ONE COMMAND to rule them all - sets up and starts everything.

Usage:
    ctx quickstart [OPTIONS]

This command orchestrates:
    1. Environment detection and configuration (init)
    2. Docker service startup (up)
    3. Service health checks
    4. Initial codebase indexing (index)
    5. Model warmup for optimal performance (warmup)
"""

import sys
import time
import os
import hashlib
import shutil
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.live import Live
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("Error: 'rich' library is required for quickstart.", file=sys.stderr)
    print("Install with: pip install rich", file=sys.stderr)

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError
from scripts.ctx_cli.utils.docker import (
    run_docker_compose,
    wait_for_health_check,
    is_neo4j_enabled,
)
from scripts.ctx_cli.utils.config import get_health_checks
from scripts.ctx_cli.utils.env import load_env_file, find_env_file
from scripts.ctx_cli.commands.init import (
    check_existing_config,
    find_docker_compose,
    suggest_collection_name,
)

console = Console() if RICH_AVAILABLE else None

def _coerce_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _resolve_compose_root() -> Path:
    compose_path = find_docker_compose()
    if compose_path:
        return compose_path.parent
    return Path.cwd()


def _resolve_dev_workspace(compose_root: Path) -> Path:
    """
    Resolve the host path that is bind-mounted into containers as `/work`.

    Docker Compose evaluates `HOST_INDEX_PATH` relative to the compose file directory,
    so we do the same for a consistent UX.
    """
    raw = os.environ.get("HOST_INDEX_PATH")
    if not raw:
        env_path = compose_root / ".env"
        if env_path.exists():
            raw = load_env_file(env_path).get("HOST_INDEX_PATH")

    if raw:
        p = Path(str(raw)).expanduser()
        return (p if p.is_absolute() else (compose_root / p)).resolve()

    return (compose_root / "dev-workspace").resolve()


def _multi_repo_mode_enabled(compose_root: Path) -> bool:
    raw = os.environ.get("MULTI_REPO_MODE")
    if raw is None:
        env_path = compose_root / ".env"
        if env_path.exists():
            raw = load_env_file(env_path).get("MULTI_REPO_MODE")
    return _coerce_bool(raw, default=False)


def _find_existing_import(source: Path, dev_workspace: Path) -> Optional[Path]:
    """
    Check if source path is already imported into dev_workspace.

    Looks for:
    1. Exact name match: dev_workspace/repo-name
    2. Hash-suffixed match: dev_workspace/repo-name-<hash>
    3. Symlink pointing to source

    Returns the existing import path if found, None otherwise.
    """
    if not dev_workspace.exists():
        return None

    base = source.name or "repo"
    source_resolved = source.resolve()

    # Check exact name match
    exact = dev_workspace / base
    if exact.exists():
        if exact.is_symlink() and exact.resolve() == source_resolved:
            return exact
        if exact.is_dir():
            # Could be a copy - check if it looks like the same repo
            # (simple heuristic: check if key files exist)
            if (exact / ".git").exists() or (exact / "package.json").exists() or (exact / "pyproject.toml").exists():
                return exact

    # Check hash-suffixed versions
    digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
    hashed = dev_workspace / f"{base}-{digest}"
    if hashed.exists() and hashed.is_dir():
        return hashed

    # Scan for any symlink pointing to source
    try:
        for entry in dev_workspace.iterdir():
            if entry.is_symlink() and entry.resolve() == source_resolved:
                return entry
    except Exception:
        pass

    return None


def _import_repo_into_workspace(source: Path, dev_workspace: Path) -> Path:
    """
    Copy a repo into `dev_workspace` so containers can index it under `/work`.

    We avoid symlinks here because `/work` is typically a bind mount; symlinks that
    point outside the mount are not visible inside containers.
    """
    dev_workspace.mkdir(parents=True, exist_ok=True)

    base = source.name or "repo"
    target = dev_workspace / base

    if target.exists():
        digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
        target = dev_workspace / f"{base}-{digest}"

    if target.exists():
        if not target.is_dir():
            raise ValueError(f"Import target exists and is not a directory: {target}")
        return target

    shutil.copytree(source, target, symlinks=True)
    return target


def check_docker_available() -> tuple[bool, str]:
    """
    Check if Docker and Docker Compose are available.

    Returns:
        (is_available, error_message)
    """
    import subprocess

    try:
        # Check docker
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False, "Docker is not installed or not running"

        # Check docker compose
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False, "Docker Compose is not installed"

        return True, ""

    except subprocess.TimeoutExpired:
        return False, "Docker command timed out - is Docker running?"
    except FileNotFoundError:
        return False, "Docker is not installed"
    except Exception as e:
        return False, f"Error checking Docker: {str(e)}"


def check_docker_compose_file() -> tuple[bool, Optional[Path]]:
    """
    Check if docker-compose.yml exists.

    Returns:
        (exists, path)
    """
    compose_path = find_docker_compose()
    if compose_path:
        return True, compose_path
    return False, None


def step_init(force: bool, skip_interactive: bool) -> int:
    """
    Step 1: Initialize configuration.

    Args:
        force: Force overwrite of existing config
        skip_interactive: Skip interactive wizard if config exists

    Returns:
        Exit code (0 for success)
    """
    console.print(Panel(
        "[bold cyan]Step 1: Environment Setup[/bold cyan]",
        border_style="cyan"
    ))

    # Check if config already exists
    exists, config_path = check_existing_config(global_mode=False)

    if exists and not force:
        if skip_interactive:
            console.print(f"[green]✓[/green] Using existing configuration: {config_path}\n")
            return 0
        else:
            console.print(f"[yellow]![/yellow] Configuration already exists: {config_path}")
            console.print("[dim]Use --force to overwrite or skip this step[/dim]\n")
            return 0

    # For quickstart, we do a simplified non-interactive setup
    console.print("[dim]Detecting environment...[/dim]")

    # Check for docker-compose.yml
    has_compose, compose_path = check_docker_compose_file()

    if not has_compose:
        console.print("[red]✗[/red] docker-compose.yml not found in current or parent directories")
        console.print("\n[yellow]Please run this from the Context-Engine directory or run:[/yellow]")
        console.print("  [cyan]ctx init[/cyan]  # Interactive setup wizard")
        return 1

    console.print(f"[green]✓[/green] Found docker-compose.yml: {compose_path}")

    # Auto-detect workspace
    workspace_path = Path.cwd()

    # PRIORITY ORDER for COLLECTION_NAME:
    # 1. Already set in environment (from shell or parent process)
    # 2. From .env file in workspace
    # 3. Fall back to suggest_collection_name()
    collection_name = os.environ.get("COLLECTION_NAME")

    if not collection_name:
        # Try loading from .env file
        env_path = workspace_path / ".env"
        if env_path.exists():
            env_vars = load_env_file(env_path)
            collection_name = env_vars.get("COLLECTION_NAME")
            if collection_name:
                console.print(f"[green]✓[/green] Loaded COLLECTION_NAME from .env")

    if not collection_name:
        # Fall back to generating a name
        collection_name = suggest_collection_name(workspace_path)
        console.print(f"[yellow]![/yellow] No COLLECTION_NAME found, using: {collection_name}")

    console.print(f"[green]✓[/green] Workspace: {workspace_path}")
    console.print(f"[green]✓[/green] Collection: {collection_name}")

    # Set environment variables for this session
    os.environ["COLLECTION_NAME"] = collection_name
    os.environ["WORKSPACE_PATH"] = str(workspace_path)

    console.print("[green]✓[/green] Environment configured\n")
    return 0


def step_up(build: bool, wait_timeout: int, no_llama: bool = False) -> int:
    """
    Step 2: Start Docker services.

    Args:
        build: Rebuild containers
        wait_timeout: Health check timeout
        no_llama: Skip the llamacpp (local LLM) container

    Returns:
        Exit code (0 for success)
    """
    console.print(Panel(
        "[bold cyan]Step 2: Starting Services[/bold cyan]",
        border_style="cyan"
    ))

    # Build docker compose command
    compose_args = ["-d"]
    if build:
        compose_args.append("--build")
        console.print("[dim]Rebuilding containers...[/dim]")

    if no_llama:
        compose_args.extend(["--scale", "llamacpp=0"])
        console.print("[dim]Skipping local LLM container (--no-llama)[/dim]")

    # Check if Neo4j is enabled
    if is_neo4j_enabled():
        console.print("[cyan]Neo4j graph backend enabled[/cyan] (NEO4J_GRAPH=1)")

    try:
        # Start services (quiet=True suppresses docker compose warnings)
        run_docker_compose("up", *compose_args, quiet=True)

        # Wait for health checks with spinner
        console.print("[dim]Waiting for services to become healthy...[/dim]\n")

        start_time = time.time()
        results = {}

        def create_status_table(results: dict, current_service: str = None, current_port: int = None) -> Table:
            """Create a fresh status table with current results."""
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("Status", style="bold")
            table.add_column("Service", style="cyan")
            table.add_column("Info", style="dim")

            for name, result in results.items():
                status = "[green]✓[/green]" if result["success"] else "[red]✗[/red]"
                info = f"port {result['port']}"
                table.add_row(status, f"{name}:", info)

            if current_service:
                table.add_row("[yellow]◉[/yellow]", f"{current_service}:", f"checking port {current_port}")

            return table

        with Live(create_status_table(results), console=console, refresh_per_second=4) as live:
            for service in get_health_checks():
                name = service["name"]
                port = service["port"]
                host = service["host"]

                # Update display with current service being checked
                live.update(create_status_table(results, name, port))

                # Perform health check
                success, elapsed = wait_for_health_check(
                    host=host,
                    port=port,
                    timeout=float(wait_timeout),
                    check_interval=0.5,
                )

                results[name] = {
                    "success": success,
                    "elapsed": elapsed,
                    "port": port,
                }

            # Final table update
            live.update(create_status_table(results))

        total_elapsed = time.time() - start_time

        # Check if all succeeded
        all_success = all(r["success"] for r in results.values())

        if all_success:
            console.print(f"\n[green]✓[/green] All services healthy in {total_elapsed:.1f}s\n")
            return 0
        else:
            console.print(f"\n[red]✗[/red] Some services failed to start\n")
            failed = [name for name, r in results.items() if not r["success"]]
            console.print(f"[red]Failed services:[/red] {', '.join(failed)}")
            console.print("\n[yellow]Try running:[/yellow]")
            console.print("  [cyan]docker compose logs[/cyan]  # View logs")
            console.print("  [cyan]ctx quickstart --build[/cyan]  # Rebuild containers")
            return 1

    except Exception as e:
        console.print(f"\n[red]Error starting services:[/red] {e}\n")
        return 1


def step_index(
    skip_index: bool,
    recreate: bool,
    paths: list[str] = None,
    import_repos: bool = False,
) -> int:
    """
    Step 3: Index the codebase.

    SAFE: Only indexes if collection is empty or --recreate is explicitly set.

    Args:
        skip_index: Skip indexing step
        recreate: Recreate collection (user explicitly requested)
        paths: List of paths to index (if None, uses current directory)

    Returns:
        Exit code (0 for success)
    """
    if skip_index:
        console.print(Panel(
            "[bold cyan]Step 3: Indexing[/bold cyan]\n[yellow]Skipped (--no-index)[/yellow]",
            border_style="cyan"
        ))
        return 0

    console.print(Panel(
        "[bold cyan]Step 3: Indexing Codebase[/bold cyan]",
        border_style="cyan"
    ))

    # Determine paths to index
    explicit_paths = bool(paths)
    compose_root = _resolve_compose_root()
    dev_workspace = _resolve_dev_workspace(compose_root)
    cwd = Path.cwd()

    if not paths:
        # No paths provided - detect smart defaults
        # Check if HOST_INDEX_PATH (dev_workspace) has content to index
        dev_workspace_has_content = False
        if dev_workspace.exists():
            # Check for actual content (not just .gitkeep)
            contents = [f for f in dev_workspace.iterdir() if f.name != ".gitkeep"]
            dev_workspace_has_content = len(contents) > 0

        # Determine the best default path
        if dev_workspace_has_content and dev_workspace != cwd:
            # HOST_INDEX_PATH has content - offer to index it
            console.print(f"[green]✓[/green] Detected HOST_INDEX_PATH: [cyan]{dev_workspace}[/cyan]")
            if dev_workspace.exists():
                contents = [f.name for f in dev_workspace.iterdir() if f.name != ".gitkeep"]
                if contents:
                    console.print(f"[dim]  Contains: {', '.join(contents[:5])}{'...' if len(contents) > 5 else ''}[/dim]")
            console.print()

            try:
                response = console.input(
                    f"[bold]Index dev-workspace?[/bold] [dim](Y/n)[/dim] "
                )
            except (EOFError, KeyboardInterrupt):
                response = "n"  # Default to skip on interrupt for less surprising behavior

            if response.lower().strip() not in ("n", "no"):
                paths = [str(dev_workspace)]
                explicit_paths = False
            else:
                # User declined, ask for custom paths
                paths = None

        elif cwd == compose_root:
            # User is in the Context-Engine source directory
            console.print(f"[yellow]![/yellow] You're in the Context-Engine source directory.")
            console.print(f"[dim]  HOST_INDEX_PATH is set to: {dev_workspace}[/dim]\n")

            if dev_workspace_has_content:
                console.print(f"[dim]  dev-workspace has content to index.[/dim]")
                paths = [str(dev_workspace)]
            else:
                console.print(f"[dim]  dev-workspace is empty. Add repos there or provide paths to index.[/dim]\n")
                paths = None

        if paths is None:
            # Ask user for paths
            console.print(f"[yellow]No paths specified.[/yellow]")
            console.print(f"[dim]Current directory: {cwd}[/dim]")
            console.print(f"[dim]HOST_INDEX_PATH: {dev_workspace}[/dim]\n")

            try:
                response = console.input(
                    "[bold]Index current directory?[/bold] [dim](Y/n)[/dim] "
                )
            except (EOFError, KeyboardInterrupt):
                response = "n"

            if response.lower().strip() in ("n", "no"):
                # Ask for paths
                console.print("\n[bold]Enter paths to index[/bold] [dim](comma-separated, or one per line)[/dim]")
                console.print("[dim]Press Enter twice when done:[/dim]\n")

                input_paths = []
                try:
                    while True:
                        line = console.input("  [cyan]>[/cyan] ").strip()
                        if not line:
                            if input_paths:
                                break
                            continue
                        # Handle comma-separated paths
                        for p in line.split(","):
                            p = p.strip()
                            if p:
                                input_paths.append(p)
                except (EOFError, KeyboardInterrupt):
                    pass

                if not input_paths:
                    console.print("\n[red]✗[/red] No paths provided. Skipping indexing.\n")
                    return 0

                paths = input_paths
                explicit_paths = True
            else:
                paths = [str(cwd)]
                explicit_paths = False

    # Validate and resolve paths
    resolved_paths = []
    for p in paths:
        path = Path(p).expanduser().resolve()
        if not path.exists():
            console.print(f"[red]✗[/red] Path does not exist: {p}")
            return 1
        if not path.is_dir():
            console.print(f"[red]✗[/red] Not a directory: {p}")
            return 1
        resolved_paths.append(path)

    multi_repo_mode = _multi_repo_mode_enabled(compose_root)

    # Ensure all indexed paths are visible to containers under `/work` (dev_workspace).
    # If a path is outside the mount, check if already imported or offer to copy it.
    paths_to_index = []
    for path in resolved_paths:
        if path.is_relative_to(dev_workspace):
            paths_to_index.append(path)
            continue

        # Check if this is the Context-Engine source repo itself (where compose lives)
        # The source repo is mounted via HOST_INDEX_PATH, not via dev-workspace import
        if path == compose_root:
            # Check if HOST_INDEX_PATH points to the source repo (correct for self-indexing)
            env_host_path = os.environ.get("HOST_INDEX_PATH", "")
            if env_host_path in (".", "./", str(compose_root)):
                # Source repo is correctly configured for indexing
                console.print(f"[green]✓[/green] Context-Engine source repo detected")
                paths_to_index.append(path)
                continue
            else:
                # HOST_INDEX_PATH points to dev-workspace, not source
                # Source repo cannot be indexed with current config
                console.print(
                    f"[yellow]![/yellow] This is the Context-Engine source repo.\n"
                    f"  Current HOST_INDEX_PATH points to: [cyan]{env_host_path or './dev-workspace'}[/cyan]\n"
                    f"  To index the source repo itself, set HOST_INDEX_PATH=. in .env\n"
                )
                return 0  # Skip - can't index source with current config

        # Check if this path is already imported into dev-workspace
        existing = _find_existing_import(path, dev_workspace)
        if existing:
            console.print(f"[green]✓[/green] Already in dev-workspace: [cyan]{existing.name}[/cyan]")
            paths_to_index.append(existing)
            continue

        # Path is outside the mount and not yet imported
        console.print(
            f"[yellow]![/yellow] Path is outside the mounted workspace (HOST_INDEX_PATH):\n"
            f"  Source: [cyan]{path}[/cyan]\n"
            f"  Mounted: [cyan]{dev_workspace}[/cyan]\n"
        )
        if not import_repos:
            try:
                resp = console.input(
                    "[bold]Copy this repo into dev-workspace so containers can index it?[/bold] [dim](Y/n)[/dim] "
                )
            except (EOFError, KeyboardInterrupt):
                resp = "n"

            if resp.lower().strip() in ("n", "no"):
                console.print(
                    "[red]✗[/red] Cannot index paths outside the mounted workspace.\n"
                    "[dim]Either move the repo under HOST_INDEX_PATH, restart services with a wider HOST_INDEX_PATH, or re-run with --import-repos to copy it into dev-workspace.[/dim]\n"
                )
                return 1

        try:
            imported = _import_repo_into_workspace(path, dev_workspace)
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to import {path}: {e}")
            return 1

        console.print(f"[green]✓[/green] Imported into dev-workspace: [cyan]{imported}[/cyan]")
        paths_to_index.append(imported)

    resolved_paths = paths_to_index

    # Build list of (path, subdir, collection) tuples
    # Each external repo gets its own collection based on directory name
    # IMPORTANT: Only create separate collections for actual git repos, not subdirectories
    index_targets = []
    for p in resolved_paths:
        try:
            rel = p.relative_to(dev_workspace)
            subdir = rel.as_posix()
        except ValueError:
            subdir = ""

        # Determine collection for this path
        # Only create a separate collection if this is an actual git repo root
        is_git_repo = (p / ".git").exists()

        if subdir and is_git_repo and multi_repo_mode:
            # External git repo - derive collection from dir name
            repo_collection = suggest_collection_name(p)
        else:
            # Main workspace OR subdirectory (not a separate repo) - use COLLECTION_NAME from env
            repo_collection = os.environ.get("COLLECTION_NAME", "")

        index_targets.append((p, subdir, repo_collection))

    # Show what will be indexed
    mode_str = "multi-repo" if multi_repo_mode else "single-repo"
    console.print(f"\n[dim]Indexing {len(resolved_paths)} path(s) ({mode_str} mode):[/dim]")
    for p, subdir, coll in index_targets:
        mounted_as = "/work" if not subdir else f"/work/{subdir}"
        coll_display = f"[yellow]{coll}[/yellow]" if coll else "[dim]auto[/dim]"
        console.print(f"  [cyan]•[/cyan] {p.name} → {coll_display} [dim]({mounted_as})[/dim]")
    console.print()

    start_time = time.time()

    try:
        client = MCPClient(server="indexer", timeout=600)

        # ─── Show existing collections ───────────────────────────────────────────
        console.print("[dim]Checking existing collections...[/dim]")

        all_collections = {}  # name -> count
        try:
            collections_result = client.call_tool("qdrant_list")
            for coll in collections_result.get("collections", []):
                if coll.endswith("_graph"):
                    continue
                try:
                    stats = client.call_tool("qdrant_status", collection=coll)
                    all_collections[coll] = stats.get("count", 0)
                except Exception:
                    all_collections[coll] = 0
        except Exception:
            pass

        if all_collections:
            console.print(f"\n[bold]Existing collections ({len(all_collections)}):[/bold]")
            for coll, count in sorted(all_collections.items(), key=lambda x: -x[1]):
                if count > 0:
                    console.print(f"  [green]●[/green] {coll}: [cyan]{count:,}[/cyan] chunks")
                else:
                    console.print(f"  [dim]○[/dim] {coll}: [dim]empty[/dim]")
        else:
            console.print("\n[dim]No existing collections found.[/dim]")

        # ─── Multi-repo mode explanation ─────────────────────────────────────────
        if multi_repo_mode:
            console.print(
                f"\n[yellow]ℹ[/yellow] [bold]MULTI_REPO_MODE=1[/bold]: "
                f"Each repo gets its own collection. Indexing {len(index_targets)} repo(s) sequentially."
            )
        else:
            console.print(
                f"\n[dim]ℹ MULTI_REPO_MODE=0: All paths indexed into one collection. "
                f"Set MULTI_REPO_MODE=1 in .env for per-repo collections.[/dim]"
            )

        # ─── Check which targets need indexing ───────────────────────────────────
        def find_matching_collection(repo_name: str, collections: dict) -> tuple[str, int]:
            """Find a collection matching repo name (exact or prefix match)."""
            # Normalize for comparison
            normalized = repo_name.lower().replace("_", "-").replace(" ", "-")

            # Exact match first
            if repo_name in collections:
                return repo_name, collections[repo_name]

            # Prefix match (e.g., "context-engine" matches "Context-Engine-41e67959")
            for coll, count in collections.items():
                coll_norm = coll.lower().replace("_", "-")
                if coll_norm.startswith(normalized) or normalized.startswith(coll_norm.split("-")[0]):
                    if count > 0:
                        return coll, count

            return "", 0

        targets_to_index = []
        for path, subdir, repo_collection in index_targets:
            # Try to find existing collection for this repo
            if repo_collection:
                matched_coll, existing_count = find_matching_collection(repo_collection, all_collections)
            else:
                matched_coll, existing_count = find_matching_collection(path.name, all_collections)

            if recreate:
                targets_to_index.append((path, subdir, matched_coll or repo_collection, "recreate"))
            elif existing_count > 0 and not explicit_paths:
                console.print(f"  [green]✓[/green] {path.name}: already indexed in [yellow]{matched_coll}[/yellow] ({existing_count:,} chunks)")
            else:
                targets_to_index.append((path, subdir, repo_collection, "new" if existing_count == 0 else "update"))

        if not targets_to_index:
            elapsed = time.time() - start_time
            console.print(f"\n[green]✓[/green] All paths already indexed ({elapsed:.1f}s)")
            console.print(f"  [dim]Use --recreate to reindex[/dim]\n")
            return 0

        console.print(f"\n[dim]Indexing {len(targets_to_index)} path(s)...[/dim]\n")

        # Index each target and verify collection creation
        indexed_collections = {}  # collection -> chunk count
        failed_repos = []
        recreated_collections = set()  # Track which collections have been recreated

        for i, (path, subdir, repo_collection, action) in enumerate(targets_to_index):
            repo_start = time.time()

            # In single-repo mode, only recreate a collection once
            # (subsequent paths to the same collection should just index, not recreate)
            effective_action = action
            if action == "recreate" and repo_collection in recreated_collections:
                effective_action = "update"

            action_str = "Recreating" if effective_action == "recreate" else "Indexing"
            console.print(f"[cyan]({i+1}/{len(targets_to_index)})[/cyan] {action_str} [bold]{path.name}[/bold]...")
            if repo_collection:
                console.print(f"  [dim]Collection: {repo_collection}[/dim]")

            # Build kwargs for MCP call
            kwargs = {"recreate": effective_action == "recreate"}
            if repo_collection:
                kwargs["collection"] = repo_collection

            # Track that we've recreated this collection
            if effective_action == "recreate" and repo_collection:
                recreated_collections.add(repo_collection)

            try:
                if subdir:
                    result = client.call_tool("qdrant_index", subdir=subdir, **kwargs)
                else:
                    result = client.call_tool("qdrant_index_root", **kwargs)

                repo_elapsed = time.time() - repo_start

                if result.get("ok", False):
                    # Verify collection has data
                    verify_collection = repo_collection or result.get("args", {}).get("collection", "")
                    chunk_count = 0
                    if verify_collection:
                        try:
                            stats = client.call_tool("qdrant_status", collection=verify_collection)
                            chunk_count = stats.get("count", 0)
                        except Exception:
                            pass

                    if chunk_count > 0:
                        console.print(
                            f"  [green]✓[/green] Indexed {result.get('total_files', 0)} files → "
                            f"[cyan]{chunk_count:,}[/cyan] chunks ({repo_elapsed:.1f}s)"
                        )
                        indexed_collections[verify_collection] = chunk_count
                    else:
                        console.print(
                            f"  [yellow]⚠[/yellow] Indexed but collection empty ({repo_elapsed:.1f}s)"
                        )
                        failed_repos.append((path.name, "Collection empty after indexing"))
                else:
                    error_msg = result.get("error", "Unknown error")
                    console.print(f"  [red]✗[/red] Failed: {error_msg} ({repo_elapsed:.1f}s)")
                    failed_repos.append((path.name, error_msg))
                    if not multi_repo_mode:
                        return 1  # In single-repo mode, fail fast

            except Exception as e:
                repo_elapsed = time.time() - repo_start
                console.print(f"  [red]✗[/red] Error: {str(e)} ({repo_elapsed:.1f}s)")
                failed_repos.append((path.name, str(e)))
                if not multi_repo_mode:
                    return 1

            console.print()  # Blank line between repos

        elapsed = time.time() - start_time

        # Summary
        if indexed_collections:
            total_chunks = sum(indexed_collections.values())
            console.print(
                f"[green]✓[/green] Indexed [cyan]{len(indexed_collections)}[/cyan] collection(s), "
                f"[cyan]{total_chunks:,}[/cyan] total chunks in [cyan]{elapsed:.1f}s[/cyan]"
            )
            for coll, count in indexed_collections.items():
                console.print(f"  [green]●[/green] {coll}: {count:,} chunks")

        if failed_repos:
            console.print(f"\n[yellow]⚠[/yellow] {len(failed_repos)} repo(s) failed:")
            for repo_name, error in failed_repos:
                console.print(f"  [red]✗[/red] {repo_name}: {error}")
            console.print()
            return 1 if not indexed_collections else 0  # Partial success OK

        console.print()

        return 0

    except MCPError as e:
        console.print(f"\n[red]✗[/red] MCP error: {e.message}\n")
        console.print("[yellow]Services may not be fully ready. Try:[/yellow]")
        console.print("  [cyan]ctx status[/cyan]  # Check service status")
        return 1
    except Exception as e:
        console.print(f"\n[red]✗[/red] Indexing failed: {str(e)}\n")
        return 1


def step_warmup(skip_warmup: bool) -> int:
    """
    Step 4: Warm up models.

    Args:
        skip_warmup: Skip warmup step

    Returns:
        Exit code (0 for success)
    """
    if skip_warmup:
        console.print(Panel(
            "[bold cyan]Step 4: Model Warmup[/bold cyan]\n[yellow]Skipped (--no-warmup)[/yellow]",
            border_style="cyan"
        ))
        return 0

    console.print(Panel(
        "[bold cyan]Step 4: Model Warmup[/bold cyan]",
        border_style="cyan"
    ))

    console.print("[dim]Preloading embedding and reranking models...[/dim]\n")

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Warming up models...", total=None)

            # Call warmup status to check current state
            client = MCPClient(server="indexer", timeout=60)
            status = client.call_tool("warmup_status")

            progress.update(task, completed=True)

        # Check warmup status
        warmup_status = status.get("status", "unknown")
        latency_ms = status.get("latency_ms") or status.get("total_ms")

        if warmup_status == "warm":
            console.print(f"[green]✓[/green] Models already warm (latency: {latency_ms:.1f}ms)\n")
            return 0
        elif warmup_status == "warming":
            console.print("[yellow]![/yellow] Models are currently warming up...\n")
            # Wait a bit and check again
            time.sleep(2)
            status = client.call_tool("warmup_status")
            warmup_status = status.get("status", "unknown")
            latency_ms = status.get("latency_ms") or status.get("total_ms")

            if warmup_status == "warm":
                console.print(f"[green]✓[/green] Models warmed up (latency: {latency_ms:.1f}ms)\n")
                return 0

        # Models should be auto-warmed by the server on startup
        # If still cold, that's okay - they'll warm on first use
        if warmup_status == "cold":
            console.print("[yellow]![/yellow] Models will warm up on first use\n")
            return 0

        if warmup_status == "failed":
            error = status.get("error", "Unknown error")
            console.print(f"[yellow]![/yellow] Warmup failed: {error}")
            console.print("[dim]Models will still work, but first query may be slower[/dim]\n")
            return 0

        console.print(f"[green]✓[/green] Models ready\n")
        return 0

    except MCPError as e:
        console.print(f"[yellow]![/yellow] Could not check warmup status: {e.message}")
        console.print("[dim]Models will warm up on first use[/dim]\n")
        return 0
    except Exception as e:
        console.print(f"[yellow]![/yellow] Warmup check failed: {str(e)}")
        console.print("[dim]Models will warm up on first use[/dim]\n")
        return 0


def run_quickstart(args) -> int:
    """
    Run the quickstart command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    if not RICH_AVAILABLE:
        return 1

    # ASCII art banner
    ascii_art = """
[bold cyan]
   ██████╗ ██████╗ ███╗   ██╗████████╗███████╗██╗  ██╗████████╗
  ██╔════╝██╔═══██╗████╗  ██║╚══██╔══╝██╔════╝╚██╗██╔╝╚══██╔══╝
  ██║     ██║   ██║██╔██╗ ██║   ██║   █████╗   ╚███╔╝    ██║
  ██║     ██║   ██║██║╚██╗██║   ██║   ██╔══╝   ██╔██╗    ██║
  ╚██████╗╚██████╔╝██║ ╚████║   ██║   ███████╗██╔╝ ██╗   ██║
   ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝   ╚═╝

  ███████╗███╗   ██╗ ██████╗ ██╗███╗   ██╗███████╗
  ██╔════╝████╗  ██║██╔════╝ ██║████╗  ██║██╔════╝
  █████╗  ██╔██╗ ██║██║  ███╗██║██╔██╗ ██║█████╗
  ██╔══╝  ██║╚██╗██║██║   ██║██║██║╚██╗██║██╔══╝
  ███████╗██║ ╚████║╚██████╔╝██║██║ ╚████║███████╗
  ╚══════╝╚═╝  ╚═══╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝╚══════╝
[/bold cyan]
[dim]         << KNOW YOUR CODE, OWN YOUR CODE >>[/dim]
"""
    console.print(ascii_art)

    # Pre-flight checks
    console.print("[bold]Pre-flight Checks[/bold]")
    console.print()

    # Check Docker
    docker_ok, docker_error = check_docker_available()
    if not docker_ok:
        console.print(f"[red]✗[/red] Docker check failed: {docker_error}")
        console.print("\n[yellow]Please install Docker Desktop and ensure it's running:[/yellow]")
        console.print("  https://www.docker.com/products/docker-desktop")
        return 1
    console.print("[green]✓[/green] Docker available")

    # Check docker-compose.yml
    has_compose, compose_path = check_docker_compose_file()
    if not has_compose:
        console.print("[red]✗[/red] docker-compose.yml not found")
        console.print("\n[yellow]Please run this from the Context-Engine directory[/yellow]")
        return 1
    console.print(f"[green]✓[/green] Found {compose_path}")
    console.print()

    # Get paths from args (may be None or empty list)
    paths = getattr(args, "paths", None) or []

    # Execute steps
    no_llama = getattr(args, "no_llama", False)
    steps = [
        ("init", lambda: step_init(args.force, skip_interactive=True)),
        ("up", lambda: step_up(args.build, args.wait, no_llama=no_llama)),
        ("index", lambda: step_index(args.no_index, args.recreate, paths, args.import_repos)),
        ("warmup", lambda: step_warmup(args.no_warmup)),
    ]

    for step_name, step_func in steps:
        try:
            exit_code = step_func()
            if exit_code != 0:
                console.print(Panel(
                    f"[red]Quickstart failed at step: {step_name}[/red]\n\n"
                    f"You can continue from this point by running:\n"
                    f"  [cyan]ctx {step_name}[/cyan]  # Run this step manually\n\n"
                    f"Or debug with:\n"
                    f"  [cyan]ctx status[/cyan]  # Check service status\n"
                    f"  [cyan]docker compose logs[/cyan]  # View logs",
                    title=f"Failed at Step: {step_name}",
                    border_style="red"
                ))
                return exit_code
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Quickstart interrupted by user[/yellow]")
            return 1
        except Exception as e:
            console.print(f"\n[red]Unexpected error in step {step_name}:[/red] {e}")
            import traceback
            traceback.print_exc()
            return 1

    # Success!
    console.print()
    console.print(Panel.fit(
        "[bold green]✓ Quickstart Complete![/bold green]\n\n"
        "[cyan]Context-Engine is ready to use[/cyan]\n\n"
        "Try these commands:\n"
        "  [cyan]ctx search 'your query'[/cyan]  # Search your codebase\n"
        "  [cyan]ctx answer 'how does X work?'[/cyan]  # Ask questions\n"
        "  [cyan]ctx status[/cyan]  # Check system status\n"
        "  [cyan]ctx --help[/cyan]  # See all commands",
        border_style="green"
    ))
    console.print()

    return 0


def register_command(subparsers):
    """Register the quickstart command with the CLI parser."""
    parser = subparsers.add_parser(
        "quickstart",
        help="One command setup - init, start, index, and warmup",
        description=(
            "The ONE COMMAND to rule them all. Detects environment, starts services, "
            "indexes the codebase, and warms up models for optimal performance.\n\n"
            "If no paths are provided, you will be prompted to confirm indexing the "
            "current directory or enter paths to index."
        )
    )

    parser.add_argument(
        "paths",
        nargs="*",
        default=[],
        help="Paths to index (default: prompts for current directory)"
    )

    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force overwrite of existing configuration"
    )

    parser.add_argument(
        "--build",
        action="store_true",
        help="Rebuild Docker containers before starting"
    )

    parser.add_argument(
        "--wait",
        type=int,
        default=30,
        help="Health check timeout in seconds (default: 30)"
    )

    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Skip initial indexing step"
    )

    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip model warmup step"
    )

    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate Qdrant collection (drops existing data)"
    )

    parser.add_argument(
        "--import-repos",
        action="store_true",
        help="Copy repos outside HOST_INDEX_PATH into dev-workspace so containers can index them"
    )

    parser.add_argument(
        "--no-llama",
        action="store_true",
        help="Skip the local LLM container (llamacpp) - for users without GPU or who use cloud LLM APIs"
    )

    parser.set_defaults(func=run_quickstart)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Context-Engine Quickstart")

    parser.add_argument("paths", nargs="*", default=[],
                       help="Paths to index (default: prompts for current directory)")
    parser.add_argument("--force", "-f", action="store_true",
                       help="Force overwrite of existing configuration")
    parser.add_argument("--build", action="store_true",
                       help="Rebuild Docker containers")
    parser.add_argument("--wait", type=int, default=30,
                       help="Health check timeout in seconds")
    parser.add_argument("--no-index", action="store_true",
                       help="Skip indexing step")
    parser.add_argument("--no-warmup", action="store_true",
                       help="Skip warmup step")
    parser.add_argument("--recreate", action="store_true",
                       help="Recreate collection")
    parser.add_argument("--import-repos", action="store_true",
                       help="Copy repos outside HOST_INDEX_PATH into dev-workspace for indexing")
    parser.add_argument("--no-llama", action="store_true",
                       help="Skip local LLM container (for users without GPU or using cloud APIs)")

    args = parser.parse_args()
    sys.exit(run_quickstart(args))
