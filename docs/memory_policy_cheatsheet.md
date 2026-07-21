# Graph Memory — Cheat Sheet

Constants from your operator (apply, never invent): `<OWNER_ID>` required — pass on every call; `<PROJECT>` optional — `metadata={"project": ...}` on writes, `metadata_filter={"project": ...}` on reads; `<AGENT_ID>` optional — `metadata={"created_by": ...}` on writes.

## Rules

1. `search` before `create_node`; one durable fact per node; no chat logs / secrets / scratchpad.
2. Fact became wrong → `mark_outdated` + `create_node`. Typo/metadata → `update_node`.
3. `possible_duplicates` in response: duplicate → link/update; conflict → `CONTRADICTS` or `mark_outdated`.

## Situation → tool

| Situation | Call |
|-----------|------|
| Session start | `get_brief(owner_id)` |
| "What do we know about X?" | `search(query="X")` → `get_context(node_id=<best hit>)` |
| Path between two known IDs | `get_trace(from_id, to_id)` (directed; retry `directed=false`) |
| Quick one-call recall | `recall_context(query, depth=1)` |
| Store a fact | `create_node(text, owner_id, metadata)` |
| Document/conversation → knowledge | extract → `ingest_knowledge(document={"ref": ...}, facts=[{text, ref?, ...}, ...], triplets=[...])` — prefer `facts[].ref`; re-ingest updates in place |
| Link nodes | `create_relation(from_id, to_id, RELATED_TO \| MENTIONS \| SUMMARIZES \| FOLLOWS_FROM \| CONTRADICTS)` |

Full policy: [`memory_policies_for_LLM.md`](./memory_policies_for_LLM.md). Prefer client rules / AGENTS.md over MCP `resources/read`.
