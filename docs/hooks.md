# Memory hooks

Client hooks that remind the agent to save durable facts to Graph Memory.
They are examples: nothing is installed or enabled until you copy them.
No server change, no daemon, no dependencies beyond `python3`.

Files in [`examples/hooks/`](../examples/hooks/):

- `memory_reminder.py` — one stdlib script for both clients
- `claude-code/settings.json` — Claude Code hooks
- `cursor/hooks.json` — Cursor hooks

## What they do

| Moment | Claude Code | Cursor |
|--------|-------------|--------|
| Session start | `SessionStart`: context to call `get_brief`, then `search` | `sessionStart`: same, via `additional_context` |
| After compaction | `SessionStart` with `source=compact`: GROW reminder | — |
| Every N turns | `Stop`: blocks the stop once with the GROW reminder | `stop`: one `followup_message` with the reminder |

The reminder follows GROW from the [memory policy](./memory_policy_cheatsheet.md):
search first, one fact per node, link or `mark_outdated` what it replaces,
skip if nothing is durable.

`GRAPH_MEMORY_REMIND_EVERY` sets N (default `10`). `0` keeps only the
session-start note. The counter lives per session in the system temp dir
(`graph-memory-hooks/`). A reminder never repeats inside its own follow-up:
the script checks `stop_hook_active` (Claude Code) and `loop_count` (Cursor).

## Install

Claude Code, per project:

```bash
mkdir -p .claude/hooks
cp examples/hooks/memory_reminder.py .claude/hooks/
# merge examples/hooks/claude-code/settings.json into .claude/settings.json
```

To remind on the prompt instead of at the end of the turn, add a
`UserPromptSubmit` hook with the `claude user-prompt` arguments. It adds the
reminder as context every N prompts and never blocks.

Cursor, per project:

```bash
mkdir -p .cursor/hooks
cp examples/hooks/memory_reminder.py .cursor/hooks/
cp examples/hooks/cursor/hooks.json .cursor/hooks.json  # or merge
```

For user-level Cursor hooks (`~/.cursor/hooks.json`) use the path
`hooks/memory_reminder.py`; those commands run from `~/.cursor/`.

To disable, remove the entries. Claude Code also honours `"disableAllHooks": true`.

## Limits

- `SessionEnd` (both clients) cannot reach the agent, so it is not used.
- Claude Code `PreCompact` can only block compaction; the reminder runs after
  compaction through `SessionStart` instead.
- Cursor cloud agents skip `sessionStart`; `stop` still runs.

References: [Claude Code hooks](https://code.claude.com/docs/en/hooks),
[Cursor hooks](https://cursor.com/docs/agent/hooks).
