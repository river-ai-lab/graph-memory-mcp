"""MCP tool annotation presets shared by every server variant.

All four hints are always set. ``openWorldHint`` is false everywhere: tools
only touch this server's own graph store.
"""

from __future__ import annotations

from mcp.types import ToolAnnotations


def _hints(*, read_only: bool, destructive: bool, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=False,
    )


# Reads only.
READ_ONLY = _hints(read_only=True, destructive=False, idempotent=True)
# Adds new data; a repeated call adds it again.
ADDITIVE = _hints(read_only=False, destructive=False, idempotent=False)
# Adds data by merge; a repeated call changes nothing more.
ADDITIVE_IDEMPOTENT = _hints(read_only=False, destructive=False, idempotent=True)
# Overwrites, outdates or deletes existing data; repeating it is harmless.
DESTRUCTIVE = _hints(read_only=False, destructive=True, idempotent=True)
