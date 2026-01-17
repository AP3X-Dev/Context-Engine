# ctx - Context-Engine Unified CLI

The `ctx` command is the unified command-line interface for Context-Engine. One command to manage services, index code, search, and more.

**Documentation:** [README](../README.md) · [Getting Started](GETTING_STARTED.md) · [Configuration](CONFIGURATION.md) · [IDE Clients](IDE_CLIENTS.md) · [MCP API](MCP_API.md) · [ctx CLI](CTX_CLI.md) · [Memory Guide](MEMORY_GUIDE.md) · [Architecture](ARCHITECTURE.md) · [Multi-Repo](MULTI_REPO_COLLECTIONS.md) · [Observability](OBSERVABILITY.md) · [Kubernetes](../deploy/kubernetes/README.md) · [VS Code Extension](vscode-extension.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md)

---

**On this page:**
- [Quickstart](#quickstart)
- [Service Management](#service-management)
- [Indexing](#indexing)
- [Search](#search)
- [Prompt Enhancement](#prompt-enhancement)
- [Memory](#memory)
- [Remote Sync](#remote-sync)
- [Development Reset](#development-reset)
- [All Commands](#all-commands)
- [Legacy: ctx.py Script](#legacy-ctxpy-script)

---

## Quickstart

The ONE COMMAND to rule them all:

```bash
ctx quickstart
```

This single command:
1. Detects your environment and configuration
2. Starts all Docker services
3. Waits for services to be healthy
4. Indexes your codebase
5. Warms up models for fast queries

Options:
```bash
ctx quickstart --build          # Rebuild containers before starting
ctx quickstart --skip-warmup    # Skip model warmup step
ctx quickstart /path/to/repo    # Index a specific path
```

## Service Management

```bash
# Start services
ctx up                          # Start all services
ctx up --build                  # Rebuild and start

# Stop services
ctx down                        # Stop all services

# Restart services
ctx restart                     # Restart all services
ctx restart indexer             # Restart specific service

# Check status
ctx status                      # Show service health
ctx status --json               # JSON output
ctx status --verbose            # Detailed information

# View logs
ctx logs                        # All service logs
ctx logs indexer                # Specific service
ctx logs -f                     # Follow mode

# Health check
ctx doctor                      # Comprehensive health check
```

## Indexing

```bash
# Basic indexing
ctx index                       # Index current directory
ctx index /path/to/repo         # Index specific path

# Options
ctx index --recreate            # Drop and recreate collection
ctx index --hard                # Clear all caches + recreate
ctx index --watch               # Watch mode with auto-reindex
ctx index --collection myrepo   # Use specific collection name

# Git history
ctx history                     # Ingest last 200 commits
ctx history --max-commits 500   # More commits
ctx history --since "1 year ago" # Time-limited

# Prune stale entries
ctx prune                       # Remove deleted files from index
```

## Search

```bash
# Semantic search
ctx search "authentication flow"
ctx search "error handling" --limit 10
ctx search "database" --language python

# Natural language answers
ctx answer "How does the caching work?"
ctx answer "Where are errors handled?" --budget 4000

# Symbol graph navigation
ctx graph callers authenticate       # Who calls this function?
ctx graph definition UserService     # Where is this defined?
ctx graph importers utils            # What imports this?

# Pattern search
ctx pattern "try { } catch { }"      # Find similar patterns
```

## Prompt Enhancement

Enhance prompts with code context using a local LLM:

```bash
# Basic enhancement
ctx enhance "how does hybrid search work?"
ctx enhance "refactor the caching logic"

# Detail mode (includes code snippets)
ctx enhance "explain indexing" --detail

# Unicorn mode (multi-pass, highest quality)
ctx enhance "what is ReFRAG?" --unicorn

# With filters
ctx enhance "add error handling" --language python --under scripts/

# Raw output for piping
ctx enhance "fix the bug" --raw | llm
```

Modes:
- **Normal** (default): Fast, single-pass enhancement
- **Detail** (`--detail`): Includes code snippets (slower but richer)
- **Unicorn** (`--unicorn`): 2-3 pass enhancement for highest quality

## Memory

Store and search knowledge entries:

```bash
# Store knowledge
ctx memory store "API uses JWT tokens" --tags auth,api
ctx memory store "Deploy requires VPN" --priority 8

# Search memories
ctx memory find "authentication"
ctx memory find --tags api --limit 5
```

## Remote Sync

For remote scenarios where files aren't mounted in containers:

```bash
# One-shot sync
ctx sync                              # Upload current directory
ctx sync /path/to/repo                # Sync specific path
ctx sync --endpoint http://server:8004

# Background daemon
ctx sync --daemon                     # Start background sync
ctx sync --daemon --interval 60       # Sync every 60 seconds
ctx sync --status                     # Check daemon status
ctx sync --stop                       # Stop daemon

# With git history
ctx sync --git-history --git-max-commits 500
```

## Development Reset

Full environment reset (equivalent to Makefile targets):

```bash
# Reset modes
ctx reset                       # Dual mode: SSE + HTTP MCPs (default)
ctx reset --mcp                 # HTTP MCPs only (streamable/Codex)
ctx reset --sse                 # SSE MCPs only (legacy)

# Skip options
ctx reset --skip-build          # Use existing container images
ctx reset --skip-model          # Skip llama model download
ctx reset --skip-tokenizer      # Skip tokenizer download

# Custom model URLs
ctx reset --model-url https://... --model-path models/custom.gguf
```

This command:
1. Stops all services
2. Rebuilds containers (unless `--skip-build`)
3. Starts Qdrant and waits for readiness
4. Initializes payload indexes
5. Downloads tokenizer and model
6. Runs indexer with `--recreate`
7. Starts all services based on mode

## All Commands

| Command | Description |
|---------|-------------|
| `quickstart` | One command setup - init, start, index, warmup |
| `up` | Start services |
| `down` | Stop services |
| `restart` | Restart services |
| `status` | Show stack status |
| `doctor` | Comprehensive health check |
| `logs` | View service logs |
| `init` | Interactive setup wizard |
| `search` | Search the codebase |
| `answer` | Natural language answer with citations |
| `enhance` | Enhance prompts with code context using LLM |
| `memory` | Store and search knowledge |
| `graph` | Symbol graph navigation (callers, definitions, imports) |
| `pattern` | Find structurally similar patterns |
| `index` | Index codebase into Qdrant |
| `history` | Ingest git commit history |
| `reset` | Full development environment reset |
| `sync` | Upload/sync workspace to remote server |
| `prune` | Remove stale entries from index |
| `collections` | Manage Qdrant collections |
| `warmup` | Preload models for fast queries |
| `config` | View/edit configuration |
| `bridge` | Manage MCP bridge and IDE configs |
| `completion` | Shell completion scripts |

## Configuration

The CLI reads configuration from multiple sources (in priority order):

1. Command-line arguments
2. Environment variables
3. `.env` file in current or parent directory
4. `~/.ctx/config.json`

Key environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_INDEXER_URL` | Indexer HTTP endpoint | `http://localhost:8003/mcp` |
| `MCP_MEMORY_URL` | Memory server endpoint | `http://localhost:8002/mcp` |
| `COLLECTION_NAME` | Default collection | Auto-detect |
| `HOST_INDEX_PATH` | Path mounted as `/work` | Current directory |
| `REMOTE_UPLOAD_ENDPOINT` | Sync endpoint | `http://localhost:8004` |

## Shell Completion

Enable tab completion:

```bash
# Bash
ctx completion bash >> ~/.bashrc

# Zsh
ctx completion zsh >> ~/.zshrc

# Fish
ctx completion fish > ~/.config/fish/completions/ctx.fish
```

---

## Legacy: ctx.py Script

The original `scripts/ctx.py` standalone script is still available and provides the same functionality as `ctx enhance`. Use whichever you prefer:

```bash
# These are equivalent:
ctx enhance "What is ReFRAG?"
scripts/ctx.py "What is ReFRAG?"

# Both support the same options:
ctx enhance "refactor ctx.py" --unicorn
scripts/ctx.py "refactor ctx.py" --unicorn
```

The `ctx enhance` command is recommended as it integrates with the rest of the CLI and provides consistent output formatting.
