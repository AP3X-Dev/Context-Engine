"""
MCP HTTP client for calling tools.

Provides a simple interface for calling MCP tools via HTTP JSON-RPC.
Handles the MCP session handshake automatically.
"""

import json
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from scripts.ctx_cli.utils.config import ConfigManager
import logging



logger = logging.getLogger(__name__)
class MCPClient:
    """
    MCP HTTP client with session handshake.

    Calls MCP tools via HTTP JSON-RPC protocol.
    Automatically handles the initialize/initialized handshake.
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
        self._session_id: Optional[str] = None
        self._request_id = 0

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

    def _next_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    def _parse_sse(self, data: str) -> Dict[str, Any]:
        """
        Parse Server-Sent Events (SSE) response.

        SSE format:
            event: message
            data: {"jsonrpc": "2.0", ...}

        Args:
            data: Raw SSE response body

        Returns:
            Parsed JSON from the last data line
        """
        last_data = None

        for line in data.strip().split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                # Extract JSON after "data: "
                json_str = line[5:].strip()
                if json_str:
                    try:
                        last_data = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue

        if last_data is None:
            # No valid data found, try parsing whole response as JSON
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                raise MCPError(
                    f"No valid JSON in SSE response",
                    code=-1,
                    data=data[:200],
                )

        return last_data

    def _make_request(
        self,
        payload: Dict[str, Any],
        include_session: bool = True,
    ) -> Dict[str, Any]:
        """
        Make HTTP request to MCP server.

        Args:
            payload: JSON-RPC payload
            include_session: Whether to include session ID header

        Returns:
            Parsed response

        Raises:
            MCPError: If request fails
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        if include_session and self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            req = Request(
                self.base_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
            )

            with urlopen(req, timeout=self.timeout) as response:
                # Capture session ID from response headers
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self._session_id = session_id

                response_data = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "")

                # Handle SSE format (text/event-stream)
                if "text/event-stream" in content_type:
                    return self._parse_sse(response_data)

                # Handle plain JSON
                return json.loads(response_data)

        except HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception as e:
                logger.debug(f"Suppressed exception: {e}")

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

    def _ensure_session(self) -> None:
        """
        Ensure MCP session is initialized.

        Performs the initialize/initialized handshake if needed.
        """
        if self._session_id:
            return

        # Step 1: Send initialize request
        init_payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "ctx-cli",
                    "version": "0.1.0",
                },
            },
        }

        result = self._make_request(init_payload, include_session=False)

        # Check for error
        if "error" in result:
            raise MCPError(
                result["error"].get("message", "Initialize failed"),
                code=result["error"].get("code", -1),
            )

        # Step 2: Send initialized notification
        initialized_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }

        # Notifications don't have a response, but we need to send it
        try:
            self._make_request(initialized_payload, include_session=True)
        except MCPError:
            # Some servers may not respond to notifications, that's OK
            pass

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
        # Ensure session is initialized
        self._ensure_session()

        # Build JSON-RPC payload
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        result = self._make_request(payload)

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
        # Ensure session is initialized
        self._ensure_session()

        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
        }

        try:
            result = self._make_request(payload)

            if "result" in result:
                return result["result"].get("tools", [])

            return []

        except MCPError:
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
