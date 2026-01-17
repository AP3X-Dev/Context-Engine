"""
Docker Compose wrapper utilities.

Provides a high-level interface for managing Docker Compose operations.
"""

import subprocess
import time
import socket
from typing import Optional, Tuple, List
from pathlib import Path


def run_docker_compose(
    command: str,
    *args: str,
    cwd: Optional[Path] = None,
    capture_output: bool = False,
    quiet: bool = False,
) -> subprocess.CompletedProcess:
    """
    Run a docker compose command.

    Args:
        command: The docker compose subcommand (e.g., "up", "down")
        *args: Additional arguments to pass to docker compose
        cwd: Working directory (defaults to project root)
        capture_output: Whether to capture stdout/stderr
        quiet: Suppress warning messages from docker compose

    Returns:
        CompletedProcess instance with result

    Raises:
        subprocess.CalledProcessError: If the command fails
    """
    if cwd is None:
        # Default to project root (2 levels up from this file)
        cwd = Path(__file__).resolve().parent.parent.parent.parent

    cmd = ["docker", "compose", command, *args]

    if capture_output:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    elif quiet:
        # Suppress stderr warnings but show stdout
        result = subprocess.run(
            cmd,
            cwd=cwd,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    else:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
        )

    return result


def check_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """
    Check if a TCP port is open.

    Args:
        host: Hostname or IP address
        port: Port number
        timeout: Connection timeout in seconds

    Returns:
        True if port is open, False otherwise
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except (socket.timeout, socket.error):
        return False


def wait_for_health_check(
    host: str,
    port: int,
    timeout: float = 30.0,
    check_interval: float = 0.5,
) -> Tuple[bool, float]:
    """
    Wait for a service to become healthy by checking if its port is open.

    Args:
        host: Hostname or IP address to check
        port: Port number to check
        timeout: Maximum time to wait in seconds
        check_interval: Time between checks in seconds

    Returns:
        Tuple of (success: bool, elapsed_time: float)
    """
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time

        if check_port_open(host, port, timeout=1.0):
            return True, elapsed

        if elapsed >= timeout:
            return False, elapsed

        time.sleep(check_interval)


def get_service_status(service_name: str, cwd: Optional[Path] = None) -> dict:
    """
    Get the status of a docker compose service.

    Args:
        service_name: Name of the service to check
        cwd: Working directory (defaults to project root)

    Returns:
        Dictionary with service status information
    """
    if cwd is None:
        cwd = Path(__file__).resolve().parent.parent.parent.parent

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json", service_name],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )

        if result.stdout.strip():
            import json
            # docker compose ps can return multiple JSON objects, one per line
            lines = result.stdout.strip().split('\n')
            statuses = [json.loads(line) for line in lines if line.strip()]
            if statuses:
                return statuses[0]

        return {"State": "not running"}
    except subprocess.CalledProcessError:
        return {"State": "error"}


class DockerComposeManager:
    """
    High-level Docker Compose manager.

    Provides convenient methods for managing Docker Compose services.
    """

    def __init__(self, cwd: Optional[Path] = None):
        """
        Initialize the manager.

        Args:
            cwd: Working directory (defaults to project root)
        """
        if cwd is None:
            # Default to project root (3 levels up from this file)
            self.cwd = Path(__file__).resolve().parent.parent.parent.parent
        else:
            self.cwd = Path(cwd)

    def _run_command(
        self,
        command: str,
        *args: str,
        capture_output: bool = True,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """
        Run a docker compose command.

        Args:
            command: Docker compose subcommand
            *args: Additional arguments
            capture_output: Whether to capture output
            check: Whether to raise on non-zero exit

        Returns:
            CompletedProcess result
        """
        cmd = ["docker", "compose", command, *args]

        return subprocess.run(
            cmd,
            cwd=self.cwd,
            capture_output=capture_output,
            text=True,
            check=check,
        )

    def up(
        self,
        detach: bool = True,
        build: bool = False,
        services: Optional[List[str]] = None,
    ) -> subprocess.CompletedProcess:
        """
        Start services with docker-compose up.

        Args:
            detach: Run in background
            build: Rebuild images before starting
            services: Specific services to start

        Returns:
            CompletedProcess result
        """
        args = []
        if detach:
            args.append("-d")
        if build:
            args.append("--build")
        if services:
            args.extend(services)

        return self._run_command("up", *args)

    def down(
        self,
        volumes: bool = False,
        remove_orphans: bool = True,
    ) -> subprocess.CompletedProcess:
        """
        Stop services with docker-compose down.

        Args:
            volumes: Remove named volumes
            remove_orphans: Remove orphaned containers

        Returns:
            CompletedProcess result
        """
        args = []
        if volumes:
            args.append("--volumes")
        if remove_orphans:
            args.append("--remove-orphans")

        return self._run_command("down", *args)

    def restart(
        self,
        services: Optional[List[str]] = None,
        timeout: int = 10,
    ) -> subprocess.CompletedProcess:
        """
        Restart services.

        Args:
            services: Specific services to restart
            timeout: Timeout in seconds for stopping

        Returns:
            CompletedProcess result
        """
        args = ["-t", str(timeout)]
        if services:
            args.extend(services)

        return self._run_command("restart", *args)

    def ps(self) -> List[dict]:
        """
        Get status of all services.

        Returns:
            List of service status dictionaries
        """
        result = self._run_command("ps", "--format", "json")

        if result.returncode != 0:
            return []

        import json
        services = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    services.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return services

    def logs(
        self,
        services: Optional[List[str]] = None,
        follow: bool = False,
        tail: Optional[int] = None,
    ) -> subprocess.CompletedProcess:
        """
        View service logs.

        Args:
            services: Specific services to view
            follow: Follow log output
            tail: Number of lines to show from end

        Returns:
            CompletedProcess result
        """
        args = []
        if follow:
            args.append("-f")
        if tail is not None:
            args.extend(["--tail", str(tail)])
        if services:
            args.extend(services)

        return self._run_command("logs", *args, capture_output=False)
