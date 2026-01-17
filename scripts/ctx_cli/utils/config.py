"""
Configuration file management.

Handles loading and managing .ctxrc configuration files.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
import configparser


class ConfigManager:
    """
    Manage Context-Engine CLI configuration.

    Supports loading configuration from:
    1. ./.ctxrc (current directory)
    2. ~/.ctxrc (home directory)
    3. Environment variables
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
compact = false
include_snippet = true

[indexing]
recreate = false

[docker]
compose_file = docker-compose.yml
"""

    def get_indexer_url(self) -> str:
        """Get indexer server URL."""
        return self.get("indexer.url", "http://localhost:8003")

    def get_memory_url(self) -> str:
        """Get memory server URL."""
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
