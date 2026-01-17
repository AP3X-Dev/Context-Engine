"""
Utility modules for CLI.

Provides helper utilities for:
- Docker Compose operations
- Configuration management
- MCP client communication
- UI helpers (Rich/plain text output)
"""

from scripts.ctx_cli.utils.docker import (
    run_docker_compose,
    wait_for_health_check,
    get_service_status,
    DockerComposeManager,
)
from scripts.ctx_cli.utils.config import ConfigManager
from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError
from scripts.ctx_cli.utils.ui import (
    get_console,
    strip_rich_markup,
    print_msg,
    print_error,
    print_warning,
    print_success,
    print_info,
    print_dim,
    print_panel,
    print_syntax,
    RICH_AVAILABLE,
)

__all__ = [
    "run_docker_compose",
    "wait_for_health_check",
    "get_service_status",
    "DockerComposeManager",
    "ConfigManager",
    "MCPClient",
    "MCPError",
    "get_console",
    "strip_rich_markup",
    "print_msg",
    "print_error",
    "print_warning",
    "print_success",
    "print_info",
    "print_dim",
    "print_panel",
    "print_syntax",
    "RICH_AVAILABLE",
]
