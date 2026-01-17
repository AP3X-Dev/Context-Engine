# ctx CLI

Unified command-line interface for Context-Engine.

## Installation

```bash
pip install -e .
```

## Commands

```
ctx up [--build] [--wait N]       Start services
ctx down [--volumes]              Stop services
ctx restart [--build]             Restart services
ctx status [--json] [--verbose]   Show stack health
ctx init [--force] [--global]     Setup wizard
ctx search <query> [options]      Semantic code search
ctx answer <query> [options]      LLM-generated answers
ctx index [path] [--watch]        Index codebase
ctx prune [--collection]          Remove stale entries
ctx config [--get K] [--set K=V]  View/edit configuration
ctx completion [bash|zsh|fish]    Shell completions
```

## Examples

```bash
ctx up --build
ctx status --verbose
ctx search "database connection" --language python
ctx answer "how does indexing work?"
ctx index --watch
ctx config --set indexer.url=http://localhost:8003
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

[search]
default_limit = 10
```
