#!/usr/bin/env zsh
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
#
# Zsh completion for ctx CLI
#
# To enable:
#   eval "$(ctx completion zsh)"
#
# Or add to ~/.zshrc:
#   eval "$(ctx completion zsh)"

#compdef ctx ctx-cli

_ctx() {
    local -a commands languages formats

    commands=(
        'up:Start Context-Engine services'
        'down:Stop Context-Engine services'
        'restart:Restart Context-Engine services'
        'index:Index codebase into Qdrant'
        'prune:Remove stale index entries'
        'search:Search codebase semantically'
        'answer:Get natural language answers about code'
        'status:Show Context-Engine stack status'
        'init:Initialize configuration files'
        'config:Show or edit configuration'
        'completion:Print shell completion script'
        '--help:Show help message'
        '--version:Show version information'
    )

    languages=(
        python javascript typescript go rust java c cpp csharp php ruby swift kotlin scala
    )

    formats=(json toon)

    _arguments -C \
        '1: :->command' \
        '*:: :->args'

    case $state in
        command)
            _describe 'ctx commands' commands
            ;;
        args)
            case $words[1] in
                up)
                    _arguments \
                        '--build[Rebuild containers before starting]' \
                        '--wait[Health check timeout in seconds]:seconds:(10 30 60 120)' \
                        '--help[Show help message]'
                    ;;
                down)
                    _arguments \
                        '--volumes[Remove volumes too]' \
                        '--help[Show help message]'
                    ;;
                restart)
                    _arguments \
                        '--build[Rebuild containers]' \
                        '--wait[Health check timeout in seconds]:seconds:(10 30 60 120)' \
                        '--help[Show help message]'
                    ;;
                index)
                    _arguments \
                        '--recreate[Drop and recreate collection]' \
                        '--watch[Watch for changes and reindex automatically]' \
                        '--subdir[Subdirectory to index]:directory:_directories' \
                        '--help[Show help message]'
                    ;;
                prune)
                    _arguments \
                        '--help[Show help message]'
                    ;;
                search)
                    _arguments \
                        '1:query:' \
                        '(-n --limit)'{-n,--limit}'[Maximum number of results]:limit:(3 5 10 20 50)' \
                        '(-l --language)'{-l,--language}'[Filter by programming language]:language:('${languages}')' \
                        '(-p --path)'{-p,--path}'[Filter by file path prefix]:path:_directories' \
                        '(-s --symbol)'{-s,--symbol}'[Filter by symbol name]:symbol:' \
                        '(-c --compact)'{-c,--compact}'[Compact output]' \
                        '--snippet[Include code snippets]' \
                        '--no-snippet[Exclude code snippets]' \
                        '(-f --format)'{-f,--format}'[Output format]:format:('${formats}')' \
                        '--help[Show help message]'
                    ;;
                answer)
                    _arguments \
                        '1:query:' \
                        '--budget[Token budget]:tokens:(1000 2000 4000 8000)' \
                        '--temperature[Generation temperature]:temp:(0.0 0.2 0.3 0.5 0.7)' \
                        '--expand[Enable query expansion]' \
                        '--help[Show help message]'
                    ;;
                status)
                    _arguments \
                        '--json[Output status as JSON]' \
                        '(-v --verbose)'{-v,--verbose}'[Show detailed per-service information]' \
                        '--help[Show help message]'
                    ;;
                init|config)
                    _arguments \
                        '--help[Show help message]'
                    ;;
                completion)
                    _arguments \
                        '1:shell:(bash zsh fish)' \
                        '--help[Show help message]'
                    ;;
            esac
            ;;
    esac
}

_ctx "$@"
