# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
#
# Fish completion for ctx CLI
#
# To enable:
#   ctx completion fish | source
#
# Or add to ~/.config/fish/config.fish:
#   ctx completion fish | source

# Disable file completion by default
complete -c ctx -f
complete -c ctx-cli -f

# Commands
complete -c ctx -n "__fish_use_subcommand" -a "up" -d "Start Context-Engine services"
complete -c ctx -n "__fish_use_subcommand" -a "down" -d "Stop Context-Engine services"
complete -c ctx -n "__fish_use_subcommand" -a "restart" -d "Restart Context-Engine services"
complete -c ctx -n "__fish_use_subcommand" -a "index" -d "Index codebase into Qdrant"
complete -c ctx -n "__fish_use_subcommand" -a "prune" -d "Remove stale index entries"
complete -c ctx -n "__fish_use_subcommand" -a "search" -d "Search codebase semantically"
complete -c ctx -n "__fish_use_subcommand" -a "answer" -d "Get natural language answers about code"
complete -c ctx -n "__fish_use_subcommand" -a "status" -d "Show Context-Engine stack status"
complete -c ctx -n "__fish_use_subcommand" -a "init" -d "Initialize configuration files"
complete -c ctx -n "__fish_use_subcommand" -a "config" -d "Show or edit configuration"
complete -c ctx -n "__fish_use_subcommand" -a "completion" -d "Print shell completion script"

# Global options
complete -c ctx -n "__fish_use_subcommand" -l help -d "Show help message"
complete -c ctx -n "__fish_use_subcommand" -l version -s V -d "Show version information"

# up command
complete -c ctx -n "__fish_seen_subcommand_from up" -l build -d "Rebuild containers before starting"
complete -c ctx -n "__fish_seen_subcommand_from up" -l wait -d "Health check timeout in seconds" -a "10 30 60 120"
complete -c ctx -n "__fish_seen_subcommand_from up" -l help -d "Show help message"

# down command
complete -c ctx -n "__fish_seen_subcommand_from down" -l volumes -d "Remove volumes too"
complete -c ctx -n "__fish_seen_subcommand_from down" -l help -d "Show help message"

# restart command
complete -c ctx -n "__fish_seen_subcommand_from restart" -l build -d "Rebuild containers"
complete -c ctx -n "__fish_seen_subcommand_from restart" -l wait -d "Health check timeout in seconds" -a "10 30 60 120"
complete -c ctx -n "__fish_seen_subcommand_from restart" -l help -d "Show help message"

# index command
complete -c ctx -n "__fish_seen_subcommand_from index" -l recreate -d "Drop and recreate collection"
complete -c ctx -n "__fish_seen_subcommand_from index" -l watch -d "Watch for changes and reindex automatically"
complete -c ctx -n "__fish_seen_subcommand_from index" -l subdir -d "Subdirectory to index" -r -F
complete -c ctx -n "__fish_seen_subcommand_from index" -l help -d "Show help message"

# prune command
complete -c ctx -n "__fish_seen_subcommand_from prune" -l help -d "Show help message"

# search command
complete -c ctx -n "__fish_seen_subcommand_from search" -s n -l limit -d "Maximum number of results" -a "3 5 10 20 50"
complete -c ctx -n "__fish_seen_subcommand_from search" -s l -l language -d "Filter by programming language" -a "python javascript typescript go rust java c cpp csharp php ruby swift kotlin scala"
complete -c ctx -n "__fish_seen_subcommand_from search" -s p -l path -d "Filter by file path prefix" -r -F
complete -c ctx -n "__fish_seen_subcommand_from search" -s s -l symbol -d "Filter by symbol name"
complete -c ctx -n "__fish_seen_subcommand_from search" -s c -l compact -d "Compact output"
complete -c ctx -n "__fish_seen_subcommand_from search" -l snippet -d "Include code snippets"
complete -c ctx -n "__fish_seen_subcommand_from search" -l no-snippet -d "Exclude code snippets"
complete -c ctx -n "__fish_seen_subcommand_from search" -s f -l format -d "Output format" -a "json toon"
complete -c ctx -n "__fish_seen_subcommand_from search" -l help -d "Show help message"

# answer command
complete -c ctx -n "__fish_seen_subcommand_from answer" -l budget -d "Token budget" -a "1000 2000 4000 8000"
complete -c ctx -n "__fish_seen_subcommand_from answer" -l temperature -d "Generation temperature" -a "0.0 0.2 0.3 0.5 0.7"
complete -c ctx -n "__fish_seen_subcommand_from answer" -l expand -d "Enable query expansion"
complete -c ctx -n "__fish_seen_subcommand_from answer" -l help -d "Show help message"

# status command
complete -c ctx -n "__fish_seen_subcommand_from status" -l json -d "Output status as JSON"
complete -c ctx -n "__fish_seen_subcommand_from status" -s v -l verbose -d "Show detailed per-service information"
complete -c ctx -n "__fish_seen_subcommand_from status" -l help -d "Show help message"

# init command
complete -c ctx -n "__fish_seen_subcommand_from init" -l help -d "Show help message"

# config command
complete -c ctx -n "__fish_seen_subcommand_from config" -l help -d "Show help message"

# completion command
complete -c ctx -n "__fish_seen_subcommand_from completion" -a "bash zsh fish" -d "Shell type"
complete -c ctx -n "__fish_seen_subcommand_from completion" -l help -d "Show help message"

# Duplicate all completions for ctx-cli
complete -c ctx-cli -n "__fish_use_subcommand" -a "up" -d "Start Context-Engine services"
complete -c ctx-cli -n "__fish_use_subcommand" -a "down" -d "Stop Context-Engine services"
complete -c ctx-cli -n "__fish_use_subcommand" -a "restart" -d "Restart Context-Engine services"
complete -c ctx-cli -n "__fish_use_subcommand" -a "index" -d "Index codebase into Qdrant"
complete -c ctx-cli -n "__fish_use_subcommand" -a "prune" -d "Remove stale index entries"
complete -c ctx-cli -n "__fish_use_subcommand" -a "search" -d "Search codebase semantically"
complete -c ctx-cli -n "__fish_use_subcommand" -a "answer" -d "Get natural language answers about code"
complete -c ctx-cli -n "__fish_use_subcommand" -a "status" -d "Show Context-Engine stack status"
complete -c ctx-cli -n "__fish_use_subcommand" -a "init" -d "Initialize configuration files"
complete -c ctx-cli -n "__fish_use_subcommand" -a "config" -d "Show or edit configuration"
complete -c ctx-cli -n "__fish_use_subcommand" -a "completion" -d "Print shell completion script"

complete -c ctx-cli -n "__fish_use_subcommand" -l help -d "Show help message"
complete -c ctx-cli -n "__fish_use_subcommand" -l version -s V -d "Show version information"
