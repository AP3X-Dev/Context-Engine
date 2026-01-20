"""
Tests for the ctx CLI package.

Tests cover:
- Configuration utilities (env loading, collection resolution, health checks)
- MCP client basics
- Command registration
- CLI argument parsing
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


# ==============================================================================
# Test: Environment file utilities (utils/env.py)
# ==============================================================================

class TestEnvUtilities:
    """Tests for scripts.ctx_cli.utils.env module."""

    def test_load_env_file_basic(self, tmp_path):
        """Test loading a basic .env file."""
        from scripts.ctx_cli.utils.env import load_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nKEY2=value2\n")

        result = load_env_file(env_file)

        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "value2"

    def test_load_env_file_with_quotes(self, tmp_path):
        """Test loading .env file with quoted values."""
        from scripts.ctx_cli.utils.env import load_env_file

        env_file = tmp_path / ".env"
        env_file.write_text('SINGLE=\'quoted\'\nDOUBLE="quoted"\n')

        result = load_env_file(env_file)

        assert result["SINGLE"] == "quoted"
        assert result["DOUBLE"] == "quoted"

    def test_load_env_file_with_comments(self, tmp_path):
        """Test that comments are ignored."""
        from scripts.ctx_cli.utils.env import load_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nKEY=value\n# Another comment\n")

        result = load_env_file(env_file)

        assert len(result) == 1
        assert result["KEY"] == "value"

    def test_load_env_file_empty_lines(self, tmp_path):
        """Test that empty lines are handled."""
        from scripts.ctx_cli.utils.env import load_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("\n\nKEY=value\n\n")

        result = load_env_file(env_file)

        assert result["KEY"] == "value"

    def test_load_env_file_nonexistent(self, tmp_path):
        """Test loading a nonexistent file returns empty dict."""
        from scripts.ctx_cli.utils.env import load_env_file

        env_file = tmp_path / "nonexistent.env"

        result = load_env_file(env_file)

        assert result == {}

    def test_find_env_file_in_current_dir(self, tmp_path):
        """Test finding .env in current directory."""
        from scripts.ctx_cli.utils.env import find_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value")

        result = find_env_file(start=tmp_path)

        assert result == env_file

    def test_find_env_file_in_parent(self, tmp_path):
        """Test finding .env in parent directory."""
        from scripts.ctx_cli.utils.env import find_env_file

        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value")
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        result = find_env_file(start=subdir)

        assert result == env_file

    def test_find_env_file_not_found(self, tmp_path):
        """Test when no .env file exists."""
        from scripts.ctx_cli.utils.env import find_env_file

        # Create a subdir without .env
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        result = find_env_file(start=subdir, max_parents=0)

        assert result is None

    def test_get_env_value_from_process_env(self):
        """Test that process environment takes priority."""
        from scripts.ctx_cli.utils.env import get_env_value

        with patch.dict(os.environ, {"TEST_KEY": "from_env"}):
            result = get_env_value("TEST_KEY")

        assert result == "from_env"

    def test_get_env_value_from_file(self, tmp_path):
        """Test getting value from .env file."""
        from scripts.ctx_cli.utils.env import get_env_value

        env_file = tmp_path / ".env"
        env_file.write_text("FILE_KEY=from_file")

        # Ensure not in process env
        with patch.dict(os.environ, {}, clear=False):
            if "FILE_KEY" in os.environ:
                del os.environ["FILE_KEY"]
            result = get_env_value("FILE_KEY", env_path=env_file)

        assert result == "from_file"

    def test_get_env_value_default(self):
        """Test default value when key not found."""
        from scripts.ctx_cli.utils.env import get_env_value

        with patch.dict(os.environ, {}, clear=False):
            if "NONEXISTENT_KEY" in os.environ:
                del os.environ["NONEXISTENT_KEY"]
            result = get_env_value("NONEXISTENT_KEY", default="default_val")

        assert result == "default_val"


# ==============================================================================
# Test: Configuration utilities (utils/config.py)
# ==============================================================================

class TestConfigUtilities:
    """Tests for scripts.ctx_cli.utils.config module."""

    def test_default_ports_defined(self):
        """Test that default ports are defined."""
        from scripts.ctx_cli.utils.config import DEFAULT_PORTS

        assert DEFAULT_PORTS["qdrant"] == 6333
        assert DEFAULT_PORTS["indexer"] == 8003
        assert DEFAULT_PORTS["memory"] == 8002

    def test_health_checks_defined(self):
        """Test that health checks are defined."""
        from scripts.ctx_cli.utils.config import HEALTH_CHECKS

        names = [check["name"] for check in HEALTH_CHECKS]
        assert "Qdrant" in names
        assert "Indexer" in names
        assert "Memory" in names

    def test_get_health_checks_returns_list(self):
        """Test get_health_checks returns a list of dicts."""
        from scripts.ctx_cli.utils.config import get_health_checks

        checks = get_health_checks()

        assert isinstance(checks, list)
        assert len(checks) >= 3
        for check in checks:
            assert "name" in check
            assert "port" in check
            assert "host" in check

    def test_get_health_checks_respects_env_override(self):
        """Test that environment variables override ports."""
        from scripts.ctx_cli.utils.config import get_health_checks

        with patch.dict(os.environ, {"QDRANT_PORT": "9999"}):
            checks = get_health_checks()

        qdrant_check = next(c for c in checks if c["name"] == "Qdrant")
        assert qdrant_check["port"] == 9999

    def test_get_health_checks_invalid_port_env(self):
        """Test that invalid port env var is ignored."""
        from scripts.ctx_cli.utils.config import get_health_checks, DEFAULT_PORTS

        with patch.dict(os.environ, {"QDRANT_PORT": "not_a_number"}):
            checks = get_health_checks()

        qdrant_check = next(c for c in checks if c["name"] == "Qdrant")
        assert qdrant_check["port"] == DEFAULT_PORTS["qdrant"]

    def test_resolve_collection_explicit(self):
        """Test explicit collection takes priority."""
        from scripts.ctx_cli.utils.config import resolve_collection

        result = resolve_collection(explicit="my-collection")

        assert result == "my-collection"

    def test_resolve_collection_from_env(self):
        """Test collection from COLLECTION_NAME env."""
        from scripts.ctx_cli.utils.config import resolve_collection

        with patch.dict(os.environ, {"COLLECTION_NAME": "env-collection"}):
            result = resolve_collection()

        assert result == "env-collection"

    def test_resolve_collection_explicit_over_env(self):
        """Test explicit overrides env."""
        from scripts.ctx_cli.utils.config import resolve_collection

        with patch.dict(os.environ, {"COLLECTION_NAME": "env-collection"}):
            result = resolve_collection(explicit="explicit-collection")

        assert result == "explicit-collection"

    def test_resolve_collection_none_when_not_set(self):
        """Test returns None when nothing is set."""
        from scripts.ctx_cli.utils.config import resolve_collection

        # Mock ConfigManager to return None
        mock_config = MagicMock()
        mock_config.get_default_collection.return_value = None

        with patch.dict(os.environ, {}, clear=False):
            if "COLLECTION_NAME" in os.environ:
                del os.environ["COLLECTION_NAME"]
            result = resolve_collection(config=mock_config)

        assert result is None

    def test_config_manager_get_indexer_url_default(self):
        """Test default indexer URL."""
        from scripts.ctx_cli.utils.config import ConfigManager

        with patch.dict(os.environ, {}, clear=False):
            for key in ["CTX_INDEXER_URL", "MCP_INDEXER_URL"]:
                if key in os.environ:
                    del os.environ[key]

            config = ConfigManager()
            url = config.get_indexer_url()

        assert url == "http://localhost:8003"

    def test_config_manager_get_indexer_url_from_env(self):
        """Test indexer URL from environment."""
        from scripts.ctx_cli.utils.config import ConfigManager

        with patch.dict(os.environ, {"MCP_INDEXER_URL": "http://custom:9000"}):
            config = ConfigManager()
            url = config.get_indexer_url()

        assert url == "http://custom:9000"

    def test_config_manager_get_memory_url_default(self):
        """Test default memory URL."""
        from scripts.ctx_cli.utils.config import ConfigManager

        with patch.dict(os.environ, {}, clear=False):
            for key in ["CTX_MEMORY_URL", "MCP_MEMORY_URL"]:
                if key in os.environ:
                    del os.environ[key]

            config = ConfigManager()
            url = config.get_memory_url()

        assert url == "http://localhost:8002"

    def test_config_manager_get_timeout_default(self):
        """Test default timeout."""
        from scripts.ctx_cli.utils.config import ConfigManager

        config = ConfigManager()
        timeout = config.get_timeout("indexer")

        assert timeout == 30


# ==============================================================================
# Test: MCP Client (utils/mcp_client.py)
# ==============================================================================

class TestMCPClient:
    """Tests for scripts.ctx_cli.utils.mcp_client module."""

    def test_mcp_error_str(self):
        """Test MCPError string representation."""
        from scripts.ctx_cli.utils.mcp_client import MCPError

        error = MCPError("Test error", code=123, data={"detail": "info"})

        assert "Test error" in str(error)
        assert "123" in str(error)

    def test_mcp_error_without_data(self):
        """Test MCPError without data."""
        from scripts.ctx_cli.utils.mcp_client import MCPError

        error = MCPError("Simple error", code=1)

        assert error.message == "Simple error"
        assert error.code == 1
        assert error.data is None

    def test_mcp_client_init_indexer(self):
        """Test MCPClient initialization for indexer."""
        from scripts.ctx_cli.utils.mcp_client import MCPClient

        # Clear MCP_INDEXER_URL to test default behavior (may be set by .env)
        env_override = {"MCP_INDEXER_URL": ""} if "MCP_INDEXER_URL" in os.environ else {}
        with patch.dict(os.environ, env_override, clear=False):
            client = MCPClient(server="indexer")

        # Accept default port 8003, or bridge port 30810, or custom URL
        assert client.base_url.endswith("/mcp")
        assert any(p in client.base_url for p in ["8003", "30810", "indexer"])

    def test_mcp_client_init_memory(self):
        """Test MCPClient initialization for memory."""
        from scripts.ctx_cli.utils.mcp_client import MCPClient

        with patch.dict(os.environ, {}, clear=False):
            client = MCPClient(server="memory")

        assert "8002" in client.base_url or "memory" in client.base_url.lower()

    def test_mcp_client_init_unknown_server(self):
        """Test MCPClient raises for unknown server."""
        from scripts.ctx_cli.utils.mcp_client import MCPClient

        with pytest.raises(ValueError, match="Unknown server"):
            MCPClient(server="unknown")

    def test_mcp_client_custom_url(self):
        """Test MCPClient with custom URL."""
        from scripts.ctx_cli.utils.mcp_client import MCPClient

        client = MCPClient(server="indexer", base_url="http://custom:1234")

        assert client.base_url == "http://custom:1234/mcp"

    def test_mcp_client_parse_sse(self):
        """Test SSE parsing."""
        from scripts.ctx_cli.utils.mcp_client import MCPClient

        client = MCPClient(server="indexer")

        sse_data = 'event: message\ndata: {"result": "success"}\n\n'
        result = client._parse_sse(sse_data)

        assert result == {"result": "success"}

    def test_mcp_client_parse_result_fastmcp_format(self):
        """Test parsing FastMCP content format."""
        from scripts.ctx_cli.utils.mcp_client import MCPClient

        client = MCPClient(server="indexer")

        result = {"content": [{"json": {"ok": True, "data": "test"}}]}
        parsed = client._parse_result(result)

        assert parsed["ok"] is True
        assert parsed["data"] == "test"

    def test_mcp_client_parse_result_text_json(self):
        """Test parsing text content that is JSON."""
        from scripts.ctx_cli.utils.mcp_client import MCPClient

        client = MCPClient(server="indexer")

        result = {"content": [{"text": '{"ok": true, "value": 42}'}]}
        parsed = client._parse_result(result)

        assert parsed["ok"] is True
        assert parsed["value"] == 42

    def test_mcp_client_parse_result_direct(self):
        """Test parsing direct result format."""
        from scripts.ctx_cli.utils.mcp_client import MCPClient

        client = MCPClient(server="indexer")

        result = {"results": [1, 2, 3], "total": 3}
        parsed = client._parse_result(result)

        assert parsed["ok"] is True
        assert parsed["results"] == [1, 2, 3]


# ==============================================================================
# Test: CLI Command Registration
# ==============================================================================

class TestCommandRegistration:
    """Tests for CLI command registration."""

    def test_all_commands_registered(self):
        """Test that all expected commands are in COMMANDS list."""
        from scripts.ctx_cli.commands import COMMANDS

        # Get command module names
        command_names = [cmd.__name__.split(".")[-1] for cmd in COMMANDS]

        expected = [
            "quickstart", "lifecycle", "status", "doctor", "logs",
            "init", "search", "answer", "memory", "graph", "pattern",
            "index", "sync", "prune", "collections", "warmup", "config",
            "bridge", "completion"
        ]

        for expected_cmd in expected:
            assert expected_cmd in command_names, f"Missing command: {expected_cmd}"

    def test_commands_have_register_function(self):
        """Test that all commands have register_command function."""
        from scripts.ctx_cli.commands import COMMANDS

        for cmd in COMMANDS:
            assert hasattr(cmd, "register_command"), \
                f"Command {cmd.__name__} missing register_command function"

    def test_register_all_commands(self):
        """Test register_all_commands function."""
        from scripts.ctx_cli.commands import register_all_commands
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        # Should not raise
        register_all_commands(subparsers)


# ==============================================================================
# Test: CLI Main Entry Point
# ==============================================================================

class TestCLIMain:
    """Tests for CLI main entry point."""

    def test_main_no_args_shows_help(self, capsys):
        """Test that running with no args shows help."""
        from scripts.ctx_cli.main import main

        with patch.object(sys, 'argv', ['ctx']):
            exit_code = main()

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "usage" in captured.out.lower() or "commands" in captured.out.lower()

    def test_main_version(self, capsys):
        """Test --version flag."""
        from scripts.ctx_cli.main import main
        from scripts.ctx_cli import __version__

        with patch.object(sys, 'argv', ['ctx', '--version']):
            with pytest.raises(SystemExit) as exc_info:
                main()

        # argparse calls sys.exit(0) for --version
        assert exc_info.value.code == 0

    def test_main_help(self, capsys):
        """Test --help flag."""
        from scripts.ctx_cli.main import main

        with patch.object(sys, 'argv', ['ctx', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0


# ==============================================================================
# Test: Lifecycle Commands (Rich fallback)
# ==============================================================================

class TestLifecycleRichFallback:
    """Tests for lifecycle command Rich fallback."""

    def test_lifecycle_imports_with_rich_available(self):
        """Test lifecycle module imports when Rich is available."""
        # Just importing should work
        from scripts.ctx_cli.commands import lifecycle
        assert lifecycle.RICH_AVAILABLE is True or lifecycle.RICH_AVAILABLE is False

    def test_lifecycle_print_function_exists(self):
        """Test _print helper exists."""
        from scripts.ctx_cli.commands.lifecycle import _print
        assert callable(_print)

    def test_lifecycle_uses_get_health_checks(self):
        """Test lifecycle uses centralized health checks."""
        from scripts.ctx_cli.commands import lifecycle
        import inspect

        source = inspect.getsource(lifecycle.run_up)
        assert "get_health_checks()" in source


# ==============================================================================
# Test: Search Command
# ==============================================================================

class TestSearchCommand:
    """Tests for search command."""

    def test_search_uses_resolve_collection(self):
        """Test search uses centralized collection resolution."""
        from scripts.ctx_cli.commands import search
        import inspect

        source = inspect.getsource(search.call_mcp_search)
        assert "resolve_collection" in source

    def test_search_register_command(self):
        """Test search command registration."""
        from scripts.ctx_cli.commands.search import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        register_command(subparsers)

        # Parse a search command
        args = parser.parse_args(["search", "test query"])
        assert args.query == "test query"

    def test_search_arguments(self):
        """Test search command arguments."""
        from scripts.ctx_cli.commands.search import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args([
            "search", "my query",
            "--limit", "5",
            "--language", "python",
            "--under", "src/",
            "--snippet"
        ])

        assert args.query == "my query"
        assert args.limit == 5
        assert args.language == "python"
        assert args.under == "src/"
        assert args.snippet is True


# ==============================================================================
# Test: Graph Command
# ==============================================================================

class TestGraphCommand:
    """Tests for graph command."""

    def test_graph_uses_resolve_collection(self):
        """Test graph uses centralized collection resolution."""
        from scripts.ctx_cli.commands import graph
        import inspect

        source = inspect.getsource(graph.call_symbol_graph)
        assert "resolve_collection" in source

    def test_graph_register_command(self):
        """Test graph command registration."""
        from scripts.ctx_cli.commands.graph import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        register_command(subparsers)

        # Parse a graph callers command
        args = parser.parse_args(["graph", "callers", "my_function"])
        assert args.symbol == "my_function"
        assert args.query_type == "callers"


# ==============================================================================
# Test: Index Command
# ==============================================================================

class TestIndexCommand:
    """Tests for index command."""

    def test_index_uses_centralized_env(self):
        """Test index uses centralized env utilities."""
        from scripts.ctx_cli.commands import index
        import inspect

        source = inspect.getsource(index)
        assert "from scripts.ctx_cli.utils.env import" in source

    def test_index_register_command(self):
        """Test index command registration."""
        from scripts.ctx_cli.commands.index import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        register_command(subparsers)

        # Parse an index command
        args = parser.parse_args(["index", "--recreate"])
        assert args.recreate is True

    def test_index_hard_flag(self):
        """Test index command --hard flag."""
        from scripts.ctx_cli.commands.index import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["index", "--hard"])
        assert args.hard is True

    def test_index_clear_caches_function(self):
        """Test clear_caches function exists."""
        from scripts.ctx_cli.commands.index import clear_caches
        assert callable(clear_caches)


# ==============================================================================
# Test: History Command
# ==============================================================================

class TestHistoryCommand:
    """Tests for history command."""

    def test_history_register_command(self):
        """Test history command registration."""
        from scripts.ctx_cli.commands.history import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()

        register_command(subparsers)

        # Parse a history command
        args = parser.parse_args(["history", "--max-commits", "100"])
        assert args.max_commits == 100

    def test_history_since_argument(self):
        """Test history command --since argument."""
        from scripts.ctx_cli.commands.history import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["history", "--since", "1 year ago"])
        assert args.since == "1 year ago"

    def test_history_local_flag(self):
        """Test history command --local flag."""
        from scripts.ctx_cli.commands.history import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["history", "--local"])
        assert args.local is True

    def test_history_in_commands_list(self):
        """Test history is in COMMANDS list."""
        from scripts.ctx_cli.commands import COMMANDS

        command_names = [cmd.__name__.split(".")[-1] for cmd in COMMANDS]
        assert "history" in command_names


# ==============================================================================
# Test: CLI Package
# ==============================================================================

class TestCLIPackage:
    """Tests for CLI package structure."""

    def test_version_defined(self):
        """Test version is defined."""
        from scripts.ctx_cli import __version__
        assert __version__
        assert isinstance(__version__, str)

    def test_main_exported(self):
        """Test main is exported."""
        from scripts.ctx_cli import main
        assert callable(main)

    def test_app_alias(self):
        """Test app alias for backward compatibility."""
        from scripts.ctx_cli import app, main
        assert app == main


# ==============================================================================
# Test: Reset Command
# ==============================================================================

class TestResetCommand:
    """Tests for scripts.ctx_cli.commands.reset module."""

    def test_reset_register_command(self):
        """Test reset command registers correctly."""
        from scripts.ctx_cli.commands.reset import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        # Parse a reset command with defaults
        args = parser.parse_args(["reset"])
        assert hasattr(args, "func")
        assert args.mcp is False
        assert args.sse is False
        assert args.skip_build is False
        assert args.skip_model is False

    def test_reset_mcp_flag(self):
        """Test reset command --mcp flag."""
        from scripts.ctx_cli.commands.reset import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["reset", "--mcp"])
        assert args.mcp is True
        assert args.sse is False

    def test_reset_sse_flag(self):
        """Test reset command --sse flag."""
        from scripts.ctx_cli.commands.reset import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["reset", "--sse"])
        assert args.sse is True
        assert args.mcp is False

    def test_reset_skip_flags(self):
        """Test reset command skip flags."""
        from scripts.ctx_cli.commands.reset import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["reset", "--skip-build", "--skip-model", "--skip-tokenizer"])
        assert args.skip_build is True
        assert args.skip_model is True
        assert args.skip_tokenizer is True

    def test_reset_in_commands_list(self):
        """Test reset is in COMMANDS list."""
        from scripts.ctx_cli.commands import COMMANDS

        command_names = [cmd.__name__.split(".")[-1] for cmd in COMMANDS]
        assert "reset" in command_names

    def test_reset_default_urls(self):
        """Test reset has correct default URLs."""
        from scripts.ctx_cli.commands.reset import (
            DEFAULT_MODEL_URL,
            DEFAULT_MODEL_PATH,
            DEFAULT_TOKENIZER_URL,
            DEFAULT_TOKENIZER_PATH,
        )

        assert "huggingface.co" in DEFAULT_MODEL_URL
        assert "granite" in DEFAULT_MODEL_URL
        assert DEFAULT_MODEL_PATH == "models/model.gguf"
        assert "huggingface.co" in DEFAULT_TOKENIZER_URL
        assert "bge-base" in DEFAULT_TOKENIZER_URL
        assert DEFAULT_TOKENIZER_PATH == "models/tokenizer.json"


# ==============================================================================
# Test: Sync Command with Daemon Support
# ==============================================================================

class TestSyncCommand:
    """Tests for scripts.ctx_cli.commands.sync module."""

    def test_sync_register_command(self):
        """Test sync command registers correctly."""
        from scripts.ctx_cli.commands.sync import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        # Parse a sync command with defaults
        args = parser.parse_args(["sync"])
        assert hasattr(args, "func")
        assert args.daemon is False
        assert args.stop is False
        assert args.status is False

    def test_sync_daemon_flag(self):
        """Test sync command --daemon flag."""
        from scripts.ctx_cli.commands.sync import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["sync", "--daemon"])
        assert args.daemon is True

    def test_sync_stop_flag(self):
        """Test sync command --stop flag."""
        from scripts.ctx_cli.commands.sync import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["sync", "--stop"])
        assert args.stop is True

    def test_sync_status_flag(self):
        """Test sync command --status flag."""
        from scripts.ctx_cli.commands.sync import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["sync", "--status"])
        assert args.status is True

    def test_sync_interval_argument(self):
        """Test sync command --interval argument."""
        from scripts.ctx_cli.commands.sync import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["sync", "--daemon", "--interval", "60"])
        assert args.interval == 60

    def test_sync_pid_file_location(self):
        """Test PID file is in ~/.ctx directory."""
        from scripts.ctx_cli.commands.sync import _get_pid_file, _get_log_file
        from pathlib import Path

        pid_file = _get_pid_file()
        log_file = _get_log_file()

        assert pid_file.parent == Path.home() / ".ctx"
        assert log_file.parent == Path.home() / ".ctx"
        assert pid_file.name == "sync-daemon.pid"
        assert log_file.name == "sync-daemon.log"

    def test_sync_in_commands_list(self):
        """Test sync is in COMMANDS list."""
        from scripts.ctx_cli.commands import COMMANDS

        command_names = [cmd.__name__.split(".")[-1] for cmd in COMMANDS]
        assert "sync" in command_names


# ==============================================================================
# Test: Enhance Command (Prompt Enhancement)
# ==============================================================================

class TestEnhanceCommand:
    """Tests for scripts.ctx_cli.commands.enhance module."""

    def test_enhance_register_command(self):
        """Test enhance command registers correctly."""
        from scripts.ctx_cli.commands.enhance import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        # Parse an enhance command
        args = parser.parse_args(["enhance", "test query"])
        assert hasattr(args, "func")
        assert args.query == "test query"
        assert args.detail is False
        assert args.unicorn is False

    def test_enhance_detail_flag(self):
        """Test enhance command --detail flag."""
        from scripts.ctx_cli.commands.enhance import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["enhance", "test", "--detail"])
        assert args.detail is True
        assert args.unicorn is False

    def test_enhance_unicorn_flag(self):
        """Test enhance command --unicorn flag."""
        from scripts.ctx_cli.commands.enhance import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["enhance", "test", "--unicorn"])
        assert args.unicorn is True
        assert args.detail is False

    def test_enhance_language_filter(self):
        """Test enhance command --language filter."""
        from scripts.ctx_cli.commands.enhance import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["enhance", "test", "--language", "python"])
        assert args.language == "python"

    def test_enhance_under_filter(self):
        """Test enhance command --under filter."""
        from scripts.ctx_cli.commands.enhance import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["enhance", "test", "--under", "scripts/"])
        assert args.under == "scripts/"

    def test_enhance_raw_flag(self):
        """Test enhance command --raw flag for piping."""
        from scripts.ctx_cli.commands.enhance import register_command
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_command(subparsers)

        args = parser.parse_args(["enhance", "test", "--raw"])
        assert args.raw is True

    def test_enhance_in_commands_list(self):
        """Test enhance is in COMMANDS list."""
        from scripts.ctx_cli.commands import COMMANDS

        command_names = [cmd.__name__.split(".")[-1] for cmd in COMMANDS]
        assert "enhance" in command_names
