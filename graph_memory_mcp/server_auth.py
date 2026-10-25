"""Token-mode MCP entry. Schemas omit arguments the API key decides.

Same handlers as ``graph_memory_mcp.server.GraphMemoryMCP``. The only
difference at the MCP boundary is ``owner_id``: it is not a tool argument.
Each call uses the key's first project (``resolve_token_owner``).

``created_by`` stays off this list. It is not a tool argument on any profile.
Token mode already stores the key name and drops client ``created_by`` /
``updated_by`` from the protected fields. ``metadata``, relation
``properties``, and ``metadata_filter`` stay, because the agent sets
``project``, ``tags``, and the other keys in those objects.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from graph_memory_mcp.base_server import _mcp_instructions
from graph_memory_mcp.config import MCPServerConfig
from graph_memory_mcp.graph_memory.owner_scope import resolve_token_owner
from graph_memory_mcp.server import GraphMemoryMCP

# Filled by the server from the bound API key. Not agent input.
SERVER_OWNED_ARGUMENTS = frozenset({"owner_id"})


def _without_server_owned(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Register ``fn`` without arguments the server fills from the API key."""
    signature = inspect.signature(fn, eval_str=True)
    hidden = [name for name in signature.parameters if name in SERVER_OWNED_ARGUMENTS]
    if not hidden:
        return fn
    visible = [
        param
        for name, param in signature.parameters.items()
        if name not in SERVER_OWNED_ARGUMENTS
    ]
    public = signature.replace(parameters=visible)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        for name in hidden:
            kwargs.pop(name, None)
        bound = public.bind(*args, **kwargs)
        bound.apply_defaults()
        payload = dict(bound.arguments)
        # Resolve before the handler validates. An empty string is not an
        # owner id, and --auth has no owner_id argument to choose a project,
        # so the key's first project is the owner.
        for name in hidden:
            if name == "owner_id":
                payload[name] = resolve_token_owner(None)
        return fn(**payload)

    wrapper.__signature__ = public  # type: ignore[attr-defined]
    annotations = dict(getattr(fn, "__annotations__", {}))
    for name in hidden:
        annotations.pop(name, None)
    wrapper.__annotations__ = annotations
    return wrapper


class GraphMemoryAuthMCP(GraphMemoryMCP):
    """Default tools for ``OWNER_SCOPE=token``, without a client ``owner_id``."""

    def __init__(self, server_config: MCPServerConfig):
        if server_config.owner_scope != "token":
            server_config = server_config.model_copy(update={"owner_scope": "token"})
        super().__init__(server_config)

    def _instructions(self) -> str:
        return _mcp_instructions(self.server_config.owner_scope, hide_owner=True)

    def _owner_tool_help(self) -> str:
        return "The server sets `owner_id` from the API key. Do not pass it."

    def _register_tools(self) -> None:
        mcp = self.mcp
        assert mcp is not None
        original = mcp.tool

        def tool(*args: Any, **kwargs: Any):
            decorator = original(*args, **kwargs)

            def register(fn: Callable[..., Any]) -> Callable[..., Any]:
                hidden = _without_server_owned(fn)
                decorator(hidden)
                return hidden

            return register

        mcp.tool = tool  # type: ignore[method-assign]
        try:
            super()._register_tools()
        finally:
            mcp.tool = original  # type: ignore[method-assign]
