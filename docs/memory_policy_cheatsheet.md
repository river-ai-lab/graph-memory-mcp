# Graph Memory — Cheat Sheet

Constants from your operator (apply, never invent): `<OWNER_ID>` required — pass on every call; `<PROJECT>` optional — `metadata={"project": ...}` on writes, `metadata_filter={"project": ...}` on reads; `<AGENT_ID>` optional — `metadata={"created_by": ...}` on writes.

## Rules

1. `search` before `create_node`; one durable fact per node; no chat logs / secrets / scratchpad; no metric tables in `text`.
2. Fact became wrong → `mark_outdated` + `create_node`. Typo/metadata → `update_node`.
3. `memory_duplicate` or `possible_duplicates`: do not write a third paraphrase. Update, `mark_outdated` + `create_node`, or `check_duplicates=false` only if the fact is different.
4. After meaningful work — GROW before final reply (Ground → Record → Orient? → Write); skip if nothing durable.
5. Temporary note → `ttl_days` (14–30). Decision or durable outcome → no TTL. Server never sets TTL from `type`. Do not store a pod lifecycle. Default search and brief hide facts that have a TTL; `include_ttl=true` shows ones that have not expired.

## Situation → tool

| Situation | Call |
|-----------|------|
| After meaningful work | GROW: Ground → Record → Orient? → Write (`project`+`created_by`); skip if nothing durable |
| Session start | `get_brief(owner_id)` (about + recent facts without TTL + `CONTRADICTS` + `stale_count`; not the task; no `include_stale`) → `search(query=<task>, compact=true)`. `suggested_next` hints at a possible next call; you decide. |
| "What do we know about X?" | `search(query="X", compact=true)`. `suggested_next` is a hint; choose the next call yourself. |
| Opinion changed | `mark_outdated` + `create_node` (no separate supersede tool) |
| Path between two known IDs | `get_trace(from_id, to_id)` (directed; retry `directed=false`) |
| Quick one-call recall | `recall_context(query, depth=1, compact=true)` |
| Store a fact | `create_node(text, owner_id, metadata)`; temporary → also `ttl_days` |
| Document/conversation → knowledge | extract → `ingest_knowledge(document={"ref": ...}, facts=[{text, ref?, ...}, ...], triplets=[...])` — prefer `facts[].ref`; re-ingest updates in place |
| Link nodes | `create_relation(from_id, to_id, RELATED_TO \| MENTIONS \| SUMMARIZES \| FOLLOWS_FROM \| CONTRADICTS)` |

Full policy: [`memory_policies_for_LLM.md`](./memory_policies_for_LLM.md). Prefer client rules / AGENTS.md over MCP `resources/read`.
