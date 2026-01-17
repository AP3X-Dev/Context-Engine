#!/usr/bin/env python3
"""
Verification script for Context-Engine CLI package.

Tests that all modules can be imported and basic functionality works.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")

    try:
        # Core package
        from scripts.ctx_cli import __version__, app
        print(f"  ✓ scripts.ctx_cli (__version__={__version__})")

        # Commands
        from scripts.ctx_cli.commands import (
            lifecycle,
            index,
            status,
            config,
        )
        print("  ✓ scripts.ctx_cli.commands")

        # Output
        from scripts.ctx_cli.output import (
            format_error,
            format_success,
            format_info,
            format_search_results,
        )
        print("  ✓ scripts.ctx_cli.output")

        # Utils
        from scripts.ctx_cli.utils import (
            DockerComposeManager,
            ConfigManager,
            MCPClient,
        )
        print("  ✓ scripts.ctx_cli.utils")

        print("\n✓ All imports successful!")
        return True

    except ImportError as e:
        print(f"\n✗ Import failed: {e}")
        return False


def test_config_manager():
    """Test ConfigManager functionality."""
    print("\nTesting ConfigManager...")

    try:
        from scripts.ctx_cli.utils import ConfigManager

        config = ConfigManager()

        # Test default config
        default_config = config.get_default_config()
        assert "[indexer]" in default_config
        assert "[memory]" in default_config
        print("  ✓ Default config template")

        # Test getters
        indexer_url = config.get_indexer_url()
        assert "localhost" in indexer_url
        print(f"  ✓ Indexer URL: {indexer_url}")

        memory_url = config.get_memory_url()
        assert "localhost" in memory_url
        print(f"  ✓ Memory URL: {memory_url}")

        timeout = config.get_timeout()
        assert isinstance(timeout, int)
        print(f"  ✓ Timeout: {timeout}s")

        print("\n✓ ConfigManager working correctly!")
        return True

    except Exception as e:
        print(f"\n✗ ConfigManager failed: {e}")
        return False


def test_mcp_client():
    """Test MCPClient initialization (without actual connection)."""
    print("\nTesting MCPClient...")

    try:
        from scripts.ctx_cli.utils import MCPClient

        # Test indexer client
        indexer_client = MCPClient(server="indexer")
        assert "8003" in indexer_client.base_url
        print(f"  ✓ Indexer client: {indexer_client.base_url}")

        # Test memory client
        memory_client = MCPClient(server="memory")
        assert "8002" in memory_client.base_url
        print(f"  ✓ Memory client: {memory_client.base_url}")

        # Test custom URL
        custom_client = MCPClient(server="indexer", base_url="http://example.com:9000")
        assert "example.com" in custom_client.base_url
        print(f"  ✓ Custom URL: {custom_client.base_url}")

        print("\n✓ MCPClient working correctly!")
        return True

    except Exception as e:
        print(f"\n✗ MCPClient failed: {e}")
        return False


def test_formatters():
    """Test output formatters."""
    print("\nTesting formatters...")

    try:
        from scripts.ctx_cli.output import (
            format_error,
            format_success,
            format_info,
            format_warning,
        )
        from rich.panel import Panel

        # Test formatters return Panel objects
        error = format_error("Test error")
        assert isinstance(error, Panel)
        print("  ✓ format_error")

        success = format_success("Test success")
        assert isinstance(success, Panel)
        print("  ✓ format_success")

        info = format_info("Test info")
        assert isinstance(info, Panel)
        print("  ✓ format_info")

        warning = format_warning("Test warning")
        assert isinstance(warning, Panel)
        print("  ✓ format_warning")

        print("\n✓ Formatters working correctly!")
        return True

    except Exception as e:
        print(f"\n✗ Formatters failed: {e}")
        return False


def test_docker_manager():
    """Test DockerComposeManager initialization."""
    print("\nTesting DockerComposeManager...")

    try:
        from scripts.ctx_cli.utils import DockerComposeManager

        manager = DockerComposeManager()
        assert manager.cwd.exists()
        print(f"  ✓ Working directory: {manager.cwd}")

        # Test custom cwd
        custom_manager = DockerComposeManager(cwd="/tmp")
        assert custom_manager.cwd == Path("/tmp")
        print(f"  ✓ Custom cwd: {custom_manager.cwd}")

        print("\n✓ DockerComposeManager working correctly!")
        return True

    except Exception as e:
        print(f"\n✗ DockerComposeManager failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Context-Engine CLI Package Verification")
    print("=" * 60)

    results = []

    results.append(("Imports", test_imports()))
    results.append(("ConfigManager", test_config_manager()))
    results.append(("MCPClient", test_mcp_client()))
    results.append(("Formatters", test_formatters()))
    results.append(("DockerComposeManager", test_docker_manager()))

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{name:25} {status}")

    total = len(results)
    passed = sum(1 for _, p in results if p)

    print(f"\n{passed}/{total} tests passed")

    if passed == total:
        print("\n✓ All tests passed! Package is ready to use.")
        return 0
    else:
        print("\n✗ Some tests failed. Please fix the issues.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
