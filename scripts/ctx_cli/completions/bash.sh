#!/usr/bin/env bash
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
#
# Bash completion for ctx CLI
#
# To enable:
#   eval "$(ctx completion bash)"
#
# Or add to ~/.bashrc:
#   eval "$(ctx completion bash)"

_ctx_completion() {
    local cur prev words cword
    _init_completion || return

    # Available commands
    local commands="up down restart index prune search answer status init config completion --help --version"

    # Available languages for --language option
    local languages="python javascript typescript go rust java c cpp csharp php ruby swift kotlin scala"

    # Handle completion based on position
    case "${prev}" in
        ctx)
            COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") )
            return 0
            ;;
        up)
            COMPREPLY=( $(compgen -W "--build --wait --help" -- "${cur}") )
            return 0
            ;;
        down)
            COMPREPLY=( $(compgen -W "--volumes --help" -- "${cur}") )
            return 0
            ;;
        restart)
            COMPREPLY=( $(compgen -W "--build --wait --help" -- "${cur}") )
            return 0
            ;;
        index)
            COMPREPLY=( $(compgen -W "--recreate --watch --subdir --help" -- "${cur}") )
            return 0
            ;;
        prune)
            COMPREPLY=( $(compgen -W "--help" -- "${cur}") )
            return 0
            ;;
        search)
            COMPREPLY=( $(compgen -W "--limit --language --path --symbol --compact --snippet --no-snippet --format --help" -- "${cur}") )
            return 0
            ;;
        answer)
            COMPREPLY=( $(compgen -W "--budget --temperature --expand --help" -- "${cur}") )
            return 0
            ;;
        status)
            COMPREPLY=( $(compgen -W "--json --verbose --help" -- "${cur}") )
            return 0
            ;;
        init|config)
            COMPREPLY=( $(compgen -W "--help" -- "${cur}") )
            return 0
            ;;
        completion)
            COMPREPLY=( $(compgen -W "bash zsh fish" -- "${cur}") )
            return 0
            ;;
        --language|-l)
            COMPREPLY=( $(compgen -W "${languages}" -- "${cur}") )
            return 0
            ;;
        --format|-f)
            COMPREPLY=( $(compgen -W "json toon" -- "${cur}") )
            return 0
            ;;
        --wait)
            COMPREPLY=( $(compgen -W "10 30 60 120" -- "${cur}") )
            return 0
            ;;
        --limit|-n)
            COMPREPLY=( $(compgen -W "3 5 10 20 50" -- "${cur}") )
            return 0
            ;;
        --budget)
            COMPREPLY=( $(compgen -W "1000 2000 4000 8000" -- "${cur}") )
            return 0
            ;;
        --temperature)
            COMPREPLY=( $(compgen -W "0.0 0.2 0.3 0.5 0.7" -- "${cur}") )
            return 0
            ;;
        --path|-p|--subdir)
            # File path completion
            _filedir
            return 0
            ;;
        *)
            # Default completion based on current word
            if [[ ${cur} == -* ]]; then
                # Complete options for current command
                local cmd="${words[1]}"
                case "${cmd}" in
                    up)
                        COMPREPLY=( $(compgen -W "--build --wait --help" -- "${cur}") )
                        ;;
                    down)
                        COMPREPLY=( $(compgen -W "--volumes --help" -- "${cur}") )
                        ;;
                    restart)
                        COMPREPLY=( $(compgen -W "--build --wait --help" -- "${cur}") )
                        ;;
                    index)
                        COMPREPLY=( $(compgen -W "--recreate --watch --subdir --help" -- "${cur}") )
                        ;;
                    search)
                        COMPREPLY=( $(compgen -W "--limit --language --path --symbol --compact --snippet --no-snippet --format --help" -- "${cur}") )
                        ;;
                    answer)
                        COMPREPLY=( $(compgen -W "--budget --temperature --expand --help" -- "${cur}") )
                        ;;
                    status)
                        COMPREPLY=( $(compgen -W "--json --verbose --help" -- "${cur}") )
                        ;;
                    *)
                        COMPREPLY=( $(compgen -W "--help --version" -- "${cur}") )
                        ;;
                esac
            else
                # Complete commands if we're at the first argument
                if [[ ${cword} -eq 1 ]]; then
                    COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") )
                fi
            fi
            return 0
            ;;
    esac
}

# Register completion
complete -F _ctx_completion ctx
complete -F _ctx_completion ctx-cli
