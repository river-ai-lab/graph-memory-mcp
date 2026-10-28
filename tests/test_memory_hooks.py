"""The example memory hooks: valid config and the reminder script contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "examples" / "hooks"
SCRIPT = HOOKS / "memory_reminder.py"


def _run(tmp_path, *args: str, payload: dict, every: str = "2") -> dict | None:
    env = {"GRAPH_MEMORY_REMIND_EVERY": every, "TMPDIR": str(tmp_path)}
    out = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=True,
    ).stdout.strip()
    return json.loads(out) if out else None


@pytest.mark.parametrize(
    "path", ["claude-code/settings.json", "cursor/hooks.json"], ids=str
)
def test_hook_config_is_json_and_points_at_the_script(path):
    text = (HOOKS / path).read_text()
    json.loads(text)
    assert "memory_reminder.py" in text


def test_claude_session_start_and_compact(tmp_path):
    start = _run(tmp_path, "claude", "session-start", payload={"source": "startup"})
    assert "get_brief" in start["hookSpecificOutput"]["additionalContext"]
    compact = _run(tmp_path, "claude", "session-start", payload={"source": "compact"})
    assert "GROW" in compact["hookSpecificOutput"]["additionalContext"]


def test_claude_stop_blocks_every_n_and_not_inside_its_followup(tmp_path):
    payload = {"session_id": "s1"}
    assert _run(tmp_path, "claude", "stop", payload=payload) is None
    second = _run(tmp_path, "claude", "stop", payload=payload)
    assert second["decision"] == "block" and "GROW" in second["reason"]
    active = {**payload, "stop_hook_active": True}
    assert _run(tmp_path, "claude", "stop", payload=active) is None


def test_claude_user_prompt_adds_context_every_n(tmp_path):
    payload = {"session_id": "s2"}
    assert _run(tmp_path, "claude", "user-prompt", payload=payload) is None
    second = _run(tmp_path, "claude", "user-prompt", payload=payload)
    assert second["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_cursor_stop_follows_up_once_every_n(tmp_path):
    payload = {"conversation_id": "c1", "status": "completed", "loop_count": 0}
    assert _run(tmp_path, "cursor", "stop", payload=payload) == {}
    assert (
        "GROW" in _run(tmp_path, "cursor", "stop", payload=payload)["followup_message"]
    )
    looped = {**payload, "loop_count": 1}
    assert _run(tmp_path, "cursor", "stop", payload=looped) == {}


def test_zero_disables_periodic_reminders(tmp_path):
    for _ in range(3):
        assert (
            _run(tmp_path, "claude", "stop", payload={"session_id": "s3"}, every="0")
            is None
        )
