# Sisyphus Agent Configurations with Context-Engine Tools

Pre-configured [oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode) Sisyphus agents enhanced with Context-Engine MCP tools for semantic code search, symbol graph navigation, and memory storage.

## Installation

Copy the agent files to your Claude config directory:

```bash
cp -r agents/* ~/.claude/agents/
```

## Requirements

- [oh-my-opencode](https://github.com/code-yeongyu/oh-my-opencode) installed
- [Context-Engine](https://github.com/m1rl0k/Context-Engine) stack running
- MCP configured in `~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "context-engine": {
      "type": "local",
      "command": [
        "npx", "-y", "@context-engine-bridge/context-engine-mcp-bridge",
        "mcp-serve",
        "--workspace", "/path/to/your/project",
        "--indexer-url", "http://localhost:8003/mcp",
        "--memory-url", "http://localhost:8002/mcp"
      ],
      "enabled": true
    }
  }
}
```

## Agent Tool Matrix

| Agent | Primary Focus | Context-Engine Tools |
|-------|---------------|---------------------|
| **explore** | Fast codebase search | `repo_search`, `code_search`, `info_request`, `symbol_graph`, `pattern_search` |
| **explore-medium** | Deep pattern discovery | + `context_search`, `search_callers_for`, `search_importers_for` |
| **librarian** | Documentation & research | `repo_search`, `context_answer`, `context_search`, `info_request`, `search_tests_for`, `search_config_for`, `memory_find`, `memory_store` |
| **librarian-low** | Quick lookups | `repo_search`, `info_request`, `search_config_for` |
| **oracle** | Architecture & debugging | `repo_search`, `context_answer`, `symbol_graph`, `neo4j_graph_query`, `pattern_search`, `search_callers_for`, `change_history_for_path` |
| **oracle-medium** | Standard analysis | `repo_search`, `context_answer`, `symbol_graph`, `search_callers_for`, `pattern_search` |
| **oracle-low** | Quick questions | `repo_search`, `info_request`, `symbol_graph` |
| **sisyphus-junior** | Task execution | `repo_search`, `code_search`, `info_request`, `symbol_graph`, `search_tests_for` |
| **sisyphus-junior-high** | Complex execution | `repo_search`, `code_search`, `symbol_graph`, `pattern_search`, `search_callers_for` |
| **sisyphus-junior-low** | Simple tasks | `repo_search`, `info_request` |
| **metis** | Pre-planning analysis | `repo_search`, `context_answer`, `info_request`, `symbol_graph`, `search_tests_for`, `search_config_for` |
| **momus** | Plan review | `repo_search`, `symbol_graph`, `info_request` |
| **prometheus** | Strategic planning | `repo_search`, `context_answer`, `info_request`, `symbol_graph`, `search_tests_for`, `search_config_for` |
| **document-writer** | Documentation | `repo_search`, `context_answer`, `info_request`, `search_tests_for` |
| **frontend-engineer** | UI/UX | `repo_search`, `info_request`, `pattern_search`, `search_tests_for` |
| **frontend-engineer-high** | Complex UI | + `symbol_graph` |
| **frontend-engineer-low** | Simple styling | `repo_search`, `info_request` |
| **qa-tester** | Testing | `repo_search`, `search_tests_for`, `search_config_for`, `info_request` |
| **multimodal-looker** | Visual analysis | `repo_search`, `info_request` |

## Context-Engine Tools Reference

### Search Tools
| Tool | Use Case |
|------|----------|
| `repo_search` | Hybrid semantic + lexical code search with reranking |
| `code_search` | Alias for repo_search |
| `context_search` | Blend code + memory/docs results |
| `context_answer` | LLM-generated explanations with citations |
| `info_request` | Simple natural language queries |
| `pattern_search` | AST-aware structural pattern matching |

### Navigation Tools
| Tool | Use Case |
|------|----------|
| `symbol_graph` | Find callers, callees, definitions, importers |
| `neo4j_graph_query` | Advanced traversals (impact, transitive, cycles) |
| `search_callers_for` | Find symbol usages |
| `search_importers_for` | Find import references |

### Specialized Search
| Tool | Use Case |
|------|----------|
| `search_tests_for` | Find test files |
| `search_config_for` | Find config files (yaml/json/toml) |
| `change_history_for_path` | File change history |

### Memory Tools
| Tool | Use Case |
|------|----------|
| `memory_store` | Store knowledge with metadata |
| `memory_find` | Search stored memories |

## Key Behavior Changes

All agents are configured to:

1. **PREFER semantic search over grep** for concept-based queries
2. Use `symbol_graph` for call chain analysis before refactoring
3. Use `pattern_search` for finding similar code across languages
4. Use grep **ONLY** for exact literals (e.g., `"REDIS_HOST"`, `"UserAlreadyExists"`)

## Examples

```bash
# Agent uses repo_search instead of grep
"Find authentication handling" → repo_search(query="authentication mechanisms")

# Agent uses symbol_graph for impact analysis
"What calls this function?" → symbol_graph(symbol="authenticate", query_type="callers")

# Agent uses neo4j for advanced traversal
"What breaks if I change this?" → neo4j_graph_query(symbol="User", query_type="impact", depth=2)
```

## License

Same as Context-Engine (BUSL-1.1)
