#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Init command for ctx CLI.

All-in-one setup wizard for Context-Engine with:
- Environment detection (Docker, services)
- Interactive .env configuration
- Service lifecycle management
- Initial indexing
- Model warmup

Usage:
  ctx init [options]

Options:
  --full          Complete setup (env + services + index + warmup)
  --env-only      Configure .env only
  --no-start      Configure but don't start services
  --skip-index    Don't run initial index
  --skip-warmup   Don't warm up models
  --force         Overwrite existing configuration
  --global        Create global configuration in ~/.ctxrc
"""

import sys
import os
import time
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import configparser
import signal
import subprocess
import socket

# Try to import Rich for beautiful output, fall back to plain if not available
try:
    from rich.console import Console
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import box
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None


# Track if we should clean up on Ctrl+C
_cleanup_on_interrupt = True


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    if _cleanup_on_interrupt:
        print("\n\nSetup cancelled by user.")
        sys.exit(1)


# ============================================================================
# Rich-aware Output Functions
# ============================================================================

def print_header(text: str):
    """Print section header."""
    if RICH_AVAILABLE:
        console.print(f"\n[bold cyan]{text}[/bold cyan]")
    else:
        print(f"\n{'=' * 60}")
        print(text)
        print('=' * 60)


def print_info(text: str):
    """Print informational message."""
    if RICH_AVAILABLE:
        console.print(f"[dim]{text}[/dim]")
    else:
        print(text)


def print_success(text: str):
    """Print success message."""
    if RICH_AVAILABLE:
        console.print(f"[green]✓[/green] {text}")
    else:
        print(f"✓ {text}")


def print_error(text: str):
    """Print error message."""
    if RICH_AVAILABLE:
        console.print(f"[red]✗[/red] {text}")
    else:
        print(f"✗ {text}")


def print_warning(text: str):
    """Print warning message."""
    if RICH_AVAILABLE:
        console.print(f"[yellow]![/yellow] {text}")
    else:
        print(f"! {text}")


def prompt_choice(question: str, choices: List[str], default: Optional[int] = None) -> int:
    """
    Prompt user to choose from a list of options.

    Args:
        question: Question to ask
        choices: List of choice descriptions
        default: Default choice index (0-based) or None

    Returns:
        Index of chosen option (0-based)
    """
    if RICH_AVAILABLE:
        console.print(f"\n[bold]{question}[/bold]")
        for i, choice in enumerate(choices, 1):
            default_marker = " [dim](default)[/dim]" if default is not None and i - 1 == default else ""
            console.print(f"  {i}. {choice}{default_marker}")
    else:
        print(f"\n{question}")
        for i, choice in enumerate(choices, 1):
            default_marker = " (default)" if default is not None and i - 1 == default else ""
            print(f"  {i}. {choice}{default_marker}")

    while True:
        if default is not None:
            prompt_text = f"Choice [1-{len(choices)}] (default: {default + 1}): "
        else:
            prompt_text = f"Choice [1-{len(choices)}]: "

        response = input(prompt_text).strip()

        # Use default if provided and user just pressed Enter
        if not response and default is not None:
            return default

        # Validate choice
        try:
            choice_num = int(response)
            if 1 <= choice_num <= len(choices):
                return choice_num - 1
            else:
                print(f"Please enter a number between 1 and {len(choices)}")
        except ValueError:
            print("Please enter a valid number")


def prompt_string(question: str, default: Optional[str] = None, required: bool = False) -> str:
    """
    Prompt user for a string value.

    Args:
        question: Question to ask
        default: Default value or None
        required: Whether a value is required

    Returns:
        User's response or default
    """
    if RICH_AVAILABLE:
        while True:
            result = Prompt.ask(question, default=default or "")
            if required and not result:
                console.print("[yellow]This field is required[/yellow]")
                continue
            return result
    else:
        if default:
            prompt_text = f"{question} (default: {default}): "
        else:
            prompt_text = f"{question}: "

        while True:
            response = input(prompt_text).strip()
            if not response and default:
                return default
            if required and not response:
                print("This field is required")
                continue
            return response


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """
    Prompt user for yes/no response.

    Args:
        question: Question to ask
        default: Default value (True for yes, False for no)

    Returns:
        True for yes, False for no
    """
    if RICH_AVAILABLE:
        return Confirm.ask(question, default=default)
    else:
        default_text = "Y/n" if default else "y/N"
        prompt_text = f"{question} [{default_text}]: "

        while True:
            response = input(prompt_text).strip().lower()

            # Use default if user just pressed Enter
            if not response:
                return default

            if response in ('y', 'yes'):
                return True
            elif response in ('n', 'no'):
                return False
            else:
                print("Please enter 'y' or 'n'")


# ============================================================================
# Environment Detection
# ============================================================================

def check_docker_available() -> bool:
    """Check if Docker is available."""
    return shutil.which("docker") is not None


def check_docker_compose_available() -> bool:
    """Check if Docker Compose is available."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_service_running(port: int, host: str = "localhost") -> bool:
    """Check if a service is running on a specific port."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except (socket.timeout, socket.error):
        return False


def detect_environment() -> Dict[str, Any]:
    """
    Detect current environment state.

    Returns:
        Dictionary with environment information
    """
    env = {
        "docker_available": check_docker_available(),
        "docker_compose_available": check_docker_compose_available(),
        "services_running": {
            "qdrant": check_service_running(6333),
            "mcp_indexer": check_service_running(8003),
            "mcp_memory": check_service_running(8002),
            "neo4j": check_service_running(7687),
        },
    }

    # Check if .env exists
    env_file = Path.cwd() / ".env"
    env["env_file_exists"] = env_file.exists()

    # Check if docker-compose.yml exists
    compose_file = find_docker_compose()
    env["compose_file"] = compose_file

    return env


def print_environment_status(env: Dict[str, Any]):
    """Print current environment status."""
    if RICH_AVAILABLE:
        table = Table(title="Environment Detection", box=box.ROUNDED)
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="bold")

        # Docker
        status = "[green]Available[/green]" if env["docker_available"] else "[red]Not Found[/red]"
        table.add_row("Docker", status)

        status = "[green]Available[/green]" if env["docker_compose_available"] else "[red]Not Found[/red]"
        table.add_row("Docker Compose", status)

        # Configuration
        status = "[green]Found[/green]" if env["env_file_exists"] else "[yellow]Missing[/yellow]"
        table.add_row(".env file", status)

        status = "[green]Found[/green]" if env["compose_file"] else "[yellow]Not Found[/yellow]"
        table.add_row("docker-compose.yml", status)

        # Services
        for service, running in env["services_running"].items():
            status = "[green]Running[/green]" if running else "[dim]Stopped[/dim]"
            table.add_row(f"{service} service", status)

        console.print(table)
    else:
        print("\nEnvironment Detection:")
        print(f"  Docker: {'Available' if env['docker_available'] else 'Not Found'}")
        print(f"  Docker Compose: {'Available' if env['docker_compose_available'] else 'Not Found'}")
        print(f"  .env file: {'Found' if env['env_file_exists'] else 'Missing'}")
        print(f"  docker-compose.yml: {'Found' if env['compose_file'] else 'Not Found'}")
        print("\nServices:")
        for service, running in env["services_running"].items():
            print(f"  {service}: {'Running' if running else 'Stopped'}")


# ============================================================================
# Original Helper Functions (Preserved)
# ============================================================================

def find_docker_compose() -> Optional[Path]:
    """
    Find docker-compose.yml in current or parent directories.

    Returns:
        Path to docker-compose.yml or None if not found
    """
    current = Path.cwd()

    # Check current directory
    compose_file = current / "docker-compose.yml"
    if compose_file.exists():
        return compose_file

    # Check parent directories (up to 3 levels)
    for _ in range(3):
        current = current.parent
        compose_file = current / "docker-compose.yml"
        if compose_file.exists():
            return compose_file

    return None


def suggest_collection_name(project_path: Path) -> str:
    """
    Suggest a collection name based on directory name.

    Args:
        project_path: Path to the project directory

    Returns:
        Suggested collection name (lowercase, alphanumeric + hyphens)
    """
    name = project_path.name.lower()
    # Replace underscores and spaces with hyphens
    name = name.replace('_', '-').replace(' ', '-')
    # Remove non-alphanumeric characters except hyphens
    name = ''.join(c for c in name if c.isalnum() or c == '-')
    # Remove leading/trailing hyphens
    name = name.strip('-')
    # Ensure it's not empty
    return name if name else "default"


def validate_url(url: str) -> bool:
    """
    Validate URL format.

    Args:
        url: URL to validate

    Returns:
        True if valid, False otherwise
    """
    return url.startswith(('http://', 'https://'))


def check_existing_config(global_mode: bool) -> Tuple[bool, Optional[Path]]:
    """
    Check if configuration file already exists.

    Args:
        global_mode: True to check global config, False for local

    Returns:
        Tuple of (exists, path)
    """
    if global_mode:
        config_path = Path.home() / ".ctxrc"
    else:
        config_path = Path.cwd() / ".ctxrc"

    return config_path.exists(), config_path


def write_config(config_data: Dict[str, Any], config_path: Path) -> None:
    """
    Write configuration to file.

    Args:
        config_data: Configuration data
        config_path: Path to write config file
    """
    config = configparser.ConfigParser()

    # Add sections and values
    for section, values in config_data.items():
        if section == "DEFAULT":
            for key, value in values.items():
                config["DEFAULT"][key] = str(value)
        else:
            if not config.has_section(section):
                config.add_section(section)
            for key, value in values.items():
                config.set(section, key, str(value))

    # Write to file
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        # Write header comment
        f.write("# Context-Engine CLI Configuration\n")
        f.write(f"# Generated by ctx init\n\n")
        config.write(f)


def print_summary(config_data: Dict[str, Any], config_path: Path):
    """
    Print configuration summary.

    Args:
        config_data: Configuration data
        config_path: Path where config will be written
    """
    if RICH_AVAILABLE:
        table = Table(title="Configuration Summary", box=box.ROUNDED)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="yellow")

        table.add_row("Config file", str(config_path))

        mode = config_data.get("DEFAULT", {}).get("mode", "unknown")
        table.add_row("Mode", mode)

        if mode == "docker":
            docker_config = config_data.get("docker", {})
            table.add_row("Docker Compose", docker_config.get('compose_file', 'N/A'))
            table.add_row("Project name", docker_config.get('project_name', 'N/A'))
        elif mode == "remote":
            remote_config = config_data.get("remote", {})
            table.add_row("Indexer URL", remote_config.get('indexer_url', 'N/A'))
            table.add_row("Memory URL", remote_config.get('memory_url', 'N/A'))

        workspace_config = config_data.get("workspace", {})
        table.add_row("Default path", workspace_config.get('default_path', 'N/A'))
        table.add_row("Collection", workspace_config.get('collection', 'N/A'))

        console.print(table)
    else:
        print("\n" + "=" * 60)
        print("Configuration Summary")
        print("=" * 60)
        print(f"\nConfig file: {config_path}")
        print("\nSettings:")

        # Print mode
        mode = config_data.get("DEFAULT", {}).get("mode", "unknown")
        print(f"  Mode: {mode}")

        # Print mode-specific settings
        if mode == "docker":
            docker_config = config_data.get("docker", {})
            print(f"  Docker Compose file: {docker_config.get('compose_file', 'N/A')}")
            print(f"  Project name: {docker_config.get('project_name', 'N/A')}")
        elif mode == "remote":
            remote_config = config_data.get("remote", {})
            print(f"  Indexer URL: {remote_config.get('indexer_url', 'N/A')}")
            print(f"  Memory URL: {remote_config.get('memory_url', 'N/A')}")

        # Print workspace settings
        workspace_config = config_data.get("workspace", {})
        print(f"  Default path: {workspace_config.get('default_path', 'N/A')}")
        print(f"  Collection: {workspace_config.get('collection', 'N/A')}")


# ============================================================================
# .env Configuration
# ============================================================================

def configure_env_file(skip_if_exists: bool = False) -> bool:
    """
    Configure .env file interactively.

    Args:
        skip_if_exists: Skip if .env already exists

    Returns:
        True if configured, False if skipped
    """
    env_file = Path.cwd() / ".env"

    if env_file.exists() and skip_if_exists:
        print_info(f".env file already exists: {env_file}")
        return False

    if env_file.exists():
        if not prompt_yes_no("A .env file already exists. Modify it?", default=False):
            return False

    print_header("Environment Configuration")

    # Embedding model selection
    model_choice = prompt_choice(
        "Select embedding model",
        [
            "BAAI/bge-base-en-v1.5 (FastEmbed - Fast, local, recommended)",
            "jinaai/jina-embeddings-v3 (Jina AI - High quality, requires API key)",
            "text-embedding-3-small (OpenAI - Requires API key)",
            "Custom model"
        ],
        default=0
    )

    embedding_config = {}

    if model_choice == 0:
        embedding_config["EMBEDDING_MODEL"] = "BAAI/bge-base-en-v1.5"
        embedding_config["EMBEDDING_PROVIDER"] = "fastembed"
    elif model_choice == 1:
        embedding_config["EMBEDDING_MODEL"] = "jinaai/jina-embeddings-v3"
        embedding_config["EMBEDDING_PROVIDER"] = "jina"
        api_key = prompt_string("Jina AI API key", required=True)
        embedding_config["JINA_API_KEY"] = api_key
    elif model_choice == 2:
        embedding_config["EMBEDDING_MODEL"] = "text-embedding-3-small"
        embedding_config["EMBEDDING_PROVIDER"] = "openai"
        api_key = prompt_string("OpenAI API key", required=True)
        embedding_config["OPENAI_API_KEY"] = api_key
    else:
        model = prompt_string("Model name", required=True)
        provider = prompt_string("Provider (fastembed/openai/jina)", default="fastembed")
        embedding_config["EMBEDDING_MODEL"] = model
        embedding_config["EMBEDDING_PROVIDER"] = provider

    # Collection name
    suggested_collection = suggest_collection_name(Path.cwd())
    collection_name = prompt_string("Collection name", default=suggested_collection)
    embedding_config["COLLECTION_NAME"] = collection_name

    # Optional: LLM provider for context_answer
    if prompt_yes_no("Configure LLM for context_answer? (optional)", default=False):
        llm_choice = prompt_choice(
            "Select LLM provider",
            [
                "GLM (ZhipuAI)",
                "OpenAI",
                "MiniMax",
                "Skip"
            ],
            default=3
        )

        if llm_choice == 0:
            api_key = prompt_string("GLM API key", required=True)
            embedding_config["GLM_API_KEY"] = api_key
            embedding_config["GLM_MODEL"] = "glm-4.7"
        elif llm_choice == 1:
            api_key = prompt_string("OpenAI API key", required=True)
            embedding_config["OPENAI_API_KEY"] = api_key
            embedding_config["OPENAI_MODEL"] = "gpt-4"
        elif llm_choice == 2:
            api_key = prompt_string("MiniMax API key", required=True)
            embedding_config["MINIMAX_API_KEY"] = api_key
            embedding_config["MINIMAX_MODEL"] = "MiniMax-M2"

    # Write or update .env file
    if env_file.exists():
        # Read existing .env
        with open(env_file, 'r') as f:
            lines = f.readlines()

        # Update values
        updated_lines = []
        updated_keys = set()

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                updated_lines.append(line)
                continue

            if '=' in line:
                key = line.split('=', 1)[0].strip()
                if key in embedding_config:
                    updated_lines.append(f"{key}={embedding_config[key]}")
                    updated_keys.add(key)
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)

        # Add new keys
        for key, value in embedding_config.items():
            if key not in updated_keys:
                updated_lines.append(f"{key}={value}")

        # Write back
        with open(env_file, 'w') as f:
            f.write('\n'.join(updated_lines) + '\n')

        print_success(f"Updated .env file: {env_file}")
    else:
        # Create new .env from template
        template_content = f"""# Context-Engine Configuration
# Generated by ctx init

# Qdrant connection
QDRANT_URL=http://qdrant:6333

# Collection settings
COLLECTION_NAME={embedding_config.get('COLLECTION_NAME', 'codebase')}
MULTI_REPO_MODE=1

# Embedding settings
EMBEDDING_MODEL={embedding_config.get('EMBEDDING_MODEL', 'BAAI/bge-base-en-v1.5')}
EMBEDDING_PROVIDER={embedding_config.get('EMBEDDING_PROVIDER', 'fastembed')}

# MCP server ports
FASTMCP_HOST=0.0.0.0
FASTMCP_PORT=8000
FASTMCP_INDEXER_PORT=8001

# HTTP transport
FASTMCP_HTTP_TRANSPORT=http
FASTMCP_HTTP_PORT=8002
FASTMCP_INDEXER_HTTP_PORT=8003

# Reranker settings
RERANKER_ENABLED=1
RERANKER_MODEL=jinaai/jina-reranker-v2-base-multilingual

# Neo4j graph
NEO4J_ENABLED=1
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=contextengine

# Symbol graph
SYMBOL_GRAPH_ENABLED=1
"""

        # Add API keys if configured
        if "JINA_API_KEY" in embedding_config:
            template_content += f"\nJINA_API_KEY={embedding_config['JINA_API_KEY']}"
        if "OPENAI_API_KEY" in embedding_config:
            template_content += f"\nOPENAI_API_KEY={embedding_config['OPENAI_API_KEY']}"
        if "GLM_API_KEY" in embedding_config:
            template_content += f"\nGLM_API_KEY={embedding_config['GLM_API_KEY']}"
            template_content += f"\nGLM_MODEL={embedding_config.get('GLM_MODEL', 'glm-4.7')}"
        if "MINIMAX_API_KEY" in embedding_config:
            template_content += f"\nMINIMAX_API_KEY={embedding_config['MINIMAX_API_KEY']}"
            template_content += f"\nMINIMAX_MODEL={embedding_config.get('MINIMAX_MODEL', 'MiniMax-M2')}"

        with open(env_file, 'w') as f:
            f.write(template_content)

        print_success(f"Created .env file: {env_file}")

    return True


# ============================================================================
# Service Management
# ============================================================================

def start_services(build: bool = False) -> bool:
    """
    Start Docker Compose services.

    Args:
        build: Whether to rebuild images

    Returns:
        True if successful
    """
    print_header("Starting Services")

    compose_file = find_docker_compose()
    if not compose_file:
        print_error("docker-compose.yml not found")
        return False

    cmd = ["docker", "compose", "up", "-d"]
    if build:
        cmd.append("--build")

    try:
        if RICH_AVAILABLE:
            with console.status("[bold blue]Starting services...", spinner="dots"):
                result = subprocess.run(
                    cmd,
                    cwd=compose_file.parent,
                    capture_output=True,
                    text=True
                )
        else:
            print("Starting services...")
            result = subprocess.run(cmd, cwd=compose_file.parent)

        if result.returncode == 0:
            print_success("Services started successfully")
            return True
        else:
            print_error("Failed to start services")
            if hasattr(result, 'stderr') and result.stderr:
                print_error(result.stderr)
            return False
    except Exception as e:
        print_error(f"Error starting services: {e}")
        return False


def wait_for_services(timeout: float = 60.0) -> bool:
    """
    Wait for services to become healthy.

    Args:
        timeout: Maximum time to wait in seconds

    Returns:
        True if all services are healthy
    """
    services = [
        ("Qdrant", 6333),
        ("MCP Indexer", 8003),
        ("MCP Memory", 8002),
    ]

    if RICH_AVAILABLE:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for name, port in services:
                task = progress.add_task(f"Waiting for {name}...", total=None)

                start_time = time.time()
                while time.time() - start_time < timeout:
                    if check_service_running(port):
                        progress.remove_task(task)
                        print_success(f"{name} is ready")
                        break
                    time.sleep(0.5)
                else:
                    progress.remove_task(task)
                    print_error(f"{name} did not become ready")
                    return False
    else:
        for name, port in services:
            print(f"Waiting for {name}...")
            start_time = time.time()
            while time.time() - start_time < timeout:
                if check_service_running(port):
                    print_success(f"{name} is ready")
                    break
                time.sleep(0.5)
            else:
                print_error(f"{name} did not become ready")
                return False

    return True


# ============================================================================
# Indexing
# ============================================================================

def run_initial_index() -> bool:
    """
    Run initial indexing of the workspace.

    Returns:
        True if successful
    """
    print_header("Initial Indexing")

    try:
        # Import here to avoid circular dependency
        from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError

        client = MCPClient(server="indexer", timeout=300)

        if RICH_AVAILABLE:
            with console.status("[bold blue]Indexing workspace...", spinner="dots"):
                result = client.call_tool("qdrant_index_root")
        else:
            print("Indexing workspace...")
            result = client.call_tool("qdrant_index_root")

        if result.get("ok"):
            print_success("Indexing completed successfully")
            if "indexed" in result:
                print_info(f"  Indexed {result['indexed']} files")
            return True
        else:
            print_error(f"Indexing failed: {result.get('error', 'Unknown error')}")
            return False
    except Exception as e:
        print_error(f"Error during indexing: {e}")
        return False


# ============================================================================
# Model Warmup
# ============================================================================

def warmup_models() -> bool:
    """
    Warm up embedding and reranking models.

    Returns:
        True if successful
    """
    print_header("Model Warmup")

    try:
        from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError

        client = MCPClient(server="indexer", timeout=60)

        if RICH_AVAILABLE:
            with console.status("[bold blue]Warming up models...", spinner="dots"):
                result = client.call_tool("warmup_status")
        else:
            print("Warming up models...")
            result = client.call_tool("warmup_status")

        if result.get("ok"):
            print_success("Models warmed up successfully")
            return True
        else:
            print_warning("Model warmup check completed with warnings")
            return True  # Not critical
    except Exception as e:
        print_warning(f"Could not verify model warmup: {e}")
        return True  # Not critical


# ============================================================================
# Main Setup Flow
# ============================================================================

def run_init(args) -> int:
    """
    Run the init command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    global _cleanup_on_interrupt

    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Print welcome
        if RICH_AVAILABLE:
            console.print(Panel.fit(
                "[bold cyan]Context-Engine Setup Wizard[/bold cyan]\n\n"
                "This wizard will configure your Context-Engine installation.\n"
                "Press Ctrl+C at any time to cancel.",
                border_style="blue"
            ))
        else:
            print("=" * 60)
            print("Context-Engine Setup Wizard")
            print("=" * 60)
            print("\nThis wizard will configure your Context-Engine installation.")
            print("Press Ctrl+C at any time to cancel.\n")

        # Detect environment
        print_header("Environment Detection")
        env = detect_environment()
        print_environment_status(env)

        # Check prerequisites
        if not env["docker_available"]:
            print_error("Docker is not available. Please install Docker first.")
            return 1

        if not env["docker_compose_available"]:
            print_error("Docker Compose is not available. Please install Docker Compose first.")
            return 1

        # Determine setup mode based on flags
        full_setup = args.full
        env_only = args.env_only
        no_start = args.no_start
        skip_index = args.skip_index or env_only
        skip_warmup = args.skip_warmup or env_only

        # Configure .env file
        if not env_only:
            print("\n")

        env_configured = configure_env_file(skip_if_exists=False)

        if env_only:
            if env_configured:
                print_success("\nEnvironment configuration complete!")
            return 0

        # Configure .ctxrc (original functionality)
        print_header("CLI Configuration")

        global_mode = args.global_config
        exists, config_path = check_existing_config(global_mode)

        if exists and not args.force:
            if not prompt_yes_no(f"Configuration file already exists at {config_path}. Overwrite?", default=False):
                print_info("Skipping CLI configuration")
                skip_cli_config = True
            else:
                skip_cli_config = False
        else:
            skip_cli_config = False

        if not skip_cli_config:
            # Initialize config data structure
            config_data = {
                "DEFAULT": {},
                "docker": {},
                "remote": {},
                "workspace": {},
                "search": {},
                "indexing": {}
            }

            # Step 1: Choose installation mode
            mode_choice = prompt_choice(
                "How is Context-Engine deployed?",
                ["Docker Compose (local)", "Remote Server"],
                default=0
            )

            if mode_choice == 0:
                # Docker mode
                config_data["DEFAULT"]["mode"] = "docker"

                # Find docker-compose.yml
                compose_path = find_docker_compose()
                if compose_path:
                    print_info(f"Found docker-compose.yml: {compose_path}")
                    use_found = prompt_yes_no("Use this file?", default=True)
                    if use_found:
                        config_data["docker"]["compose_file"] = str(compose_path)
                    else:
                        compose_path_input = prompt_string(
                            "Path to docker-compose.yml",
                            default="./docker-compose.yml"
                        )
                        config_data["docker"]["compose_file"] = compose_path_input
                else:
                    compose_path_input = prompt_string(
                        "Path to docker-compose.yml",
                        default="./docker-compose.yml"
                    )
                    config_data["docker"]["compose_file"] = compose_path_input

                # Get project name
                project_name = prompt_string(
                    "Docker Compose project name",
                    default="context-engine"
                )
                config_data["docker"]["project_name"] = project_name

            else:
                # Remote mode
                config_data["DEFAULT"]["mode"] = "remote"

                # Get server URLs
                while True:
                    indexer_url = prompt_string(
                        "MCP Indexer server URL",
                        default="http://localhost:8003/mcp"
                    )
                    if validate_url(indexer_url):
                        config_data["remote"]["indexer_url"] = indexer_url
                        break
                    else:
                        print_error("Invalid URL. Must start with http:// or https://")

                while True:
                    memory_url = prompt_string(
                        "MCP Memory server URL",
                        default="http://localhost:8002/mcp"
                    )
                    if validate_url(memory_url):
                        config_data["remote"]["memory_url"] = memory_url
                        break
                    else:
                        print_error("Invalid URL. Must start with http:// or https://")

            # Step 2: Project/workspace settings
            print_header("Workspace Settings")

            default_path = prompt_string(
                "Project path to index",
                default=str(Path.cwd())
            )
            config_data["workspace"]["default_path"] = default_path

            # Suggest collection name
            suggested_collection = suggest_collection_name(Path(default_path))
            collection_name = prompt_string(
                "Collection name",
                default=suggested_collection
            )
            config_data["workspace"]["collection"] = collection_name

            # Step 3: Optional search defaults
            print_header("Search Settings (optional)")

            if prompt_yes_no("Configure search defaults?", default=False):
                limit = prompt_string("Default search limit", default="10")
                try:
                    config_data["search"]["default_limit"] = str(int(limit))
                except ValueError:
                    config_data["search"]["default_limit"] = "10"

                compact = prompt_yes_no("Use compact output by default?", default=False)
                config_data["search"]["compact"] = "true" if compact else "false"

                snippets = prompt_yes_no("Include snippets by default?", default=True)
                config_data["search"]["include_snippet"] = "true" if snippets else "false"
            else:
                # Use defaults
                config_data["search"]["default_limit"] = "10"
                config_data["search"]["compact"] = "false"
                config_data["search"]["include_snippet"] = "true"

            # Step 4: Optional indexing settings
            if prompt_yes_no("Configure indexing defaults?", default=False):
                recreate = prompt_yes_no("Recreate collections by default?", default=False)
                config_data["indexing"]["recreate"] = "true" if recreate else "false"
            else:
                config_data["indexing"]["recreate"] = "false"

            # Step 5: Show summary and confirm
            print_summary(config_data, config_path)

            if not prompt_yes_no("\nWrite this configuration?", default=True):
                print_info("Skipping CLI configuration")
            else:
                # Disable cleanup on interrupt (we're past the point of no return)
                _cleanup_on_interrupt = False

                # Write configuration
                write_config(config_data, config_path)
                print_success(f"Configuration written to: {config_path}")

        # Start services if requested
        if not no_start:
            print("\n")

            # Check if services are already running
            any_running = any(env["services_running"].values())

            if any_running:
                if prompt_yes_no("Some services are already running. Restart them?", default=False):
                    should_start = True
                else:
                    should_start = False
            else:
                if full_setup:
                    should_start = True
                else:
                    should_start = prompt_yes_no("Start Docker Compose services now?", default=True)

            if should_start:
                if start_services(build=False):
                    if wait_for_services():
                        # Run initial indexing
                        if not skip_index:
                            print("\n")
                            if full_setup or prompt_yes_no("Run initial indexing?", default=True):
                                run_initial_index()

                        # Warm up models
                        if not skip_warmup:
                            print("\n")
                            if full_setup or prompt_yes_no("Warm up models?", default=True):
                                warmup_models()
                    else:
                        print_warning("Services did not become healthy in time")
                else:
                    print_error("Failed to start services")
                    return 1

        # Final summary
        print("\n")
        if RICH_AVAILABLE:
            console.print(Panel.fit(
                "[bold green]Setup Complete![/bold green]\n\n"
                "Next steps:\n"
                "  • Check status: [cyan]ctx status[/cyan]\n"
                "  • Search code: [cyan]ctx search 'your query'[/cyan]\n"
                "  • Get help: [cyan]ctx --help[/cyan]",
                border_style="green"
            ))
        else:
            print("=" * 60)
            print("Setup Complete!")
            print("=" * 60)
            print("\nNext steps:")
            print("  • Check status: ctx status")
            print("  • Search code: ctx search 'your query'")
            print("  • Get help: ctx --help")

        return 0

    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        return 1
    except Exception as e:
        print_error(f"Error during setup: {e}")
        import traceback
        traceback.print_exc()
        return 1


def register_command(subparsers):
    """Register the init command with the CLI parser."""
    parser = subparsers.add_parser(
        "init",
        help="Interactive setup wizard for Context-Engine",
        description="Configure Context-Engine with .env setup, service management, and initial indexing"
    )

    # Setup mode flags
    parser.add_argument(
        "--full",
        action="store_true",
        help="Complete setup: configure + start services + index + warmup"
    )

    parser.add_argument(
        "--env-only",
        action="store_true",
        help="Only configure .env file, skip CLI config and services"
    )

    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Configure but don't start services"
    )

    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Don't run initial indexing"
    )

    parser.add_argument(
        "--skip-warmup",
        action="store_true",
        help="Don't warm up models"
    )

    # Original flags
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing configuration without prompting"
    )

    parser.add_argument(
        "--global", "-g",
        dest="global_config",
        action="store_true",
        help="Create global configuration in ~/.ctxrc instead of ./.ctxrc"
    )

    parser.set_defaults(func=run_init)
