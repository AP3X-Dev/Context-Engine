#!/usr/bin/env python3
"""
ingest/cli.py - Command-line interface for code indexing.

This module provides the CLI argument parsing and main() function for running
the indexer as a standalone script.
"""
from __future__ import annotations

import logging
import os
import argparse
from pathlib import Path

from scripts.ingest.config import (
    is_multi_repo_mode,
    get_collection_name,
)
from scripts.ingest.pipeline import index_repo
from scripts.ingest.pseudo import generate_pseudo_tags

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Index code into Qdrant with metadata for MCP code search."
    )
    parser.add_argument("--root", type=str, default=".", help="Root directory to index")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate the collection before indexing",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Do not delete existing points for each file before inserting",
    )
    parser.add_argument(
        "--no-skip-unchanged",
        action="store_true",
        help="Do not skip files whose content hash matches existing index",
    )
    parser.add_argument(
        "--schema-mode",
        type=str,
        default=None,
        choices=["validate", "create", "migrate"],
        help=(
            "Schema handling mode: validate (read-only), create (create if missing), "
            "migrate (add missing vectors/indexes). Default preserves legacy behavior."
        ),
    )
    # Exclusion controls
    parser.add_argument(
        "--ignore-file",
        type=str,
        default=None,
        help="Path to a .qdrantignore-style file of patterns to exclude",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Disable default exclusions (models, node_modules, build, venv, .git, etc.)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        help="Additional exclude pattern(s); can be used multiple times or comma-separated",
    )
    # Scaling controls
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Embedding/upsert batch size (default 64)",
    )
    parser.add_argument(
        "--chunk-lines",
        type=int,
        default=None,
        help="Max lines per chunk (default 120)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=None,
        help="Overlap lines between chunks (default 20)",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=None,
        help="Print progress every N files (default 200; 0 disables)",
    )
    # GLM pseudo tag test
    parser.add_argument(
        "--test-pseudo",
        type=str,
        default=None,
        help="Test generate_pseudo_tags on the given code snippet and print result, then exit",
    )
    parser.add_argument(
        "--test-pseudo-file",
        type=str,
        default=None,
        help="Test generate_pseudo_tags on the contents of the given file and print result, then exit",
    )

    return parser.parse_args()


def _run_post_index_backfill(qdrant_url: str, api_key: str, collection: str, model_name: str) -> None:
    """Run post-indexing backfill for pseudo-tags and graph edges."""
    from scripts.ingest.pipeline import pseudo_backfill_tick, graph_backfill_tick
    from qdrant_client import QdrantClient

    try:
        # Get model dimension for vector operations
        try:
            from scripts.embedder import get_model_dimension
            dim = get_model_dimension(model_name)
        except Exception:
            dim = 384  # Default for BGE models

        # Connect to Qdrant
        client = QdrantClient(
            url=qdrant_url,
            api_key=api_key if api_key else None,
            timeout=int(os.environ.get("QDRANT_TIMEOUT", "60")),
        )

        # --- Pseudo backfill ---
        print("[backfill] Starting deferred pseudo-tag generation...")

        # Temporarily enable REFRAG_PSEUDO_DESCRIBE for backfill
        orig_pseudo = os.environ.get("REFRAG_PSEUDO_DESCRIBE")
        os.environ["REFRAG_PSEUDO_DESCRIBE"] = "1"

        pseudo_total = 0
        max_iterations = 1000  # Safety limit
        batch_size = int(os.environ.get("PSEUDO_BACKFILL_BATCH_SIZE", "128"))

        try:
            for iteration in range(max_iterations):
                processed = pseudo_backfill_tick(
                    client,
                    collection,
                    repo_name=None,
                    max_points=batch_size,
                    dim=dim,
                )
                if processed == 0:
                    break
                pseudo_total += processed
                print(f"[backfill] Pseudo: {pseudo_total} points processed...")
        finally:
            # Restore original env
            if orig_pseudo is not None:
                os.environ["REFRAG_PSEUDO_DESCRIBE"] = orig_pseudo
            else:
                os.environ.pop("REFRAG_PSEUDO_DESCRIBE", None)

        print(f"[backfill] Pseudo complete: {pseudo_total} points enriched")

        # --- Graph backfill (Neo4j edges from Qdrant metadata) ---
        neo4j_enabled = (os.environ.get("NEO4J_GRAPH", "") or "").strip().lower() in {"1", "true", "yes", "on"}
        if neo4j_enabled:
            print("[backfill] Starting graph edge backfill...")
            graph_total = 0

            try:
                for iteration in range(max_iterations):
                    processed = graph_backfill_tick(
                        client,
                        collection,
                        repo_name=None,
                        max_points=batch_size,
                    )
                    if processed == 0:
                        break
                    graph_total += processed
                    print(f"[backfill] Graph: {graph_total} points processed...")
            except Exception as e:
                print(f"[backfill] Graph backfill error: {e}")
                logger.warning(f"Graph backfill failed: {e}", exc_info=True)

            print(f"[backfill] Graph complete: {graph_total} points processed for edges")

        print("[backfill] Post-indexing backfill complete")

    except Exception as e:
        print(f"[backfill] Warning: backfill failed: {e}")
        logger.warning(f"Post-index backfill failed: {e}", exc_info=True)


# Alias for backward compatibility
_run_pseudo_backfill = _run_post_index_backfill


def main():
    """Main entry point for the CLI."""
    # Load .env file for REFRAG_*, GLM_*, and other settings
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent.parent / ".env")
    except ImportError:
        pass  # python-dotenv not installed, rely on exported env vars

    # Backend migration: detect file<->redis switch and migrate state if needed
    try:
        from scripts.workspace_state import detect_and_migrate_backend
        ws_root = Path(os.environ.get("WORKSPACE_PATH") or os.environ.get("WATCH_ROOT") or "/work")
        migrated = detect_and_migrate_backend(ws_root)
        if migrated is not None:
            print(f"[backend_migration] Migrated {migrated} items to new backend")
    except Exception as e:
        logger.warning(f"Backend migration check failed (continuing): {e}")

    args = parse_args()

    # Map CLI overrides to env so downstream helpers pick them up
    if args.ignore_file:
        os.environ["QDRANT_IGNORE_FILE"] = args.ignore_file
    if args.no_default_excludes:
        os.environ["QDRANT_DEFAULT_EXCLUDES"] = "0"
    if args.exclude:
        parts = []
        for e in args.exclude:
            parts.extend([p.strip() for p in str(e).split(",") if p.strip()])
        if parts:
            os.environ["QDRANT_EXCLUDES"] = ",".join(parts)
    if args.batch_size is not None:
        os.environ["INDEX_BATCH_SIZE"] = str(args.batch_size)
    if args.chunk_lines is not None:
        os.environ["INDEX_CHUNK_LINES"] = str(args.chunk_lines)
    if args.chunk_overlap is not None:
        os.environ["INDEX_CHUNK_OVERLAP"] = str(args.chunk_overlap)
    if args.progress_every is not None:
        os.environ["INDEX_PROGRESS_EVERY"] = str(args.progress_every)

    # Optional test mode: exercise generate_pseudo_tags and exit
    if args.test_pseudo or args.test_pseudo_file:
        import json as _json

        code_text = ""
        if args.test_pseudo:
            code_text = args.test_pseudo
        if args.test_pseudo_file:
            try:
                code_text = Path(args.test_pseudo_file).read_text(
                    encoding="utf-8", errors="ignore"
                )
            except Exception as e:
                print(f"[TEST_PSEUDO] Failed to read file {args.test_pseudo_file}: {e}")
                return

        if not code_text.strip():
            print("[TEST_PSEUDO] No code text provided")
            return

        try:
            from scripts.refrag_llamacpp import get_runtime_kind
            runtime = get_runtime_kind()
        except Exception:
            runtime = "unknown"

        pseudo, tags = "", []
        try:
            pseudo, tags = generate_pseudo_tags(code_text)
        except Exception as e:
            print(f"[TEST_PSEUDO] Error while generating pseudo tags: {e}")

        print(
            _json.dumps(
                {
                    "runtime": runtime,
                    "pseudo": pseudo,
                    "tags": tags,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    api_key = os.environ.get("QDRANT_API_KEY")
    collection = os.environ.get("COLLECTION_NAME") or os.environ.get("DEFAULT_COLLECTION") or "codebase"
    model_name = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-base-en-v1.5")

    # Resolve collection name based on multi-repo mode
    multi_repo = bool(is_multi_repo_mode and is_multi_repo_mode())
    if multi_repo:
        print("[multi_repo] Multi-repo mode enabled - will create separate collections per repository")

        root_path = Path(args.root).resolve()
        repos = []
        try:
            if root_path.is_dir():
                for child in sorted(root_path.iterdir()):
                    try:
                        if not child.is_dir():
                            continue
                        if child.name.startswith("."):
                            continue
                        if child.name in {".codebase", "__pycache__"}:
                            continue
                        repos.append(child)
                    except Exception as e:
                        logger.debug(f"Suppressed exception, continuing: {e}")
                        continue
        except Exception:
            repos = []

        if not repos:
            print(f"[multi_repo] No repo directories found under: {root_path}")
            return

        multi_flag = (os.environ.get("PSEUDO_DEFER_TO_WORKER") or "").strip().lower()
        multi_defer_pseudo = multi_flag in {"1", "true", "yes", "on"}
        indexed_collections = set()

        for repo_root in repos:
            repo_name = repo_root.name
            repo_collection = collection
            if get_collection_name:
                try:
                    resolved = get_collection_name(repo_name)
                    if resolved:
                        repo_collection = resolved
                except Exception as e:
                    logger.debug(f"Suppressed exception: {e}")
            if not repo_collection:
                repo_collection = "codebase"

            index_repo(
                repo_root,
                qdrant_url,
                api_key,
                repo_collection,
                model_name,
                args.recreate,
                dedupe=(not args.no_dedupe),
                skip_unchanged=(not args.no_skip_unchanged),
                pseudo_mode="off" if multi_defer_pseudo else "full",
                schema_mode=args.schema_mode,
            )
            indexed_collections.add(repo_collection)

        # Run pseudo backfill for all indexed collections if deferred
        if multi_defer_pseudo:
            for coll in indexed_collections:
                _run_pseudo_backfill(qdrant_url, api_key, coll, model_name)
        return
    else:
        if get_collection_name:
            try:
                resolved = get_collection_name(str(Path(args.root).resolve()))
                placeholders = {"", "default-collection", "my-collection", "codebase"}
                if resolved and collection in placeholders:
                    collection = resolved
            except Exception as e:
                logger.debug(f"Suppressed exception: {e}")
        if not collection:
            collection = os.environ.get("COLLECTION_NAME", "codebase")
        print(f"[single_repo] Single-repo mode enabled - using collection: {collection}")

    flag = (os.environ.get("PSEUDO_DEFER_TO_WORKER") or "").strip().lower()
    defer_pseudo = flag in {"1", "true", "yes", "on"}
    pseudo_mode = "off" if defer_pseudo else "full"

    index_repo(
        Path(args.root).resolve(),
        qdrant_url,
        api_key,
        collection,
        model_name,
        args.recreate,
        dedupe=(not args.no_dedupe),
        skip_unchanged=(not args.no_skip_unchanged),
        pseudo_mode=pseudo_mode,
        schema_mode=args.schema_mode,
    )

    # Run pseudo backfill after indexing if deferred
    if defer_pseudo:
        _run_pseudo_backfill(qdrant_url, api_key, collection, model_name)


if __name__ == "__main__":
    main()
