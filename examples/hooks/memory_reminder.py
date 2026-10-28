#!/usr/bin/env python3
"""Remind a coding agent to save durable facts to Graph Memory.

Stdlib only. Reads the hook JSON on stdin and prints the client's reply.

    memory_reminder.py claude session-start|user-prompt|stop
    memory_reminder.py cursor session-start|stop

GRAPH_MEMORY_REMIND_EVERY (default 10) sets how many turns pass between
reminders. 0 turns the periodic reminders off.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

BRIEF = (
    "Graph Memory is connected. Session start: get_brief, then "
    "search(query=<task>, compact=true)."
)
GROW = (
    "Graph Memory checkpoint: if this work produced a durable decision, fact "
    "or outcome, record it with GROW (Ground: search first; Record: one fact "
    "per node with metadata; Orient: link or mark_outdated what it replaces; "
    "Write: create_node or upsert_node). Skip if nothing durable. No chat logs "
    "or secrets."
)


def _every() -> int:
    try:
        return max(0, int(os.environ.get("GRAPH_MEMORY_REMIND_EVERY", "10")))
    except ValueError:
        return 10


def _tick(session: str, name: str) -> int:
    """Increment and return a per-session counter kept in the temp dir."""
    state = Path(tempfile.gettempdir()) / "graph-memory-hooks"
    state.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session or "default")[:120]
    path = state / f"{safe}.{name}"
    try:
        count = int(path.read_text()) + 1
    except (OSError, ValueError):
        count = 1
    path.write_text(str(count))
    return count


def _due(session: str, name: str) -> bool:
    every = _every()
    return every > 0 and _tick(session, name) % every == 0


def claude(event: str, data: dict) -> dict | None:
    session = data.get("session_id", "")
    if event == "session-start":
        text = GROW if data.get("source") == "compact" else BRIEF
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": text,
            }
        }
    if event == "user-prompt" and _due(session, "prompt"):
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": GROW,
            }
        }
    if event == "stop" and not data.get("stop_hook_active"):
        if _due(session, "stop"):
            return {"decision": "block", "reason": GROW}
    return None


def cursor(event: str, data: dict) -> dict | None:
    session = data.get("conversation_id") or data.get("session_id", "")
    if event == "session-start":
        return {"additional_context": BRIEF}
    if event == "stop":
        if data.get("status") == "completed" and not data.get("loop_count"):
            if _due(session, "stop"):
                return {"followup_message": GROW}
        return {}
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("claude", "cursor"):
        print(__doc__, file=sys.stderr)
        return 1
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    handler = claude if argv[1] == "claude" else cursor
    reply = handler(argv[2], data if isinstance(data, dict) else {})
    if reply is not None:
        print(json.dumps(reply))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
