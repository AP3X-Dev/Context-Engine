#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Test script for shell completion functionality.

Tests that completion scripts are properly generated and contain
expected content for all supported shells.
"""

import sys
import subprocess
from pathlib import Path


def test_completion_bash():
    """Test bash completion script generation."""
    print("Testing bash completion...")

    result = subprocess.run(
        [sys.executable, "-m", "scripts.ctx_cli", "completion", "bash"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"bash completion failed: {result.stderr}"

    script = result.stdout

    # Verify script contains expected content
    assert "#!/usr/bin/env bash" in script
    assert "_ctx_completion()" in script
    assert "complete -F _ctx_completion ctx" in script

    # Verify commands are listed
    commands = ["up", "down", "restart", "index", "prune", "search", "answer", "status", "completion"]
    for cmd in commands:
        assert cmd in script, f"Command '{cmd}' not found in bash completion"

    # Verify language options
    languages = ["python", "javascript", "typescript", "go", "rust"]
    for lang in languages:
        assert lang in script, f"Language '{lang}' not found in bash completion"

    print("  ✓ Bash completion script is valid")
    return True


def test_completion_zsh():
    """Test zsh completion script generation."""
    print("Testing zsh completion...")

    result = subprocess.run(
        [sys.executable, "-m", "scripts.ctx_cli", "completion", "zsh"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"zsh completion failed: {result.stderr}"

    script = result.stdout

    # Verify script contains expected content
    assert "#!/usr/bin/env zsh" in script
    assert "#compdef ctx" in script
    assert "_ctx()" in script

    # Verify commands with descriptions
    commands = [
        ("up", "Start Context-Engine services"),
        ("down", "Stop Context-Engine services"),
        ("search", "Search codebase semantically"),
        ("completion", "Print shell completion script")
    ]
    for cmd, desc in commands:
        assert f"'{cmd}:{desc}'" in script or f"'{cmd}" in script, \
            f"Command '{cmd}' not found in zsh completion"

    # Verify _arguments usage
    assert "_arguments" in script

    print("  ✓ Zsh completion script is valid")
    return True


def test_completion_fish():
    """Test fish completion script generation."""
    print("Testing fish completion...")

    result = subprocess.run(
        [sys.executable, "-m", "scripts.ctx_cli", "completion", "fish"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"fish completion failed: {result.stderr}"

    script = result.stdout

    # Verify script contains expected content
    assert "complete -c ctx" in script
    assert "__fish_use_subcommand" in script
    assert "__fish_seen_subcommand_from" in script

    # Verify commands with descriptions
    commands = [
        ("up", "Start Context-Engine services"),
        ("down", "Stop Context-Engine services"),
        ("search", "Search codebase semantically"),
        ("completion", "Print shell completion script")
    ]
    for cmd, desc in commands:
        assert f'"{cmd}"' in script or f"'{cmd}'" in script, \
            f"Command '{cmd}' not found in fish completion"
        assert desc in script, f"Description '{desc}' not found in fish completion"

    # Verify language completion
    assert "python javascript typescript" in script

    print("  ✓ Fish completion script is valid")
    return True


def test_completion_invalid_shell():
    """Test that invalid shell name produces error."""
    print("Testing error handling for invalid shell...")

    result = subprocess.run(
        [sys.executable, "-m", "scripts.ctx_cli", "completion", "invalid"],
        capture_output=True,
        text=True
    )

    assert result.returncode != 0, "Expected error for invalid shell"
    assert "invalid choice" in result.stderr.lower(), \
        f"Expected 'invalid choice' error, got: {result.stderr}"

    print("  ✓ Invalid shell handling works correctly")
    return True


def test_completion_help():
    """Test completion command help output."""
    print("Testing completion help...")

    result = subprocess.run(
        [sys.executable, "-m", "scripts.ctx_cli", "completion", "--help"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"completion --help failed: {result.stderr}"

    help_text = result.stdout

    # Verify help contains expected information
    assert "bash" in help_text
    assert "zsh" in help_text
    assert "fish" in help_text
    assert "eval" in help_text or "source" in help_text

    print("  ✓ Completion help is valid")
    return True


def test_main_help_includes_completion():
    """Test that main help lists completion command."""
    print("Testing main help includes completion...")

    result = subprocess.run(
        [sys.executable, "-m", "scripts.ctx_cli", "--help"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0, f"main --help failed: {result.stderr}"

    help_text = result.stdout

    # Verify completion command is listed
    assert "completion" in help_text.lower(), "completion command not listed in main help"

    print("  ✓ Main help includes completion command")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing ctx CLI Shell Completion")
    print("=" * 60)
    print()

    tests = [
        test_completion_bash,
        test_completion_zsh,
        test_completion_fish,
        test_completion_invalid_shell,
        test_completion_help,
        test_main_help_includes_completion,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  ✗ Test failed: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
