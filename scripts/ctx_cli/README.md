# ctx CLI

Unified command-line interface for Context-Engine.

## Installation

```bash
pip install -e .
```

## Quick Start

Get up and running with a single command:

```bash
ctx quickstart
```

This will:
1. Configure your environment
2. Start all services
3. Index your codebase
4. Warm up embedding models

### Quickstart Options

| Flag | Description |
|------|-------------|
| `--no-llama` | Skip the local LLM container (for users without GPU or using cloud APIs like OpenAI/GLM) |
| `--no-index` | Skip initial codebase indexing |
| `--no-warmup` | Skip model warmup step |
| `--build` | Rebuild Docker containers before starting |
| `--recreate` | Recreate Qdrant collection (drops existing data) |
| `--import-repos` | Copy external repos into dev-workspace for indexing |

**Example: Lightweight setup without local LLM:**
```bash
ctx quickstart --no-llama
```

This is ideal when:
- You don't have a GPU or sufficient RAM for local LLM inference
- You're using cloud LLM APIs (OpenAI, GLM, MiniMax) configured in `.env`
- You want faster startup and lower resource usage

## Commands

### Getting Started

| Command | Description |
|---------|-------------|
| `ctx quickstart` | One command to rule them all - full setup |
| `ctx init [--full]` | Interactive setup wizard |
| `ctx doctor` | Diagnose issues with actionable fixes |

### Service Management

| Command | Description |
|---------|-------------|
| `ctx up [--build] [--wait N]` | Start services |
| `ctx down [--volumes]` | Stop services |
| `ctx restart [--build]` | Restart services |
| `ctx status [--json] [--verbose]` | Show stack health, model state, cache stats |
| `ctx logs [SERVICE] [-f] [--tail N]` | View service logs |
| `ctx warmup [--status]` | Preload models for fast queries |

### Search & Retrieval

| Command | Description |
|---------|-------------|
| `ctx search <query> [options]` | Semantic code search |
| `ctx answer <query> [options]` | LLM-generated answers with citations |
| `ctx memory store <info> [--tags]` | Store knowledge in memory |
| `ctx memory find <query> [--kind]` | Search stored memories |
| `ctx graph callers <symbol>` | Find who calls a symbol |
| `ctx graph definition <symbol>` | Find where symbol is defined |
| `ctx graph importers <symbol>` | Find what imports a module |
| `ctx graph callees <symbol>` | Find what a symbol calls |
| `ctx pattern <query> [--mode]` | Find structurally similar code |

### Indexing

| Command | Description |
|---------|-------------|
| `ctx index [path] [--watch]` | Index codebase (local/mounted) |
| `ctx sync [path] [--watch]` | Upload/sync to remote server |
| `ctx prune [--collection]` | Remove stale entries |
| `ctx collections list` | List all collections |
| `ctx collections create NAME` | Create new collection |
| `ctx collections delete NAME` | Delete collection |

### Remote Sync (VS Code Extension Equivalent)

| Command | Description |
|---------|-------------|
| `ctx sync` | Force sync current directory |
| `ctx sync --watch` | Watch mode with auto-sync |
| `ctx sync --git-history` | Include git commit metadata |
| `ctx sync --endpoint URL` | Use custom upload endpoint |

### IDE Integration

| Command | Description |
|---------|-------------|
| `ctx bridge generate claude` | Generate Claude Desktop config |
| `ctx bridge generate cursor` | Generate Cursor IDE config |
| `ctx bridge generate windsurf` | Generate Windsurf config |
| `ctx bridge generate all` | Generate all IDE configs |

### Configuration

| Command | Description |
|---------|-------------|
| `ctx config [--get K] [--set K=V]` | View/edit configuration |
| `ctx completion [bash\|zsh\|fish]` | Shell completions |

## Examples

```bash
# Quick start for new users
ctx quickstart

# Check system health
ctx doctor

# Start services and monitor logs
ctx up --build
ctx logs indexer -f

# Search the codebase
ctx search "database connection" --language python --snippet
ctx answer "how does the indexing pipeline work?"

# Memory operations
ctx memory store "JWT tokens are used for auth" --kind explanation --tags topic=auth
ctx memory find "authentication" --limit 5

# Symbol graph navigation
ctx graph callers authenticate --depth 2
ctx graph definition MCPClient --language python
ctx graph importers qdrant_client

# Pattern search
ctx pattern "try: ... except: pass" --snippet
ctx pattern "retry with backoff" --mode description

# Manage collections
ctx collections list
ctx collections create my-project
ctx collections switch my-project

# Generate IDE configs
ctx bridge generate all

# Monitor and maintain
ctx status --verbose
ctx warmup --status
ctx index --watch
```

## Shell Completion

```bash
eval "$(ctx completion bash)"   # Bash
eval "$(ctx completion zsh)"    # Zsh
ctx completion fish | source    # Fish
```

## Configuration

Config loaded from `./.ctxrc` or `~/.ctxrc`:

```ini
[indexer]
url = http://localhost:8003
timeout = 30

[memory]
url = http://localhost:8002

[search]
default_limit = 10
default_collection = codebase

[docker]
compose_file = compose.yaml
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MCP_INDEXER_URL` | Indexer HTTP endpoint | `http://localhost:8003/mcp` |
| `MCP_MEMORY_URL` | Memory HTTP endpoint | `http://localhost:8002/mcp` |
| `COLLECTION_NAME` | Default collection | `codebase` |
| `COMPOSE_FILE` | Docker compose file | `compose.yaml` |

## Troubleshooting

Run the doctor command to diagnose issues:

```bash
ctx doctor
```

Common fixes:
- **Services not running**: `ctx up`
- **Models not loaded**: `ctx warmup`
- **Stale index**: `ctx prune && ctx index`
- **Config issues**: `ctx init --env-only`
