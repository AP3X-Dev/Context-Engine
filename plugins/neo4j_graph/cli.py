#!/usr/bin/env python3
"""
CLI for Neo4j graph indexing.

Usage:
    # Index from Qdrant graph collection to Neo4j
    python -m plugins.neo4j_graph.cli backfill --collection my-collection
    
    # Index a directory directly to Neo4j
    python -m plugins.neo4j_graph.cli index --path /path/to/code --repo my-repo
    
    # Check Neo4j connection and stats
    python -m plugins.neo4j_graph.cli status
"""
from __future__ import annotations

import argparse
import os
import sys

# Ensure plugin can import from scripts/
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def cmd_status(args):
    """Check Neo4j connection and show stats."""
    from .backend import Neo4jGraphBackend

    backend = Neo4jGraphBackend()
    print(f"Backend: {backend.backend_type}")
    print(f"URI: {os.environ.get('NEO4J_URI', 'bolt://localhost:7687')}")

    # Test connection and get counts
    try:
        driver = backend._get_driver()
        with driver.session() as session:
            result = session.run("MATCH (n:Symbol) RETURN count(n) as nodes")
            nodes = result.single()["nodes"]
            
            result = session.run("MATCH ()-[r:CALLS]->() RETURN count(r) as calls")
            calls = result.single()["calls"]
            
            result = session.run("MATCH ()-[r:IMPORTS]->() RETURN count(r) as imports")
            imports = result.single()["imports"]
            
        print(f"\nGraph Stats:")
        print(f"  Symbols: {nodes}")
        print(f"  CALLS edges: {calls}")
        print(f"  IMPORTS edges: {imports}")
        print("\n✓ Neo4j connection OK")
    except Exception as e:
        print(f"\n✗ Neo4j connection failed: {e}")
        return 1
    return 0


def cmd_backfill(args):
    """Backfill edges from main Qdrant collection to Neo4j.

    Reads code chunks from the main collection and extracts graph edges
    from metadata.calls and metadata.imports fields, using the same
    resolution logic as the main indexing pipeline.
    """
    from qdrant_client import QdrantClient
    from .backend import Neo4jGraphBackend

    # Try to import ingest_adapter for proper symbol resolution
    try:
        from scripts.graph_backends.ingest_adapter import extract_call_edges, extract_import_edges
        use_ingest_adapter = True
    except ImportError:
        from .base import GraphEdge
        use_ingest_adapter = False
        print("  Warning: ingest_adapter not available, edges will have unresolved callee paths")

    collection = args.collection
    limit = args.limit
    clean = getattr(args, 'clean', False)

    print(f"Backfilling from Qdrant {collection} to Neo4j...")

    # Connect to Qdrant
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    client = QdrantClient(url=qdrant_url)

    # Check collection exists
    try:
        info = client.get_collection(collection)
        print(f"  Source: {collection} ({info.points_count} points)")
    except Exception as e:
        print(f"  ✗ Collection {collection} not found: {e}")
        return 1

    # Initialize Neo4j backend
    backend = Neo4jGraphBackend()
    store = backend.ensure_graph_store(collection)
    print(f"  Target: Neo4j ({store})")

    # Clean existing data if requested (batched to avoid memory issues)
    if clean:
        print("  Cleaning existing Neo4j data...")
        try:
            driver = backend._get_driver()
            batch_size = 1000
            total_deleted = 0
            with driver.session() as session:
                while True:
                    result = session.run(
                        """
                        MATCH (n:Symbol {collection: $coll})
                        WITH n LIMIT $batch
                        DETACH DELETE n
                        RETURN count(*) as deleted
                        """,
                        coll=collection,
                        batch=batch_size
                    )
                    deleted = result.single()["deleted"]
                    total_deleted += deleted
                    if deleted < batch_size:
                        break
                print(f"  Deleted {total_deleted} nodes for collection {collection}")
        except Exception as e:
            print(f"  Warning: cleanup failed: {e}")

    # Scroll through collection and extract edges using ingest_adapter for consistent resolution
    edges = []
    offset = None
    total_edges = 0
    total_points = 0

    while True:
        result = client.scroll(
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
            # import_map maps local names to qualified paths for resolution
            # e.g., {"QdrantClient": "qdrant_client.QdrantClient"}
            import_map = meta.get("import_map", {}) or {}
            symbol_signature = meta.get("symbol_signature", "") or ""
            symbol_docstring = meta.get("symbol_docstring", "") or ""

            if use_ingest_adapter:
                # Use ingest_adapter for proper symbol resolution
                call_edges = extract_call_edges(
                    symbol_path=symbol_path,
                    calls=calls,
                    path=path,
                    repo=repo,
                    start_line=start_line,
                    end_line=end_line,
                    language=language,
                    caller_point_id=str(p.id),
                    import_paths=import_map,  # Pass import_map for resolution
                    collection=collection,
                    qdrant_client=client,
                )
                # Enrich edges with symbol metadata
                for edge in call_edges:
                    edge.caller_signature = symbol_signature
                    edge.caller_docstring = symbol_docstring
                edges.extend(call_edges)

                import_edges = extract_import_edges(
                    symbol_path=symbol_path,
                    imports=imports,
                    path=path,
                    repo=repo,
                    language=language,
                    caller_point_id=str(p.id),
                    collection=collection,
                    qdrant_client=client,
                )
                # Enrich edges with symbol metadata
                for edge in import_edges:
                    edge.caller_signature = symbol_signature
                    edge.caller_docstring = symbol_docstring
                edges.extend(import_edges)
            else:
                # Fallback: Create edges directly without resolution
                for callee in calls:
                    if callee and isinstance(callee, str):
                        edge_id = f"{symbol_path}:calls:{callee}"
                        edges.append(GraphEdge(
                            id=edge_id,
                            edge_type="calls",
                            caller_symbol=symbol_path,
                            callee_symbol=callee,
                            caller_path=path,
                            callee_path="",  # Unknown - will be resolved if found
                            repo=repo,
                            language=language,
                            start_line=start_line,
                            end_line=end_line,
                            caller_signature=symbol_signature,
                            caller_docstring=symbol_docstring,
                        ))

                for imported in imports:
                    if imported and isinstance(imported, str):
                        edge_id = f"{symbol_path}:imports:{imported}"
                        edges.append(GraphEdge(
                            id=edge_id,
                            edge_type="imports",
                            caller_symbol=symbol_path,
                            callee_symbol=imported,
                            caller_path=path,
                            callee_path="",
                            repo=repo,
                            language=language,
                            start_line=start_line,
                            end_line=end_line,
                            caller_signature=symbol_signature,
                            caller_docstring=symbol_docstring,
                        ))

            total_points += 1

            # Batch upsert
            if len(edges) >= 500:
                count = backend.upsert_edges(store, edges)
                total_edges += count
                print(f"  Processed {total_points} points, upserted {total_edges} edges...", end="\r")
                edges = []

        if limit and total_edges >= limit:
            break
        if offset is None:
            break

    # Final batch
    if edges:
        count = backend.upsert_edges(store, edges)
        total_edges += count

    print(f"\n✓ Backfilled {total_edges} edges from {total_points} points to Neo4j")

    # Post-process: resolve unresolved edges to real definitions
    print("  Resolving unresolved edges to real definitions...")
    resolved = backend.resolve_unresolved_edges(collection)
    if resolved > 0:
        print(f"  ✓ Resolved {resolved} edges")
    else:
        print("  (no edges could be resolved)")

    return 0


def cmd_index(args):
    """Index a directory directly to Neo4j."""
    from .backend import Neo4jGraphBackend

    try:
        from scripts.ast_analyzer import get_ast_analyzer
        from scripts.graph_backends.ingest_adapter import (
            extract_call_edges,
            extract_import_edges,
        )
    except ImportError:
        print("✗ Requires scripts/ast_analyzer.py - run from repo root")
        return 1

    path = os.path.abspath(args.path)
    repo = args.repo or os.path.basename(path)
    collection = args.collection or os.environ.get("COLLECTION_NAME") or repo

    print(f"Indexing {path} to Neo4j (repo={repo}, collection={collection})...")

    backend = Neo4jGraphBackend()
    store = backend.ensure_graph_store(collection)
    analyzer = get_ast_analyzer()

    # Complete extension -> language mapping (16+ languages)
    CODE_EXTS = {
        # Core languages
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".hpp": "cpp",
        ".cs": "csharp",
        ".csx": "csharp",
        ".kt": "kotlin",
        ".swift": "swift",
        ".scala": "scala",
        # Shell/scripting
        ".sh": "shell",
        ".ps1": "powershell",
        ".psm1": "powershell",
        ".psd1": "powershell",
        ".pl": "perl",
        ".lua": "lua",
        # Web
        ".vue": "vue",
        ".svelte": "svelte",
        ".cshtml": "razor",
        ".razor": "razor",
        # Additional languages
        ".elm": "elm",
        ".dart": "dart",
        ".r": "r",
        ".R": "r",
        ".m": "matlab",
        ".cljs": "clojure",
        ".clj": "clojure",
        ".hs": "haskell",
        ".ml": "ocaml",
        ".zig": "zig",
        ".nim": "nim",
        ".v": "verilog",
        ".sv": "verilog",
        ".ex": "elixir",
        ".exs": "elixir",
        ".erl": "erlang",
        ".groovy": "groovy",
        ".gradle": "groovy",
    }

    # Walk directory and analyze files
    extensions = set(CODE_EXTS.keys())
    total_edges = 0
    total_files = 0

    # Directories to skip during indexing
    skip_dirs = {"node_modules", "vendor", "__pycache__", "dev-workspace", ".git", "venv", ".venv", "dist", "build", "target", "out", ".tox", ".mypy_cache", ".pytest_cache"}

    for root, dirs, files in os.walk(path):
        # Skip hidden/vendor/dev dirs
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip_dirs]

        for fname in files:
            ext = os.path.splitext(fname)[1]
            if ext not in extensions:
                continue

            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, path)

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    code = f.read()

                # Detect language from extension
                lang = CODE_EXTS.get(ext, "python")
                
                # Analyze
                analysis = analyzer.analyze_file(fpath, lang, content=code)
                symbols = analysis.get("symbols", []) or []
                calls = analysis.get("calls", []) or []
                imports = analysis.get("imports", []) or []

                symbol_meta_by_path = {}
                symbol_meta_by_name = {}
                # Build symbol_paths for callee resolution: map symbol name -> file path
                symbol_paths = {}
                for sym in symbols:
                    name = str(getattr(sym, "name", "") or "")
                    if not name:
                        continue
                    path_key = str(getattr(sym, "path", "") or "") or name
                    symbol_meta_by_path[path_key] = sym
                    symbol_meta_by_name.setdefault(name, sym)
                    # Map symbol name to the file where it's defined
                    symbol_paths[name] = fpath
                    if path_key != name:
                        symbol_paths[path_key] = fpath

                symbol_calls = {}
                for call in calls:
                    caller = str(getattr(call, "caller", "") or "")
                    callee = str(getattr(call, "callee", "") or "")
                    if not caller or not callee:
                        continue
                    symbol_calls.setdefault(caller, [])
                    symbol_calls[caller].append(callee)

                def _dedupe(items):
                    seen = set()
                    out = []
                    for item in items:
                        if not item or item in seen:
                            continue
                        seen.add(item)
                        out.append(item)
                    return out

                for caller, callees in list(symbol_calls.items()):
                    symbol_calls[caller] = _dedupe(callees)

                # Build import_paths for callee resolution: map imported name -> module path
                import_paths = {}
                for imp in imports:
                    module = str(getattr(imp, "module", "") or "")
                    names = getattr(imp, "names", []) or []
                    alias = getattr(imp, "alias", None)
                    if module:
                        # "import os" -> os maps to <module>/os
                        import_paths[module] = f"<module>/{module}"
                        if alias:
                            import_paths[str(alias)] = f"<module>/{module}"
                        # "from os import path" -> path maps to <module>/os.path
                        for name in names:
                            name_str = str(name) if name else ""
                            if name_str:
                                import_paths[name_str] = f"<module>/{module}.{name_str}"

                import_modules = _dedupe([
                    str(getattr(imp, "module", "") or "")
                    for imp in imports
                    if getattr(imp, "module", None)
                ])
                call_names = _dedupe([
                    str(getattr(call, "callee", "") or "")
                    for call in calls
                    if getattr(call, "callee", None)
                ])

                edges = []

                # Extract call edges (symbol-level preferred, file-level fallback)
                if symbol_calls:
                    for caller, callees in symbol_calls.items():
                        sym_info = symbol_meta_by_path.get(caller) or symbol_meta_by_name.get(caller)
                        start_line = None
                        end_line = None
                        if sym_info is not None:
                            try:
                                start_line = int(getattr(sym_info, "start_line", 0) or 0) or None
                                end_line = int(getattr(sym_info, "end_line", 0) or 0) or None
                            except Exception:
                                start_line = None
                                end_line = None
                        edges.extend(extract_call_edges(
                            symbol_path=caller,
                            calls=callees,
                            path=fpath,
                            repo=repo,
                            start_line=start_line,
                            end_line=end_line,
                            language=lang,
                            symbol_paths=symbol_paths,
                            import_paths=import_paths,
                        ))
                    if import_modules:
                        edges.extend(extract_import_edges(
                            symbol_path=fpath,
                            imports=import_modules,
                            path=fpath,
                            repo=repo,
                            language=lang,
                        ))
                else:
                    if call_names:
                        edges.extend(extract_call_edges(
                            symbol_path=fpath,
                            calls=call_names,
                            path=fpath,
                            repo=repo,
                            language=lang,
                            symbol_paths=symbol_paths,
                            import_paths=import_paths,
                        ))
                    if import_modules:
                        edges.extend(extract_import_edges(
                            symbol_path=fpath,
                            imports=import_modules,
                            path=fpath,
                            repo=repo,
                            language=lang,
                        ))
                
                if edges:
                    backend.upsert_edges(store, edges)
                    total_edges += len(edges)
                    total_files += 1
                    print(f"  {rel_path}: {len(edges)} edges", end="\r")
                    
            except Exception as e:
                print(f"  ✗ {rel_path}: {e}")
    
    print(f"\n✓ Indexed {total_files} files, {total_edges} edges to Neo4j")
    return 0


def cmd_query(args):
    """Query the Neo4j graph for callers/callees/imports."""
    from .backend import Neo4jGraphBackend

    backend = Neo4jGraphBackend()

    symbol = args.symbol
    query_type = args.type
    limit = args.limit
    repo = args.repo
    collection = args.collection or os.environ.get("COLLECTION_NAME") or "default"
    graph_store = backend.ensure_graph_store(collection) or collection

    try:
        if query_type == "callers":
            records = backend.get_callers(graph_store, symbol, repo=repo, limit=limit)
            print(f"Callers of '{symbol}' ({len(records)} found):")
            for rec in records:
                path = rec.get("caller_path") or ""
                print(f"  {rec.get('caller_symbol', '')} ({path})")

        elif query_type == "callees":
            records = backend.get_callees(graph_store, symbol, repo=repo, limit=limit)
            print(f"Callees of '{symbol}' ({len(records)} found):")
            for rec in records:
                print(f"  {rec.get('callee_symbol', '')}")

        elif query_type == "imports":
            records = backend.get_importers(graph_store, symbol, repo=repo, limit=limit)
            print(f"Importers of '{symbol}' ({len(records)} found):")
            for rec in records:
                path = rec.get("caller_path") or ""
                print(f"  {rec.get('caller_symbol', '')} ({path})")

        else:
            print(f"Unknown query type: {query_type}")
            return 1

    except Exception as e:
        print(f"Query error: {e}")
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(description="Neo4j graph indexing CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    subparsers.add_parser("status", help="Check Neo4j connection and stats")

    # backfill
    p = subparsers.add_parser("backfill", help="Backfill from Qdrant to Neo4j")
    p.add_argument("--collection", "-c", required=True, help="Main collection name")
    p.add_argument("--limit", "-l", type=int, default=0, help="Max edges to backfill")
    p.add_argument("--clean", action="store_true", help="Delete existing Neo4j data for this collection before backfill")

    # index
    p = subparsers.add_parser("index", help="Index directory to Neo4j")
    p.add_argument("--path", "-p", required=True, help="Directory to index")
    p.add_argument("--repo", "-r", help="Repository name (default: dirname)")
    p.add_argument("--collection", "-c", help="Collection name (default: $COLLECTION_NAME or repo)")

    # query
    p = subparsers.add_parser("query", help="Query the graph")
    p.add_argument("--symbol", "-s", required=True, help="Symbol to query")
    p.add_argument("--type", "-t", choices=["callers", "callees", "imports"], default="callers", help="Query type")
    p.add_argument("--limit", "-l", type=int, default=20, help="Max results")
    p.add_argument("--repo", "-r", help="Repository name filter")
    p.add_argument("--collection", "-c", help="Collection name (default: $COLLECTION_NAME)")

    args = parser.parse_args()

    if args.command == "status":
        sys.exit(cmd_status(args))
    elif args.command == "backfill":
        sys.exit(cmd_backfill(args))
    elif args.command == "index":
        sys.exit(cmd_index(args))
    elif args.command == "query":
        sys.exit(cmd_query(args))


if __name__ == "__main__":
    main()
