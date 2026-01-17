#!/usr/bin/env python3
# Copyright 2025 John Donalson and Context-Engine Contributors.
# Licensed under the Business Source License 1.1.
"""
Doctor command for ctx CLI.

Comprehensive health check for Context-Engine stack with actionable fix suggestions.

Checks:
1. Docker daemon running
2. Docker Compose installed
3. Required services running (qdrant, indexer, memory)
4. Network connectivity to services
5. Environment variables configured
6. .env file exists and has required keys
7. Model files present (if local models)
8. Disk space adequate
9. MCP endpoints responding
10. Collection exists and has data

Usage:
  ctx doctor [--fix] [--json]
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import socket

from scripts.ctx_cli.utils.mcp_client import MCPClient, MCPError


# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def colored(text: str, color: str) -> str:
    """Add color to text."""
    return f"{color}{text}{Colors.RESET}"


class HealthCheck:
    """Individual health check result."""

    def __init__(
        self,
        name: str,
        passed: bool,
        message: str = "",
        fix_command: Optional[str] = None,
        fix_description: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        self.passed = passed
        self.message = message
        self.fix_command = fix_command
        self.fix_description = fix_description
        self.details = details or {}


class Doctor:
    """Context-Engine health checker."""

    def __init__(self, auto_fix: bool = False):
        self.auto_fix = auto_fix
        self.checks: List[HealthCheck] = []
        self.fixes_applied: List[str] = []

    def run_all_checks(self) -> None:
        """Run all health checks."""
        self.check_docker_daemon()
        self.check_docker_compose()
        self.check_env_file()
        self.check_required_env_vars()
        self.check_docker_services()
        self.check_network_connectivity()
        self.check_mcp_endpoints()
        self.check_collection_status()
        self.check_disk_space()
        self.check_model_files()

    def check_docker_daemon(self) -> None:
        """Check if Docker daemon is running."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
                check=False
            )

            if result.returncode == 0:
                self.checks.append(HealthCheck(
                    name="Docker Daemon",
                    passed=True,
                    message="Docker daemon is running"
                ))
            else:
                self.checks.append(HealthCheck(
                    name="Docker Daemon",
                    passed=False,
                    message="Docker daemon is not responding",
                    fix_command=None,
                    fix_description="Start Docker Desktop or run: sudo systemctl start docker"
                ))

        except FileNotFoundError:
            self.checks.append(HealthCheck(
                name="Docker Daemon",
                passed=False,
                message="Docker is not installed",
                fix_command=None,
                fix_description="Install Docker from https://docs.docker.com/get-docker/"
            ))
        except subprocess.TimeoutExpired:
            self.checks.append(HealthCheck(
                name="Docker Daemon",
                passed=False,
                message="Docker daemon timeout",
                fix_command=None,
                fix_description="Docker may be starting. Wait a moment and try again."
            ))

    def check_docker_compose(self) -> None:
        """Check if Docker Compose is installed."""
        try:
            result = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                timeout=5,
                check=False
            )

            if result.returncode == 0:
                version = result.stdout.decode().strip()
                self.checks.append(HealthCheck(
                    name="Docker Compose",
                    passed=True,
                    message=f"Docker Compose installed ({version})",
                    details={"version": version}
                ))
            else:
                self.checks.append(HealthCheck(
                    name="Docker Compose",
                    passed=False,
                    message="Docker Compose is not available",
                    fix_command=None,
                    fix_description="Update Docker Desktop or install Docker Compose plugin"
                ))

        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.checks.append(HealthCheck(
                name="Docker Compose",
                passed=False,
                message="Docker Compose not found",
                fix_command=None,
                fix_description="Install Docker Compose from https://docs.docker.com/compose/install/"
            ))

    def check_env_file(self) -> None:
        """Check if .env file exists."""
        env_path = Path.cwd() / ".env"

        if env_path.exists():
            # Count non-empty, non-comment lines
            with open(env_path, 'r') as f:
                lines = [l.strip() for l in f if l.strip() and not l.strip().startswith('#')]

            self.checks.append(HealthCheck(
                name="Environment File",
                passed=True,
                message=f".env file exists ({len(lines)} variables)",
                details={"path": str(env_path), "variables": len(lines)}
            ))
        else:
            self.checks.append(HealthCheck(
                name="Environment File",
                passed=False,
                message=".env file not found",
                fix_command="cp .env.example .env",
                fix_description="Copy .env.example to .env and customize settings"
            ))

    def check_required_env_vars(self) -> None:
        """Check if required environment variables are set."""
        # Load .env file if it exists
        env_vars = {}
        env_path = Path.cwd() / ".env"

        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()

        # Required variables
        required = [
            "QDRANT_URL",
            "COLLECTION_NAME",
            "EMBEDDING_MODEL",
        ]

        missing = [var for var in required if var not in env_vars or not env_vars[var]]

        if not missing:
            self.checks.append(HealthCheck(
                name="Required Environment Variables",
                passed=True,
                message=f"All {len(required)} required variables set",
                details={"required": required}
            ))
        else:
            self.checks.append(HealthCheck(
                name="Required Environment Variables",
                passed=False,
                message=f"Missing variables: {', '.join(missing)}",
                fix_command=None,
                fix_description=f"Add these variables to .env file: {', '.join(missing)}",
                details={"missing": missing}
            ))

    def check_docker_services(self) -> None:
        """Check if Docker Compose services are running."""
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False
            )

            if result.returncode != 0:
                self.checks.append(HealthCheck(
                    name="Docker Services",
                    passed=False,
                    message="Cannot get service status",
                    fix_command="ctx up",
                    fix_description="Start services with: ctx up"
                ))
                return

            # Parse service status
            services = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    try:
                        services.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            if not services:
                self.checks.append(HealthCheck(
                    name="Docker Services",
                    passed=False,
                    message="No services found",
                    fix_command="ctx up",
                    fix_description="Start services with: ctx up"
                ))
                return

            # Check required services
            required_services = ["qdrant", "mcp", "mcp_indexer"]
            service_names = {s.get("Service", s.get("Name", "")).lower() for s in services}
            running_services = {
                s.get("Service", s.get("Name", "")).lower()
                for s in services
                if s.get("State") == "running"
            }

            missing = [svc for svc in required_services if svc not in service_names]
            stopped = [svc for svc in required_services if svc in service_names and svc not in running_services]

            if not missing and not stopped:
                self.checks.append(HealthCheck(
                    name="Docker Services",
                    passed=True,
                    message=f"All {len(required_services)} required services running",
                    details={
                        "running": list(running_services),
                        "total": len(services)
                    }
                ))
            else:
                issues = []
                if missing:
                    issues.append(f"missing: {', '.join(missing)}")
                if stopped:
                    issues.append(f"stopped: {', '.join(stopped)}")

                self.checks.append(HealthCheck(
                    name="Docker Services",
                    passed=False,
                    message="; ".join(issues),
                    fix_command="ctx restart",
                    fix_description="Restart services with: ctx restart",
                    details={"missing": missing, "stopped": stopped}
                ))

        except (subprocess.TimeoutExpired, FileNotFoundError):
            self.checks.append(HealthCheck(
                name="Docker Services",
                passed=False,
                message="Cannot check service status",
                fix_command=None,
                fix_description="Ensure Docker is running"
            ))

    def check_network_connectivity(self) -> None:
        """Check network connectivity to services."""
        endpoints = [
            ("Qdrant", "localhost", 6333),
            ("MCP Indexer Health", "localhost", 18003),
            ("MCP Memory Health", "localhost", 18002),
        ]

        reachable = []
        unreachable = []

        for name, host, port in endpoints:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, port))
                sock.close()

                if result == 0:
                    reachable.append(f"{name}:{port}")
                else:
                    unreachable.append(f"{name}:{port}")
            except Exception:
                unreachable.append(f"{name}:{port}")

        if not unreachable:
            self.checks.append(HealthCheck(
                name="Network Connectivity",
                passed=True,
                message=f"All {len(endpoints)} endpoints reachable",
                details={"reachable": reachable}
            ))
        else:
            self.checks.append(HealthCheck(
                name="Network Connectivity",
                passed=False,
                message=f"Unreachable: {', '.join(unreachable)}",
                fix_command="ctx restart",
                fix_description="Services may not be running. Try: ctx restart",
                details={"unreachable": unreachable}
            ))

    def check_mcp_endpoints(self) -> None:
        """Check if MCP endpoints are responding."""
        # Check indexer
        indexer_ok = False
        indexer_error = None

        try:
            client = MCPClient(server="indexer", timeout=5)
            result = client.call_tool("workspace_info")
            indexer_ok = result.get("ok", False)
        except Exception as e:
            indexer_error = str(e)

        # Check memory
        memory_ok = False
        memory_error = None

        try:
            client = MCPClient(server="memory", timeout=5)
            # Try to list tools as a simple health check
            tools = client.list_tools()
            memory_ok = len(tools) > 0
        except Exception as e:
            memory_error = str(e)

        if indexer_ok and memory_ok:
            self.checks.append(HealthCheck(
                name="MCP Endpoints",
                passed=True,
                message="Both indexer and memory MCP endpoints responding"
            ))
        else:
            issues = []
            if not indexer_ok:
                issues.append(f"indexer ({indexer_error or 'not responding'})")
            if not memory_ok:
                issues.append(f"memory ({memory_error or 'not responding'})")

            self.checks.append(HealthCheck(
                name="MCP Endpoints",
                passed=False,
                message=f"Failed: {', '.join(issues)}",
                fix_command="ctx restart",
                fix_description="MCP servers may be starting or crashed. Try: ctx restart"
            ))

    def check_collection_status(self) -> None:
        """Check if collection exists and has data."""
        try:
            client = MCPClient(server="indexer", timeout=5)
            result = client.call_tool("qdrant_status")

            if not result.get("ok"):
                self.checks.append(HealthCheck(
                    name="Collection Status",
                    passed=False,
                    message="Cannot get collection status",
                    fix_command="ctx index",
                    fix_description="Index codebase with: ctx index"
                ))
                return

            count = result.get("count", 0)
            collection = result.get("collection", "unknown")

            if count > 0:
                self.checks.append(HealthCheck(
                    name="Collection Status",
                    passed=True,
                    message=f"Collection '{collection}' has {count:,} points",
                    details={
                        "collection": collection,
                        "points": count
                    }
                ))
            else:
                self.checks.append(HealthCheck(
                    name="Collection Status",
                    passed=False,
                    message=f"Collection '{collection}' is empty",
                    fix_command="ctx index",
                    fix_description="Index codebase with: ctx index",
                    details={"collection": collection}
                ))

        except Exception as e:
            self.checks.append(HealthCheck(
                name="Collection Status",
                passed=False,
                message=f"Error checking collection: {str(e)}",
                fix_command="ctx restart && ctx index",
                fix_description="Restart services and index: ctx restart && ctx index"
            ))

    def check_disk_space(self) -> None:
        """Check if adequate disk space is available."""
        try:
            # Check current directory disk space
            stat = shutil.disk_usage(Path.cwd())

            # Convert to GB
            total_gb = stat.total / (1024 ** 3)
            free_gb = stat.free / (1024 ** 3)
            used_gb = stat.used / (1024 ** 3)
            percent_free = (free_gb / total_gb) * 100

            # Warn if less than 5GB free or less than 10% free
            min_free_gb = 5
            min_percent = 10

            if free_gb >= min_free_gb and percent_free >= min_percent:
                self.checks.append(HealthCheck(
                    name="Disk Space",
                    passed=True,
                    message=f"{free_gb:.1f} GB free ({percent_free:.1f}% of {total_gb:.1f} GB)",
                    details={
                        "total_gb": round(total_gb, 1),
                        "used_gb": round(used_gb, 1),
                        "free_gb": round(free_gb, 1),
                        "percent_free": round(percent_free, 1)
                    }
                ))
            else:
                self.checks.append(HealthCheck(
                    name="Disk Space",
                    passed=False,
                    message=f"Low disk space: {free_gb:.1f} GB free ({percent_free:.1f}%)",
                    fix_command=None,
                    fix_description="Free up disk space. Consider running: docker system prune",
                    details={
                        "total_gb": round(total_gb, 1),
                        "free_gb": round(free_gb, 1),
                        "percent_free": round(percent_free, 1)
                    }
                ))

        except Exception as e:
            self.checks.append(HealthCheck(
                name="Disk Space",
                passed=False,
                message=f"Cannot check disk space: {str(e)}",
                fix_command=None,
                fix_description=None
            ))

    def check_model_files(self) -> None:
        """Check if model files are present (if using local models)."""
        # Load .env to check model configuration
        env_vars = {}
        env_path = Path.cwd() / ".env"

        if env_path.exists():
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()

        # Check for local model paths
        reranker_path = env_vars.get("RERANKER_ONNX_PATH", "")
        tokenizer_path = env_vars.get("RERANKER_TOKENIZER_PATH", "")
        refrag_phi_path = env_vars.get("REFRAG_PHI_PATH", "")

        # Filter out docker paths (those will be in container)
        local_paths = []
        if reranker_path and not reranker_path.startswith("/app/"):
            local_paths.append(("Reranker ONNX", reranker_path))
        if tokenizer_path and not tokenizer_path.startswith("/app/"):
            local_paths.append(("Reranker Tokenizer", tokenizer_path))
        if refrag_phi_path and not refrag_phi_path.startswith("/work/"):
            local_paths.append(("ReFRAG Phi", refrag_phi_path))

        if not local_paths:
            self.checks.append(HealthCheck(
                name="Model Files",
                passed=True,
                message="Using container-bundled models (no local paths configured)"
            ))
            return

        # Check if local paths exist
        missing = []
        present = []

        for name, path in local_paths:
            if Path(path).exists():
                present.append(name)
            else:
                missing.append(f"{name} ({path})")

        if not missing:
            self.checks.append(HealthCheck(
                name="Model Files",
                passed=True,
                message=f"All {len(present)} local model files present",
                details={"present": present}
            ))
        else:
            self.checks.append(HealthCheck(
                name="Model Files",
                passed=False,
                message=f"Missing: {', '.join(missing)}",
                fix_command=None,
                fix_description="Download missing model files or use container-bundled models",
                details={"missing": missing}
            ))

    def print_results(self) -> None:
        """Print health check results in a formatted table."""
        passed = sum(1 for check in self.checks if check.passed)
        total = len(self.checks)

        # Header
        print("\n" + colored("=" * 70, Colors.BOLD))
        print(colored("Context-Engine Health Check", Colors.BOLD))
        print(colored("=" * 70, Colors.BOLD))
        print()

        # Individual checks
        for check in self.checks:
            symbol = colored("✓", Colors.GREEN) if check.passed else colored("✗", Colors.RED)
            status = colored("PASS", Colors.GREEN) if check.passed else colored("FAIL", Colors.RED)

            print(f"{symbol} {check.name.ljust(30)} [{status}]")

            if check.message:
                print(f"  {check.message}")

            if not check.passed and (check.fix_command or check.fix_description):
                if check.fix_command:
                    print(f"  {colored('Fix:', Colors.YELLOW)} {check.fix_command}")
                elif check.fix_description:
                    print(f"  {colored('Fix:', Colors.YELLOW)} {check.fix_description}")

            print()

        # Summary
        print(colored("-" * 70, Colors.BOLD))

        if passed == total:
            summary = colored(f"All {total} checks passed!", Colors.GREEN + Colors.BOLD)
        else:
            failed = total - passed
            summary = colored(f"{passed}/{total} checks passed, {failed} failed",
                            Colors.YELLOW + Colors.BOLD if failed < 3 else Colors.RED + Colors.BOLD)

        print(summary)
        print(colored("-" * 70, Colors.BOLD))
        print()

    def print_json(self) -> None:
        """Print results as JSON."""
        passed = sum(1 for check in self.checks if check.passed)
        total = len(self.checks)

        output = {
            "healthy": passed == total,
            "passed": passed,
            "total": total,
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "message": check.message,
                    "fix_command": check.fix_command,
                    "fix_description": check.fix_description,
                    "details": check.details
                }
                for check in self.checks
            ]
        }

        print(json.dumps(output, indent=2))

    def apply_fixes(self) -> None:
        """Apply automatic fixes where possible."""
        for check in self.checks:
            if not check.passed and check.fix_command:
                print(f"\n{colored('Applying fix:', Colors.YELLOW)} {check.name}")
                print(f"  Running: {check.fix_command}")

                try:
                    # Parse and execute fix command safely (no shell=True)
                    cmd_parts = shlex.split(check.fix_command)
                    result = subprocess.run(
                        cmd_parts,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )

                    if result.returncode == 0:
                        print(f"  {colored('✓', Colors.GREEN)} Fix applied successfully")
                        self.fixes_applied.append(check.name)
                    else:
                        print(f"  {colored('✗', Colors.RED)} Fix failed: {result.stderr}")

                except subprocess.TimeoutExpired:
                    print(f"  {colored('✗', Colors.RED)} Fix timed out")
                except Exception as e:
                    print(f"  {colored('✗', Colors.RED)} Fix error: {str(e)}")


def run_doctor(args) -> int:
    """
    Run the doctor command.

    Args:
        args: Parsed command arguments

    Returns:
        Exit code (0 for all checks passed, 1 for failures)
    """
    doctor = Doctor(auto_fix=args.fix)

    # Run all checks
    doctor.run_all_checks()

    # Apply fixes if requested
    if args.fix:
        doctor.apply_fixes()

        # Re-run checks after fixes
        if doctor.fixes_applied:
            print(f"\n{colored('Re-running checks after fixes...', Colors.BLUE)}\n")
            doctor.checks = []
            doctor.run_all_checks()

    # Output results
    if args.json:
        doctor.print_json()
    else:
        doctor.print_results()

    # Return exit code
    passed = sum(1 for check in doctor.checks if check.passed)
    total = len(doctor.checks)

    return 0 if passed == total else 1


def register_command(subparsers):
    """Register the doctor command with the CLI parser."""
    parser = subparsers.add_parser(
        "doctor",
        help="Run comprehensive health check",
        description="Check Context-Engine stack health and get actionable fix suggestions"
    )

    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to automatically fix issues where possible"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )

    parser.set_defaults(func=run_doctor)
