"""
Environment file utilities.

Provides consistent loading of .env files across CLI commands.
"""

from pathlib import Path
from typing import Optional, Dict


def find_env_file(start: Optional[Path] = None, max_parents: int = 3) -> Optional[Path]:
    """
    Find a .env file by searching current/parent directories.

    Args:
        start: Starting directory (defaults to cwd)
        max_parents: Maximum parent directories to search

    Returns:
        Path to .env file or None if not found
    """
    current = (start or Path.cwd()).resolve()
    for _ in range(max_parents + 1):
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def load_env_file(env_path: Path) -> Dict[str, str]:
    """
    Load a .env file and return key-value pairs.

    Handles:
    - Comments (lines starting with #)
    - Empty lines
    - Quoted values (single or double quotes)
    - Basic KEY=VALUE format

    Args:
        env_path: Path to .env file

    Returns:
        Dictionary of environment variables
    """
    env_vars: Dict[str, str] = {}

    if not env_path.exists():
        return env_vars

    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Skip lines without =
            if "=" not in line:
                continue

            # Parse KEY=VALUE
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # Remove quotes if present
            if value and len(value) >= 2:
                if (value[0] == '"' and value[-1] == '"') or \
                   (value[0] == "'" and value[-1] == "'"):
                    value = value[1:-1]

            if key:
                env_vars[key] = value

    except Exception:
        return {}

    return env_vars


def get_env_value(
    key: str,
    env_path: Optional[Path] = None,
    default: Optional[str] = None,
) -> Optional[str]:
    """
    Get an environment variable value, checking process env first, then .env file.

    Args:
        key: Environment variable name
        env_path: Optional path to .env file (searches if not provided)
        default: Default value if not found

    Returns:
        Value or default
    """
    import os

    # Check process environment first
    value = os.environ.get(key)
    if value is not None:
        return value

    # Try to load from .env file
    if env_path is None:
        env_path = find_env_file()

    if env_path:
        env_vars = load_env_file(env_path)
        value = env_vars.get(key)
        if value is not None:
            return value

    return default


def get_qdrant_url_for_host(env_path: Optional[Path] = None) -> str:
    """
    Get Qdrant URL suitable for host access (CLI running on host machine).

    The .env file typically has QDRANT_URL=http://qdrant:6333 for Docker containers,
    but when the CLI runs on the host, we need to use localhost instead.

    Args:
        env_path: Optional path to .env file

    Returns:
        Qdrant URL with Docker hostname normalized to localhost
    """
    url = get_env_value("QDRANT_URL", env_path, "http://localhost:6333")
    # Normalize Docker internal hostname to localhost for host access
    if url and "://qdrant:" in url:
        url = url.replace("://qdrant:", "://localhost:")
    return url or "http://localhost:6333"
