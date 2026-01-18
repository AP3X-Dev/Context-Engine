"""
Configuration file management.

Handles loading and managing .ctxrc configuration files.
Provides centralized access to ports, URLs, and collection resolution.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, List
import configparser


# Default service ports - centralized for consistency
DEFAULT_PORTS = {
    "qdrant": 6333,
    "indexer": 8003,
    "indexer_internal": 18003,  # Internal health check port
    "memory": 8002,
    "memory_internal": 18002,   # Internal health check port
    "neo4j_bolt": 7687,
    "neo4j_http": 7474,
}

# Health check configuration - used by lifecycle, quickstart, status commands
HEALTH_CHECKS = [
    {"name": "Qdrant", "port": DEFAULT_PORTS["qdrant"], "host": "localhost"},
    {"name": "Indexer", "port": DEFAULT_PORTS["indexer"], "host": "localhost"},
    {"name": "Memory", "port": DEFAULT_PORTS["memory"], "host": "localhost"},
]


def _coerce_bool(value: Optional[str], default: bool = False) -> bool:
    """Convert string environment values to boolean."""
    if value is None:
        return default
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _load_env_file_simple(path: Path) -> Dict[str, str]:
    """Load environment variables from a .env file."""
    env: Dict[str, str] = {}
    if not path.exists():
        return env
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    env[key] = value
    except Exception:
        pass
    return env


def is_neo4j_enabled() -> bool:
    """
    Check if Neo4j graph backend is enabled.

    Checks:
        1. NEO4J_GRAPH environment variable
        2. .env file in project root

    Returns:
        True if NEO4J_GRAPH=1 is set
    """
    # Check environment first
    env_val = os.environ.get("NEO4J_GRAPH")
    if env_val is not None:
        return _coerce_bool(env_val, default=False)

    # Check .env file in project root
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        env_vars = _load_env_file_simple(env_path)
        env_val = env_vars.get("NEO4J_GRAPH")
        if env_val is not None:
            return _coerce_bool(env_val, default=False)

    return False


def get_health_checks() -> List[Dict[str, Any]]:
    """
    Get health check configuration with environment overrides.

    Includes Neo4j if NEO4J_GRAPH=1 is set.

    Environment variables:
        QDRANT_PORT: Override Qdrant port
        MCP_INDEXER_PORT: Override Indexer port
        MCP_MEMORY_PORT: Override Memory port
        NEO4J_GRAPH: Enable Neo4j health check

    Returns:
        List of health check configurations
    """
    # Start with base checks
    base_checks = list(HEALTH_CHECKS)

    # Add Neo4j if enabled
    if is_neo4j_enabled():
        base_checks.append({
            "name": "Neo4j",
            "port": DEFAULT_PORTS["neo4j_http"],
            "host": "localhost"
        })

    checks = []
    for check in base_checks:
        check_copy = check.copy()
        name_lower = check["name"].lower()

        # Check for port overrides
        if name_lower == "qdrant":
            port_override = os.environ.get("QDRANT_PORT")
        elif name_lower == "indexer":
            port_override = os.environ.get("MCP_INDEXER_PORT")
        elif name_lower == "memory":
            port_override = os.environ.get("MCP_MEMORY_PORT")
        elif name_lower == "neo4j":
            port_override = os.environ.get("NEO4J_HTTP_PORT")
        else:
            port_override = None

        if port_override:
            try:
                check_copy["port"] = int(port_override)
            except ValueError:
                pass  # Keep default if invalid

        checks.append(check_copy)

    return checks


class ConfigManager:
    """
    Manage Context-Engine CLI configuration.

    Supports loading configuration from:
    1. ./.ctxrc (current directory)
    2. ~/.ctxrc (home directory)
    3. Environment variables

    Notes on environment variables:
    - Generic config overrides use `CTX_` + uppercased key, e.g. `CTX_INDEXER_URL`
      for `indexer.url`.
    - For compatibility with other Context-Engine tooling and docs, the MCP endpoint
      helpers also honor `MCP_INDEXER_URL` and `MCP_MEMORY_URL`.
    """

    def __init__(self):
        """Initialize the configuration manager."""
        self.config = configparser.ConfigParser()
        self.config_path: Optional[Path] = None
        self.load_config()

    def find_config_file(self) -> Optional[Path]:
        """
        Find configuration file.

        Searches in order:
        1. ./.ctxrc (current directory)
        2. ~/.ctxrc (home directory)

        Returns:
            Path to config file or None if not found
        """
        # Check current directory
        local_config = Path.cwd() / ".ctxrc"
        if local_config.exists():
            return local_config

        # Check home directory
        global_config = Path.home() / ".ctxrc"
        if global_config.exists():
            return global_config

        return None

    def load_config(self) -> bool:
        """
        Load configuration from file.

        Returns:
            True if config was loaded, False otherwise
        """
        config_path = self.find_config_file()

        if config_path:
            self.config.read(config_path)
            self.config_path = config_path
            return True

        return False

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value.

        Supports dot notation for sections: "indexer.url"

        Args:
            key: Configuration key (optionally with section)
            default: Default value if not found

        Returns:
            Configuration value or default
        """
        # Check environment variable first (uppercase, dots to underscores)
        env_key = f"CTX_{key.upper().replace('.', '_')}"
        env_value = os.environ.get(env_key)
        if env_value is not None:
            return env_value

        # Parse section.key notation
        if "." in key:
            section, option = key.split(".", 1)
        else:
            section = "DEFAULT"
            option = key

        # Get from config file
        try:
            return self.config.get(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def set(self, key: str, value: str) -> None:
        """
        Set configuration value and save to file.

        Args:
            key: Configuration key (optionally with section)
            value: Configuration value
        """
        # Parse section.key notation
        if "." in key:
            section, option = key.split(".", 1)
        else:
            section = "DEFAULT"
            option = key

        # Create section if it doesn't exist
        if section != "DEFAULT" and not self.config.has_section(section):
            self.config.add_section(section)

        # Set value
        self.config.set(section, option, value)

        # Save to file
        if self.config_path is None:
            self.config_path = Path.cwd() / ".ctxrc"

        with open(self.config_path, "w") as f:
            self.config.write(f)

    def get_default_config(self) -> str:
        """
        Get default configuration template.

        Returns:
            Default configuration as INI string
        """
        return """# Context-Engine CLI Configuration

[indexer]
url = http://localhost:8003
timeout = 30

[memory]
url = http://localhost:8002
timeout = 30

[search]
default_limit = 10
default_collection = codebase
compact = false
include_snippet = true

[indexing]
recreate = false

[docker]
compose_file = docker-compose.yml
"""

    def get_default_collection(self) -> Optional[str]:
        """
        Get default collection name for search/answer tools.

        Resolution order is handled by `get()` (env override via CTX_* first, then file).
        """
        val = self.get("search.default_collection")
        if val is None:
            return None
        try:
            s = str(val).strip()
        except Exception:
            return None
        return s or None

    def get_indexer_url(self) -> str:
        """Get indexer server URL."""
        # Prefer explicit CLI env override, then common MCP_* env vars, then config/default.
        ctx = os.environ.get("CTX_INDEXER_URL")
        if ctx:
            return ctx
        mcp = os.environ.get("MCP_INDEXER_URL")
        if mcp:
            return mcp
        return self.get("indexer.url", "http://localhost:8003")

    def get_memory_url(self) -> str:
        """Get memory server URL."""
        ctx = os.environ.get("CTX_MEMORY_URL")
        if ctx:
            return ctx
        mcp = os.environ.get("MCP_MEMORY_URL")
        if mcp:
            return mcp
        return self.get("memory.url", "http://localhost:8002")

    def get_timeout(self, server: str = "indexer") -> int:
        """
        Get request timeout for server.

        Args:
            server: Server name ("indexer" or "memory")

        Returns:
            Timeout in seconds
        """
        timeout = self.get(f"{server}.timeout", "30")
        try:
            return int(timeout)
        except ValueError:
            return 30

    def get_search_defaults(self) -> Dict[str, Any]:
        """
        Get default search parameters.

        Returns:
            Dictionary of search defaults
        """
        return {
            "limit": int(self.get("search.default_limit", "10")),
            "compact": self.get("search.compact", "false").lower() == "true",
            "include_snippet": self.get("search.include_snippet", "true").lower() == "true",
        }


def resolve_collection(
    explicit: Optional[str] = None,
    config: Optional[ConfigManager] = None,
) -> Optional[str]:
    """
    Resolve collection name using standard priority order.

    Resolution order:
        1. Explicit value (CLI argument)
        2. COLLECTION_NAME environment variable
        3. Config file (search.default_collection)
        4. None (let server auto-detect)

    Args:
        explicit: Explicitly provided collection name (highest priority)
        config: ConfigManager instance (created if not provided)

    Returns:
        Collection name or None if not specified
    """
    # 1. Explicit takes priority
    if explicit:
        return explicit

    # 2. Check environment variable
    env_collection = os.environ.get("COLLECTION_NAME")
    if env_collection:
        return env_collection

    # 3. Check config file
    if config is None:
        config = ConfigManager()

    cfg_collection = config.get_default_collection()
    if cfg_collection:
        return cfg_collection

    # 4. Let server auto-detect
    return None
