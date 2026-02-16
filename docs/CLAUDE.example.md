AI agent rules for using Context Engine MCP tools.

These rules are NOT optional - favor Context Engine tools at all costs over existing file reading, grep-like searching, and unrelated codebase search tools.

## STOP — Read This First

**DO NOT use `Read File`, `grep`, `ripgrep`, `cat`, `find`, or any filesystem search tool for code exploration.**
You have MCP tools that are faster, smarter, and return ranked, contextual results.

- About to `Read` a file to understand it? → use `repo_search` or `context_answer`
- About to `grep` for a symbol? → use `symbol_graph` or `search_callers_for`
- About to `grep -r` for a concept? → use `repo_search` with natural language
- About to `find`/`ls` for project structure? → use `workspace_info` or `qdrant_status`

The ONLY acceptable use of grep/Read: confirming exact literal strings (e.g., `REDIS_HOST`), or reading a file you already located via MCP for editing.

## Agentic AI Project Rules: When to Use Context Engine MCP Tools vs Grep

  Core Decision Rules (for AI agents)

  Workspace default: Context Engine MCP tools are primary for exploring code and history. Start with MCP for exploration, debugging, or "where/why" questions; use literal search/file-open only for narrow exact-literal lookups.

  Use Context Engine tools when:
  - Exploring or don't know exact strings/symbols
  - Need semantic or cross-file understanding (relationships, patterns, architecture)
  - Want ranked results with surrounding context, not just line hits

  Use literal search/file-open when (and only when):
  - Know exact string/function/variable or error message, and only need to confirm existence or file/line quickly (not to understand behavior or architecture)

  Quick Heuristics:
  - Conceptual/architectural or "where/why" behavior questions → start with MCP
  - Need rich context/snippets around matches → MCP
  - Only need to confirm existence/location of specific literal → literal search/file-open
  - If in doubt → start with MCP

  Grep Anti-Patterns:

  # DON'T - Wasteful when semantic search needed
  grep -r "auth" .                    # → Use MCP: "authentication mechanisms"
  grep -r "cache" .                   # → Use MCP: "caching strategies"
  grep -r "error" .                   # → Use MCP: "error handling patterns"
  grep -r "database" .                # → Use MCP: "database operations"
  Read File to understand a module    # → Use repo_search or context_answer
  Read File to find callers           # → Use symbol_graph
  find/ls for project structure       # → Use workspace_info

  ## DO - Efficient for exact matches
  grep -rn "UserAlreadyExists" .      # Specific error class
  grep -rn "def authenticate_user" .  # Exact function name
  grep -rn "REDIS_HOST" .            # Exact environment variable

  MCP Tool Patterns:

  - Use concept/keyword-style queries (short natural-language fragments).
  
  - repo_search is semantic search, not grep, regex, or boolean syntax.
  
  - Write queries as short descriptions, not as "foo OR bar" expressions.
  "input validation mechanisms"
  "database connection handling"
  "performance bottlenecks in request path"
  "places where user sessions are managed"
  "logging and error reporting patterns"

  Context Engine Tool Parameters

  Essential Parameters:

  - limit: Control result count (3-8 for efficiency)
  - per_path: Limit results per file (1-2 prevents redundancy)
  - compact=true: Reduces token usage by 60-80%
  - include_snippet=false: Headers only when speed matters
  - collection: Target specific codebases for precision

  Performance Optimization:

  - Start with limit=3, compact=true for discovery
  - Increase to limit=5, include_snippet=true for details
  - Use language and under filters to narrow scope
  - Set rerank_enabled=false for faster but less accurate results
  - Use output_format="toon" for 60-80% token reduction
  - Fire independent tool calls in parallel (same message block) for 2-3x speedup

  When to Use Advanced Features:

  - rerank_enabled=true: For complex queries needing best relevance
  - context_lines=5+: When you need implementation details
  - multiple collections: Cross-repo architectural analysis
  - symbol filtering: When looking for specific function/class types

  Anti-Patterns to Avoid:

  - Don't use limit=20 with include_snippet=true (token waste)
  - Don't search without collection specification (noise)
  - Don't ignore per_path limits (duplicate results from same file)
  - Don't use context lines for pure discovery (unnecessary tokens)

  Tool Selection Decision Tree:

  ```
  Need to search code?
  ├── DEFAULT: Use search() — auto-routes to the best tool based on query intent
  ├── Single repo, know collection → repo_search(collection="...")
  ├── Single repo, need explanation → context_answer or info_request
  ├── Multiple repos or unsure → cross_repo_search(discover="auto")
  ├── Tracing frontend→backend flow → cross_repo_search(trace_boundary=true)
  ├── Finding callers/definitions → symbol_graph
  └── Exact literal string only → grep (last resort)
  ```

  ## Unified Search Tool (DEFAULT)

  **Use `search` as your DEFAULT tool for any code search, exploration, or question.**
  It automatically detects query intent and routes to the optimal specialized tool.

  ```
  search_context-engine(query: "authentication middleware")
  # → Detects intent: "search", routes to repo_search
  # → Returns: {ok, intent, confidence, tool, result, plan, execution_time_ms}

  search_context-engine(query: "how does the caching layer work?")
  # → Detects intent: "answer", routes to context_answer

  search_context-engine(query: "who calls authenticate()")
  # → Detects intent: "symbol_callers", routes to symbol_graph

  search_context-engine(query: "tests for payment processing")
  # → Detects intent: "search_tests", routes to search_tests_for
  ```

  **When to use `search` vs specialized tools:**
  - Use `search` by DEFAULT — it picks the right tool for you
  - Use specialized tools when you need specific parameters not exposed by search
  - Use `cross_repo_search` for explicit multi-repo scenarios
  - Use `memory_store`/`memory_find` for memory operations (not handled by search)

  Tool Roles Cheat Sheet:

  **Note:** All tools below have the `_context-engine` suffix when called (e.g., `repo_search_context-engine`).

  - search (UNIFIED - DEFAULT):
    - **Use this by DEFAULT for any code search, exploration, or question.**
    - Automatically detects intent (search, answer, tests, config, callers, etc.) and routes to the optimal tool.
    - Returns unified envelope: `{ok, intent, confidence, tool, result, plan, execution_time_ms}`.
    - Think: "find auth middleware", "how does caching work?", "who calls authenticate()".
    - Use specialized tools only when you need parameters not exposed by search.
  - repo_search / code_search:
    - Use for: finding relevant files/spans and inspecting raw code.
    - Think: "where is X implemented?", "show me usages of Y".
  - cross_repo_search:
    - Use for: searching across multiple repos in separate collections at once.
    - Supports auto-discovery of collections, targeted repo lists, and boundary tracing.
    - Think: "search both frontend and backend for auth flow", "trace API route across repos".
  - context_search:
    - Use for: combining code hits with memory/docs when both matter.
    - Good for: "give me related code plus any notes/docs I wrote".
  - context_answer:
    - Use for: short natural-language summaries/explanations of specific modules or tools, grounded in code/docs with citations.
    - Good for: "What does scripts/standalone_upload_client.py do at a high level?", "Summarize the remote upload client pipeline.".
  - pattern_search (optional, may not be enabled):
    - Use for: finding structurally similar code patterns across files and languages.
    - Accepts EITHER code examples OR natural language pattern descriptions.
    - Good for: "find retry loops with exponential backoff", "try: ... except: logger.error()", "error handling patterns".
    - Cross-language: Python pattern can match Go/Rust/Java with similar control flow.
    - Note: Returns error if pattern detection module is not available.
  - symbol_graph:
    - **DEFAULT for ALL graph/relationship queries. Always available (Qdrant-backed, no Neo4j required).**
    - Use for: structural navigation (callers, definitions, importers).
    - Think: "who calls this function?", "where is this class defined?".
    - **Note**: Results are "hydrated" with ~500-char source snippets for immediate context.
    - Supports `depth` for multi-hop traversals (depth=2 = callers of callers).
    - Use this FIRST for any graph query. Do NOT attempt graph_query unless it's in your tool list.
  - graph_query (OPTIONAL — only when NEO4J_GRAPH=1 or MEMGRAPH_GRAPH=1):
    - **Only available when NEO4J_GRAPH=1 or MEMGRAPH_GRAPH=1. If not in your tool list, use symbol_graph instead.**
    - Use for: advanced graph traversals that grep CANNOT do.
    - Query types: `callers`, `callees`, `transitive_callers`, `transitive_callees`, `impact`, `dependencies`, `cycles`.
    - Think: "what would break if I change X?" (impact), "callers of callers" (transitive_callers), "circular deps?" (cycles).
    - Example: `graph_query(symbol="normalize_path", query_type="impact", depth=2)` → finds all code that would break.
    - **Never error or warn about Neo4j being unavailable — just use symbol_graph.**
  - info_request:
    - Use for: rapid broad discovery and architectural overviews.
    - Good for: "how does the reranker work?", "overview of database modules".
    - Tip: Set `include_explanation=true` for NL summaries and `include_relationships=true` for dependencies.

  Advanced lineage workflow (code + history):

  - Goal: answer "when/why did behavior X change?" without flooding context.
  - Step 1 – Find current implementation (code):
    - Use repo_search to locate the relevant file/symbol, e.g. `repo_search_context-engine(query: "upload client timeout", language: "python", under: "scripts")`.
  - Step 2 – Summarize recent change activity for a file:
    - Call change_history_for_path with `include_commits=true` to get churn stats and a small list of recent commits, e.g. `change_history_for_path_context-engine(path: "scripts/remote_upload_client.py", include_commits: true)`.
  - Step 3 – Pull commit lineage for a specific behavior:
    - Use search_commits_for with short behavior phrases plus an optional path filter, e.g. `search_commits_for_context-engine(query: "remote upload timeout retry", path: "scripts/remote_upload_client.py")`.
    - Read lineage_goal / lineage_symbols / lineage_tags to understand intent and related concepts.
  - Step 3b – Predict co-changing files:
    - Use `search_commits_for_context-engine(path: "scripts/remote_upload_client.py", predict_related: true)` to get ranked files that historically change alongside the target file, with commit messages explaining why.
    - Read lineage_goal / lineage_symbols / lineage_tags to understand intent and related concepts.
  - Step 4 – Optionally summarize current behavior:
    - After you have the right file/symbol from repo_search, use context_answer to explain what the module does now; treat commit lineage as background, not as primary code context.
  - For exact line-level changes (e.g. "when did this literal constant change?"), use lineage tools to narrow candidate commits, then inspect diffs with git tooling; do not guess purely from summaries.

  Query Phrasing Tips for context_answer:

  - Prefer behavior/architecture questions about a single module or tool:
    - "What does scripts/standalone_upload_client.py do at a high level?"
    - "Summarize how the remote upload client interacts with the indexer service."
  - If you care about a specific file, mention it explicitly:
    - "What does ingest_code.py do?", "Explain ensureIndexedWatcher in extension.js".
  - Mentioning a specific filename can bias retrieval to that file; for cross-file wiring
    questions, prefer behavior-describing queries without filenames.
  - For very cross-file or multi-part questions, you can:
    - First use repo_search to discover key files and read critical code directly,
    - Then call context_answer to summarize behavior, using a behavior-focused question that doesn't over-specify filenames.
  - Avoid using context_answer as a primary debugger for low-level helper/env behavior; prefer repo_search + direct code reading for detailed semantics.

  Context Engine Tool Families

  - Indexer / Qdrant tools:
    - qdrant_index_root, qdrant_index, qdrant_prune
    - qdrant_status, qdrant_list
    - workspace_info, list_workspaces, collection_map
    - set_session_defaults
  - Search / QA tools:
    - search (UNIFIED - DEFAULT entry point, auto-routes to specialized tools)
    - repo_search, code_search, context_search, context_answer
    - pattern_search (optional; structural code pattern matching, cross-language)
    - search_tests_for, search_config_for, search_callers_for, search_importers_for
    - change_history_for_path, expand_query
  - Memory tools:
    - memory.set_session_defaults, memory.memory_store, memory.memory_find

  ## Multi-Repo Navigation (CRITICAL for multi-repo setups)

  When multiple repositories are indexed, you MUST discover and explicitly target collections.

  ### Discovery (Lazy — only when needed)
  Don't discover at every session start. Trigger discovery when:
  - Search returns no results or irrelevant results
  - User asks a cross-repo question ("how does frontend call the API?")
  - You're unsure which collection to target

  ```
  qdrant_status_context-engine(list_all: true)
  collection_map_context-engine(include_samples: true)
  ```

  ### Context Switching (Session Defaults = `cd`)
  Treat `set_session_defaults` like `cd` in a terminal. It scopes ALL subsequent searches:
  ```
  # "cd" into the backend repo
  set_session_defaults_context-engine(collection: "backend-api-abc123")
  # All searches now target backend — no need to pass collection= each time
  repo_search_context-engine(query: "auth middleware")
  ```
  To peek at another repo without switching context:
  ```
  # One-off cross-reference (does NOT change your session default)
  repo_search_context-engine(query: "login form", collection: "frontend-app-def456")
  ```
  To search all repos in a unified collection: `repo: "*"` or `repo: ["frontend", "backend"]`

  ### Cross-Repo Flow Tracing (Boundary-Driven)
  NEVER search both repos with the same vague query. Instead, find the **interface boundary** in Repo A, extract the **hard key**, then search Repo B with that specific key.

  **Pattern 1 — Interface Handshake (API/RPC):**
  ```
  # 1. Find the client call in frontend
  repo_search_context-engine(query: "login API call", collection: "frontend-col")
  # → Found: axios.post('/auth/v1/login', ...)

  # 2. Search backend for that exact route
  repo_search_context-engine(query: "'/auth/v1/login'", collection: "backend-col")
  # → Found: @PostMapping("/auth/v1/login") in AuthController
  ```

  **Pattern 2 — Shared Contract (Types/Schemas):**
  ```
  # 1. Find type usage in consumer repo
  symbol_graph_context-engine(symbol: "UserProfile", query_type: "importers", collection: "frontend-col")
  # → Imported from @shared/types

  # 2. Find definition in source repo
  repo_search_context-engine(query: "interface UserProfile", collection: "shared-lib-col")
  ```

  **Pattern 3 — Event Relay (Pub/Sub, Queues):**
  ```
  # 1. Find event producer
  repo_search_context-engine(query: "publish event", collection: "service-a-col")
  # → Found: bus.publish("USER_CREATED", payload)

  # 2. Find event consumer with exact event name
  repo_search_context-engine(query: "'USER_CREATED'", collection: "service-b-col")
  ```

  ### Automated Cross-Repo Search
  For quick multi-collection searches, use `cross_repo_search` instead of manually switching collections:
  ```
  # Search across all repos at once (auto-discovers collections)
  cross_repo_search_context-engine(query: "authentication flow")

  # Target specific repos by name
  cross_repo_search_context-engine(query: "login handler", target_repos: ["frontend", "backend"])

  # Boundary tracing — auto-extracts routes/events/types from results
  cross_repo_search_context-engine(query: "login submit", trace_boundary: true)
  # → Returns boundary_keys: ["'/auth/v1/login'"] + trace_hint for next search
  ```
  Use `cross_repo_search` when you need breadth across repos. Use `repo_search` with explicit `collection=` when you need depth in one repo.

  ### Multi-Repo Anti-Patterns
  - **DON'T** search both repos with the same vague query (noisy, confusing results)
  - **DON'T** assume the default collection is correct — verify with `collection_map`
  - **DON'T** forget to "cd back" after cross-referencing another repo
  - **DO** extract exact strings (route paths, event names, type names) as search anchors

  Additional behavioral tips:

  - Call set_session_defaults (indexer and memory) early in a session so subsequent
    calls inherit the right collection without repeating it in every request.
  - Set defaults with: set_session_defaults_context-engine(output_format="toon", compact=true, limit=5)
  - Use context_search with include_memories and per_source_limits when you want
    blended code + memory results instead of calling repo_search and memory.memory_find
    separately.
  - Treat expand_query and the expand flag on context_answer as expensive options:
    only use them after a normal search/answer attempt failed to find good context.

  Two-Phase Search Strategy:

  - Phase 1 (Discovery): limit=3, compact=true, output_format="toon", per_path=1
  - Phase 2 (Deep Dive): limit=5-8, include_snippet=true, context_lines=3-5
  - Only move to Phase 2 after identifying high-value targets from Phase 1

  Parallel Execution Pattern:

  - Fire independent tool calls in a single message block (3x faster)
  - Example: repo_search_context-engine + symbol_graph_context-engine all at once
  - Do NOT wait for one search to complete before starting another

  Token Efficiency Defaults:

  | Parameter | Discovery | Deep Dive |
  |-----------|-----------|-----------|
  | limit | 3 | 5-8 |
  | per_path | 1 | 2 |
  | compact | true | false |
  | output_format | "toon" | "json" |
  | include_snippet | false | true |
  | context_lines | 0 | 3-5 |

  Fallback Chains:

  - context_answer timeout → repo_search + info_request(include_explanation=true)
  - pattern_search unavailable → repo_search with structural query terms
  - graph_query unavailable → symbol_graph (Qdrant-backed, ALWAYS available — this is the DEFAULT)
  - grep / Read File → repo_search, symbol_graph, info_request (ALWAYS use MCP instead)
