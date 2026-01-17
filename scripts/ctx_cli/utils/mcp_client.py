"""
MCP HTTP client for calling tools.

Provides a simple interface for calling MCP tools via HTTP JSON-RPC.
"""

import json
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from scripts.ctx_cli.utils.config import ConfigManager


class MCPClient:
    """
    MCP HTTP client.

    Calls MCP tools via HTTP JSON-RPC protocol.
    """

    def __init__(
        self,
        server: str = "indexer",
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        """
        Initialize MCP client.

        Args:
            server: Server name ("indexer" or "memory")
            base_url: Base URL for MCP server (overrides config)
            timeout: Request timeout in seconds (overrides config)
        """
        self.server = server
        self.config = ConfigManager()

        # Determine base URL
        if base_url:
            self.base_url = base_url
        elif server == "indexer":
            self.base_url = self.config.get_indexer_url()
        elif server == "memory":
            self.base_url = self.config.get_memory_url()
        else:
            raise ValueError(f"Unknown server: {server}")

        # Ensure /mcp endpoint
        if not self.base_url.endswith("/mcp"):
            self.base_url = f"{self.base_url.rstrip('/')}/mcp"

        # Determine timeout
        if timeout:
            self.timeout = timeout
        else:
            self.timeout = self.config.get_timeout(server)

    def call_tool(
        self,
        tool_name: str,
        **arguments: Any,
    ) -> Dict[str, Any]:
        """
        Call an MCP tool.

        Args:
            tool_name: Name of the tool to call
            **arguments: Tool arguments as keyword arguments

        Returns:
            Parsed tool result

        Raises:
            MCPError: If the call fails
        """
        # Build JSON-RPC payload
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        try:
            # Make HTTP request
            req = Request(
                self.base_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )

            with urlopen(req, timeout=self.timeout) as response:
                response_data = response.read().decode("utf-8")
                result = json.loads(response_data)

                # Check for JSON-RPC error
                if "error" in result:
                    error = result["error"]
                    raise MCPError(
                        error.get("message", "Unknown error"),
                        code=error.get("code", -1),
                        data=error.get("data"),
                    )

                # Extract result
                return self._parse_result(result.get("result", {}))

        except HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass

            raise MCPError(
                f"HTTP {e.code}: {e.reason}",
                code=e.code,
                data=error_body,
            ) from e

        except URLError as e:
            raise MCPError(
                f"Connection failed: {e.reason}",
                code=-1,
            ) from e

        except json.JSONDecodeError as e:
            raise MCPError(
                f"Invalid JSON response: {e}",
                code=-1,
            ) from e

    def _parse_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse MCP result.

        MCP tools return results in different formats:
        1. FastMCP: {"content": [{"type": "text", "text": "..."}]}
        2. Direct: {"results": [...], "total": 10}

        Args:
            result: Raw result from MCP response

        Returns:
            Parsed result data
        """
        # Check for FastMCP content wrapper
        if "content" in result and isinstance(result["content"], list):
            content = result["content"]

            if not content:
                return {"ok": False, "error": "Empty content"}

            first_item = content[0]

            # Check for JSON content
            if isinstance(first_item, dict):
                if "json" in first_item:
                    return first_item["json"]

                # Check for text content that might be JSON
                if "text" in first_item:
                    text = first_item["text"]
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return {"ok": True, "text": text}

            # Fallback to raw content
            return {"ok": True, "content": content}

        # Direct result format (no wrapper)
        if isinstance(result, dict):
            # Add ok flag if not present
            if "ok" not in result:
                result["ok"] = True
            return result

        # Unknown format
        return {"ok": False, "error": "Unknown result format", "raw": result}

    def list_tools(self) -> list:
        """
        List available tools.

        Returns:
            List of tool definitions
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        }

        try:
            req = Request(
                self.base_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )

            with urlopen(req, timeout=self.timeout) as response:
                response_data = response.read().decode("utf-8")
                result = json.loads(response_data)

                if "result" in result:
                    return result["result"].get("tools", [])

                return []

        except Exception:
            return []


class MCPError(Exception):
    """
    MCP error exception.

    Raised when an MCP call fails.
    """

    def __init__(
        self,
        message: str,
        code: int = -1,
        data: Any = None,
    ):
        """
        Initialize MCP error.

        Args:
            message: Error message
            code: Error code
            data: Additional error data
        """
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data

    def __str__(self) -> str:
        """String representation."""
        if self.data:
            return f"{self.message} (code: {self.code}, data: {self.data})"
        return f"{self.message} (code: {self.code})"
