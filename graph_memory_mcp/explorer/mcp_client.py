"""HTTP client for calling Graph Memory MCP tools (streamable HTTP)."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)


def extract_tool_json(result: Any) -> dict[str, Any]:
    """Extract JSON dict from an MCP CallToolResult."""
    content = getattr(result, "content", None)
    if content:
        for block in content:
            block_type = getattr(block, "type", None)
            if block_type == "json":
                data = getattr(block, "json", None)
                if isinstance(data, dict):
                    return data
            text = getattr(block, "text", None)
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return {"raw": text}
    if isinstance(result, dict):
        return result
    return {"raw": repr(result)}


class McpToolClient(Protocol):
    url: str
    connected: bool

    async def connect(self) -> None: ...

    async def close(self) -> None: ...

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class McpHttpClient:
    """Persistent streamable-HTTP session to a running Graph Memory MCP server."""

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.connected = False
        self._external_http_client = http_client
        self._http_client: httpx.AsyncClient | None = None
        self._owns_http_client = False
        self._transport_cm: Any = None
        self._session_cm: Any = None
        self._session: ClientSession | None = None

    async def connect(self) -> None:
        if self.connected:
            return
        if self._external_http_client is not None:
            self._http_client = self._external_http_client
            self._owns_http_client = False
        else:
            self._http_client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_http_client = True
        self._transport_cm = streamable_http_client(
            self.url, http_client=self._http_client
        )
        read, write, _get_session_id = await self._transport_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        session = await self._session_cm.__aenter__()
        if session is None:
            raise RuntimeError("Failed to open MCP client session")
        await session.initialize()
        self._session = session
        self.connected = True
        logger.info("Connected to MCP at %s", self.url)

    async def close(self) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(None, None, None)
            self._session_cm = None
            self._session = None
        if self._transport_cm is not None:
            await self._transport_cm.__aexit__(None, None, None)
            self._transport_cm = None
        if self._http_client is not None and self._owns_http_client:
            await self._http_client.aclose()
        self._http_client = None
        self.connected = False

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._session:
            raise RuntimeError("MCP client is not connected")
        result = await self._session.call_tool(name, arguments=arguments or {})
        return extract_tool_json(result)
