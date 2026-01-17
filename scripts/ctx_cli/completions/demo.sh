#!/usr/bin/env bash
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
#
# Demo script showing shell completion functionality
#
# This script demonstrates how to test completions without
# permanently installing them.

set -e

echo "============================================================"
echo "ctx CLI Shell Completion Demo"
echo "============================================================"
echo

# Check if ctx command exists
if ! command -v ctx &> /dev/null && ! command -v ctx-cli &> /dev/null; then
    echo "Note: 'ctx' command not found in PATH."
    echo "For this demo, we'll use: python -m scripts.ctx_cli"
    echo
    CTX_CMD="python -m scripts.ctx_cli"
else
    if command -v ctx &> /dev/null; then
        CTX_CMD="ctx"
    else
        CTX_CMD="ctx-cli"
    fi
fi

echo "1. Generate Bash completion script"
echo "   Command: $CTX_CMD completion bash"
echo
$CTX_CMD completion bash | head -20
echo "   ... (142 total lines)"
echo

echo "============================================================"
echo

echo "2. Generate Zsh completion script"
echo "   Command: $CTX_CMD completion zsh"
echo
$CTX_CMD completion zsh | head -20
echo "   ... (119 total lines)"
echo

echo "============================================================"
echo

echo "3. Generate Fish completion script"
echo "   Command: $CTX_CMD completion fish"
echo
$CTX_CMD completion fish | head -20
echo "   ... (102 total lines)"
echo

echo "============================================================"
echo

echo "4. Show available commands (from help)"
echo "   Command: $CTX_CMD --help"
echo
$CTX_CMD --help | grep -A 20 "commands:"
echo

echo "============================================================"
echo

echo "5. Completion usage examples:"
echo
echo "   Bash:"
echo "     eval \"\$($CTX_CMD completion bash)\""
echo "     # Then type: ctx <TAB>"
echo
echo "   Zsh:"
echo "     eval \"\$($CTX_CMD completion zsh)\""
echo "     # Then type: ctx <TAB>"
echo
echo "   Fish:"
echo "     $CTX_CMD completion fish | source"
echo "     # Then type: ctx <TAB>"
echo

echo "============================================================"
echo

echo "6. Test completion command with invalid shell (should error)"
echo "   Command: $CTX_CMD completion invalid"
echo
if $CTX_CMD completion invalid 2>&1 | grep -q "invalid choice"; then
    echo "   ✓ Correctly rejected invalid shell type"
else
    echo "   ✗ Should have rejected invalid shell type"
fi
echo

echo "============================================================"
echo "Demo complete!"
echo
echo "To enable completions permanently:"
echo "  - See completions/INSTALL.md for installation instructions"
echo "  - See completions/README.md for detailed documentation"
echo "============================================================"
