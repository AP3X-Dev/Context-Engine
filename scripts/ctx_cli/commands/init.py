#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Init command for ctx CLI.

Interactive setup wizard for creating configuration files.

Usage:
  ctx init [--force] [--global]
"""

import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import configparser
import signal


# Track if we should clean up on Ctrl+C
_cleanup_on_interrupt = True


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    if _cleanup_on_interrupt:
        print("\n\nSetup cancelled by user.")
        sys.exit(1)


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


def prompt_choice(question: str, choices: list, default: Optional[int] = None) -> int:
    """
    Prompt user to choose from a list of options.

    Args:
        question: Question to ask
        choices: List of choice descriptions
        default: Default choice index (0-based) or None

    Returns:
        Index of chosen option (0-based)
    """
    print(f"\n{question}")
    for i, choice in enumerate(choices, 1):
        default_marker = " (default)" if default is not None and i - 1 == default else ""
        print(f"  {i}. {choice}{default_marker}")

    while True:
        if default is not None:
            prompt = f"Choice [1-{len(choices)}] (default: {default + 1}): "
        else:
            prompt = f"Choice [1-{len(choices)}]: "

        response = input(prompt).strip()

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


def prompt_string(question: str, default: Optional[str] = None) -> str:
    """
    Prompt user for a string value.

    Args:
        question: Question to ask
        default: Default value or None

    Returns:
        User's response or default
    """
    if default:
        prompt = f"{question} (default: {default}): "
    else:
        prompt = f"{question}: "

    response = input(prompt).strip()

    if not response and default:
        return default

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
    default_text = "Y/n" if default else "y/N"
    prompt = f"{question} [{default_text}]: "

    while True:
        response = input(prompt).strip().lower()

        # Use default if user just pressed Enter
        if not response:
            return default

        if response in ('y', 'yes'):
            return True
        elif response in ('n', 'no'):
            return False
        else:
            print("Please enter 'y' or 'n'")


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


def print_header():
    """Print welcome header."""
    print("=" * 60)
    print("Context-Engine CLI Setup Wizard")
    print("=" * 60)
    print("\nThis wizard will help you configure the Context-Engine CLI.")
    print("Press Ctrl+C at any time to cancel.\n")


def print_summary(config_data: Dict[str, Any], config_path: Path):
    """
    Print configuration summary.

    Args:
        config_data: Configuration data
        config_path: Path where config will be written
    """
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
        # Print header
        print_header()

        # Determine config path
        global_mode = args.global_config
        exists, config_path = check_existing_config(global_mode)

        # Check if config exists and not forcing
        if exists and not args.force:
            print(f"Configuration file already exists: {config_path}")
            if not prompt_yes_no("Overwrite existing configuration?", default=False):
                print("Setup cancelled.")
                return 0

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
                print(f"\nFound docker-compose.yml: {compose_path}")
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
                    print("Invalid URL. Must start with http:// or https://")

            while True:
                memory_url = prompt_string(
                    "MCP Memory server URL",
                    default="http://localhost:8002/mcp"
                )
                if validate_url(memory_url):
                    config_data["remote"]["memory_url"] = memory_url
                    break
                else:
                    print("Invalid URL. Must start with http:// or https://")

        # Step 2: Project/workspace settings
        print("\n--- Workspace Settings ---")

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
        print("\n--- Search Settings (optional) ---")

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
            print("Setup cancelled.")
            return 0

        # Disable cleanup on interrupt (we're past the point of no return)
        _cleanup_on_interrupt = False

        # Write configuration
        write_config(config_data, config_path)
        print(f"\nConfiguration written to: {config_path}")

        # Step 6: Optional post-setup actions
        if config_data["DEFAULT"]["mode"] == "docker":
            print("\n--- Optional Actions ---")

            if prompt_yes_no("Start Docker Compose stack now?", default=False):
                print("\nStarting Docker Compose stack...")
                import subprocess
                compose_file = config_data["docker"]["compose_file"]
                try:
                    subprocess.run(
                        ["docker", "compose", "-f", compose_file, "up", "-d"],
                        check=True
                    )
                    print("Docker Compose stack started successfully!")

                    # Ask about indexing
                    if prompt_yes_no("Index the workspace now?", default=False):
                        print("\nNote: Indexing will be triggered automatically.")
                        print("Monitor progress with: ctx status")
                except subprocess.CalledProcessError as e:
                    print(f"Failed to start Docker Compose: {e}")
                    return 1

        print("\n" + "=" * 60)
        print("Setup complete!")
        print("=" * 60)
        print("\nNext steps:")
        print("  1. Start the stack: ctx up")
        print("  2. Check status: ctx status")
        print("  3. Search code: ctx search 'your query'")
        print("\nFor more commands: ctx --help")

        return 0

    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        return 1
    except Exception as e:
        print(f"\nError during setup: {e}")
        import traceback
        traceback.print_exc()
        return 1


def register_command(subparsers):
    """Register the init command with the CLI parser."""
    parser = subparsers.add_parser(
        "init",
        help="Interactive setup wizard for configuration",
        description="Create or update Context-Engine CLI configuration through an interactive wizard"
    )

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
